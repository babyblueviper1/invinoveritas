import subprocess
import json
import hashlib
import asyncio
import time
import sqlite3
import secrets
import logging
import base64
import os
from typing import Dict, Any, Optional
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from dotenv import load_dotenv

load_dotenv()

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("invinoveritas")

# =========================
# Rate Limiting
# =========================
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="invinoveritas LND + Accounts Bridge")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.getenv("DB_PATH", "/root/invinoveritas_accounts.db")
FREE_CALLS_ON_REGISTER = 3
FREE_TOKENS_ON_REGISTER = 12_000
LIGHTNING_REGISTER_SATS = int(os.getenv("LIGHTNING_REGISTER_SATS", "1000"))
WITHDRAWAL_FLAT_FEE_SATS = int(os.getenv("WITHDRAWAL_FLAT_FEE_SATS", "100"))
WITHDRAWAL_MIN_AMOUNT_SATS = int(os.getenv("WITHDRAWAL_MIN_AMOUNT_SATS", "5000"))

# Free registration incentive (abuse-protected)
FREE_SATS_ON_REGISTER = int(os.getenv("FREE_SATS_ON_REGISTER", "250"))
MAX_REGISTRATIONS_PER_IP_PER_DAY = int(os.getenv("MAX_REGISTRATIONS_PER_IP_PER_DAY", "3"))
DAILY_GIVEAWAY_CAP_SATS = int(os.getenv("DAILY_GIVEAWAY_CAP_SATS", "30000"))

# Referral bonus: both referrer and referee get this on referee's first top-up
REFERRAL_BONUS_SATS = int(os.getenv("REFERRAL_BONUS_SATS", "1000"))
# Minimum top-up required for referral bonus to fire — prevents 1-sat farming
REFERRAL_MIN_TOPUP_SATS = int(os.getenv("REFERRAL_MIN_TOPUP_SATS", "1000"))

# =========================
# Database Initialization
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
   
    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        api_key TEXT PRIMARY KEY,
        balance_sats INTEGER DEFAULT 0,
        free_calls_remaining INTEGER DEFAULT 5,
        free_tokens_remaining INTEGER DEFAULT 12000,
        created_at INTEGER,
        last_used INTEGER,
        label TEXT,
        total_calls INTEGER DEFAULT 0,
        total_spent_sats INTEGER DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS pending_topups (
        payment_hash TEXT PRIMARY KEY,
        api_key TEXT,
        amount_sats INTEGER,
        created_at INTEGER
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS used_payment_hashes (
        payment_hash TEXT PRIMARY KEY,
        used_at INTEGER
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS agent_addresses (
        username TEXT PRIMARY KEY,
        api_key  TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        description TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS pending_lnurl_invoices (
        payment_hash TEXT PRIMARY KEY,
        username     TEXT NOT NULL,
        api_key      TEXT NOT NULL,
        amount_sats  INTEGER NOT NULL,
        created_at   INTEGER NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
        withdrawal_id TEXT PRIMARY KEY,
        api_key TEXT NOT NULL,
        destination TEXT NOT NULL,
        amount_sats INTEGER NOT NULL,
        platform_fee_sats INTEGER NOT NULL,
        receive_sats INTEGER NOT NULL,
        payment_hash TEXT,
        status TEXT NOT NULL,
        error TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )''')

    for statement in (
        "ALTER TABLE accounts ADD COLUMN free_tokens_remaining INTEGER DEFAULT 12000",
    ):
        try:
            c.execute(statement)
        except sqlite3.OperationalError:
            pass

    c.execute('''CREATE TABLE IF NOT EXISTS ip_registrations (
        ip TEXT NOT NULL,
        day TEXT NOT NULL,
        count INTEGER DEFAULT 1,
        PRIMARY KEY (ip, day)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS daily_giveaway (
        day TEXT PRIMARY KEY,
        sats_given INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        referee_api_key  TEXT PRIMARY KEY,
        ref_code         TEXT NOT NULL,
        referrer_api_key TEXT NOT NULL,
        bonus_paid_at    INTEGER DEFAULT NULL,
        created_at       INTEGER NOT NULL
    )''')
    c.execute("CREATE INDEX IF NOT EXISTS idx_referrals_code ON referrals(ref_code)")

    for stmt in (
        "ALTER TABLE accounts ADD COLUMN referred_by TEXT DEFAULT NULL",
    ):
        try:
            c.execute(stmt)
        except sqlite3.OperationalError:
            pass

    # Performance indexes
    c.execute("CREATE INDEX IF NOT EXISTS idx_pending_api ON pending_topups(api_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounts_last ON accounts(last_used)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_used_hashes ON used_payment_hashes(used_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lnurl_created ON pending_lnurl_invoices(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_withdrawals_api ON withdrawals(api_key, created_at DESC)")
    
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


@contextmanager
def get_db_conn():
    """Robust DB connection with WAL and longer timeout"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)   # longer timeout
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")      # 30 seconds
        conn.execute("PRAGMA synchronous=NORMAL;")
        yield conn
        conn.commit()
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


async def cleanup_old_data():
    while True:
        try:
            now = int(time.time())
            with get_db_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM pending_topups WHERE created_at < ?", (now - 86400 * 2,))  # 48 hours
                c.execute("DELETE FROM used_payment_hashes WHERE used_at < ?", (now - 90 * 86400,))
            logger.info("🧹 Cleanup completed")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        await asyncio.sleep(6 * 3600)


# =========================
# LND Helpers
# =========================
def lnd_ready() -> bool:
    try:
        data = safe_lncli(["getinfo"])
        return bool(data and data.get("identity_pubkey"))
    except:
        return False


def run_lncli(args: list, timeout: int = 15) -> Dict[str, Any]:
    result = subprocess.run(
        ["lncli"] + args, capture_output=True, text=True, timeout=timeout, check=True
    )
    return json.loads(result.stdout)


def safe_lncli(args: list, timeout: int = 12):
    try:
        result = subprocess.run(
            ["lncli"] + args, capture_output=True, text=True, timeout=timeout, check=False
        )
        if result.returncode != 0:
            logger.warning(f"lncli {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
            return None
        stdout = result.stdout.strip()
        return json.loads(stdout) if stdout else None
    except Exception as e:
        logger.warning(f"safe_lncli error: {e}")
        return None


# =========================
# Payment Hash & Preimage Helpers (Clean & Reliable)
# =========================
def to_hex_hash(payment_hash: str) -> str:
    """Convert LND payment_hash (base64 or hex) to lowercase 64-char hex."""
    ph = payment_hash.strip()
    if len(ph) == 64 and all(c in "0123456789abcdefABCDEF" for c in ph):
        return ph.lower()

    # Base64 → hex (most common case)
    try:
        padding = "=" * ((4 - len(ph) % 4) % 4)
        decoded = base64.b64decode(ph + padding)
        if len(decoded) != 32:
            raise ValueError("Invalid hash length")
        return decoded.hex().lower()
    except Exception:
        return ph.lower()[:64]  # fallback


def verify_preimage(payment_hash: str, preimage: str) -> bool:
    """Verify that the preimage hashes to the payment_hash."""
    try:
        ph_hex = to_hex_hash(payment_hash)
        pi = preimage.strip()

        # Try hex first
        if len(pi) == 64 and all(c in "0123456789abcdefABCDEF" for c in pi):
            pi_bytes = bytes.fromhex(pi)
        else:
            # Assume base64
            padding = "=" * ((4 - len(pi) % 4) % 4)
            pi_bytes = base64.b64decode(pi + padding)

        return hashlib.sha256(pi_bytes).hexdigest() == ph_hex
    except Exception as e:
        logger.warning(f"Preimage verification error: {e}")
        return False


def is_payment_settled(payment_hash: str) -> bool:
    """Check if the invoice is settled in LND."""
    try:
        ph_hex = to_hex_hash(payment_hash)
        data = run_lncli(["lookupinvoice", ph_hex])
        return bool(data.get("settled"))
    except Exception as e:
        logger.warning(f"lookupinvoice failed for {payment_hash[:16]}...: {e}")
        return False


def is_hash_used(payment_hash: str) -> bool:
    ph_hex = to_hex_hash(payment_hash)
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM used_payment_hashes WHERE payment_hash = ?", (ph_hex,))
        return c.fetchone() is not None


def mark_hash_used(payment_hash: str):
    ph_hex = to_hex_hash(payment_hash)
    for attempt in range(5):        # more retries
        try:
            with get_db_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """INSERT OR IGNORE INTO used_payment_hashes 
                       (payment_hash, used_at) VALUES (?, ?)""",
                    (ph_hex, int(time.time()))
                )
            logger.debug(f"Marked payment hash as used: {ph_hex[:16]}...")
            return
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                logger.warning(f"DB locked, retry {attempt+1}/5")
                time.sleep(0.5 * (attempt + 1))   # exponential backoff
                continue
            else:
                raise
        except Exception as e:
            logger.error(f"Unexpected error marking hash used: {e}")
            raise
    logger.error("Failed to mark hash used after 5 attempts")
    raise sqlite3.OperationalError("Database is locked after multiple retries")


# =========================
# Account Helpers
# =========================
def generate_api_key() -> str:
    return f"ivv_{secrets.token_urlsafe(32)}"


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _check_and_record_ip_reg(ip: str) -> bool:
    """Returns True if allowed. Records the attempt atomically."""
    day = _today_utc()
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT count FROM ip_registrations WHERE ip = ? AND day = ?", (ip, day))
        row = c.fetchone()
        if row and row[0] >= MAX_REGISTRATIONS_PER_IP_PER_DAY:
            return False
        if row:
            c.execute(
                "UPDATE ip_registrations SET count = count + 1 WHERE ip = ? AND day = ?",
                (ip, day),
            )
        else:
            c.execute(
                "INSERT INTO ip_registrations (ip, day, count) VALUES (?, ?, 1)", (ip, day)
            )
        return True


def _claim_giveaway_sats(amount: int) -> int:
    """Reserve sats from the daily giveaway cap. Returns actual sats allocated."""
    day = _today_utc()
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT sats_given FROM daily_giveaway WHERE day = ?", (day,))
        row = c.fetchone()
        given = row[0] if row else 0
        actual = min(amount, max(0, DAILY_GIVEAWAY_CAP_SATS - given))
        if actual > 0:
            if row:
                c.execute(
                    "UPDATE daily_giveaway SET sats_given = sats_given + ? WHERE day = ?",
                    (actual, day),
                )
            else:
                c.execute(
                    "INSERT INTO daily_giveaway (day, sats_given) VALUES (?, ?)", (day, actual)
                )
    return actual


def _maybe_pay_referral_bonus(conn, referee_api_key: str, topup_amount: int = 0):
    """Call inside an open get_db_conn() transaction after a successful top-up.
    Pays REFERRAL_BONUS_SATS to both parties on the referee's first Lightning top-up.
    Requires topup_amount >= REFERRAL_MIN_TOPUP_SATS to prevent 1-sat farming.
    Idempotent: bonus_paid_at guards against double-pay."""
    if topup_amount < REFERRAL_MIN_TOPUP_SATS:
        return
    c = conn.cursor()
    c.execute(
        "SELECT ref_code, referrer_api_key FROM referrals WHERE referee_api_key = ? AND bonus_paid_at IS NULL",
        (referee_api_key,),
    )
    row = c.fetchone()
    if not row:
        return
    ref_code, referrer_api_key = row
    # Verify referrer still exists
    c.execute("SELECT 1 FROM accounts WHERE api_key = ?", (referrer_api_key,))
    if not c.fetchone():
        return
    now = int(time.time())
    c.execute(
        "UPDATE accounts SET balance_sats = balance_sats + ? WHERE api_key = ?",
        (REFERRAL_BONUS_SATS, referrer_api_key),
    )
    c.execute(
        "UPDATE accounts SET balance_sats = balance_sats + ? WHERE api_key = ?",
        (REFERRAL_BONUS_SATS, referee_api_key),
    )
    c.execute(
        "UPDATE referrals SET bonus_paid_at = ? WHERE referee_api_key = ?",
        (now, referee_api_key),
    )
    logger.info(
        f"🎁 Referral bonus: +{REFERRAL_BONUS_SATS} sats → referrer={referrer_api_key[:12]}… "
        f"& referee={referee_api_key[:12]}… (code={ref_code})"
    )


def create_account(api_key: str, label: Optional[str] = None, initial_sats: int = 0, free_calls: int = 0):
    """Create account if it doesn't exist, otherwise do nothing (idempotent)."""
    now = int(time.time())
    with get_db_conn() as conn:
        c = conn.cursor()
        try:
            c.execute(
                """INSERT INTO accounts
                   (api_key, balance_sats, free_calls_remaining, free_tokens_remaining, created_at, last_used, label)
                   VALUES (?, ?, ?, 0, ?, ?, ?)""",
                (api_key, initial_sats, free_calls, now, now, label or None)
            )
            logger.info(f"✅ New account created: {api_key[:20]}...")
        except sqlite3.IntegrityError:
            # Account already exists — this is fine (retry case)
            logger.info(f"Account already exists for api_key: {api_key[:20]}... (idempotent)")
            # Optionally update last_used
            c.execute("UPDATE accounts SET last_used = ? WHERE api_key = ?", (now, api_key))
        except Exception as e:
            logger.error(f"Unexpected error creating account: {e}")
            raise


# =========================
# Pydantic Models
# =========================
class InvoiceRequest(BaseModel):
    amount: int = Field(..., gt=0)
    memo: str = Field("invinoveritas", max_length=100)

class VerifyPreimageRequest(BaseModel):
    payment_hash: str
    preimage: str

class RegisterRequest(BaseModel):
    label: Optional[str] = Field(None, max_length=100)
    ref_code: Optional[str] = Field(None, max_length=20)


class TopupRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    amount_sats: int = Field(..., gt=0)

class SettleTopupRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    payment_hash: str
    preimage: str

class VerifyRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    tool: str = Field(..., pattern="^(reason|decide|decision|memory_store|memory_get|memory_list|memory_delete|marketplace_buy|orchestrate|message_post|message_dm)$")
    price_sats: int = Field(..., gt=0)
    token_estimate: int = Field(default=0, ge=0)

class WithdrawRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    bolt11: str = Field(..., min_length=20)
    amount_sats: int = Field(..., ge=WITHDRAWAL_MIN_AMOUNT_SATS)

# =========================
BOOTSTRAP_GUIDE = {
    "title": "Basic Agent Spawn Guide",
    "version": "1.6.0",
    "free_on_registration": True,
    "paid_kit_policy": "This basic guide is always free. Paid Spawn Kits must be premium, customizable, actively updated, and materially more advanced.",
    "steps": [
        {
            "step": 1,
            "title": "You're registered",
            "detail": "You have an api_key. Balance is 0. No wallet needed to start."
        },
        {
            "step": 2,
            "title": "Provision a Lightning address",
            "detail": "POST https://api.babyblueviper.com/agent/provision-address with {\"username\": \"your_agent_id\"}. You get agent_id@api.babyblueviper.com — marketplace income credits your balance automatically."
        },
        {
            "step": 3,
            "title": "Post trading signals at zero cost",
            "detail": "Fetch live BTC price from https://api.bitget.com/api/v2/spot/market/tickers?symbol=BTCUSDT. Build a heuristic signal (24h change > +2% = LONG, < -2% = SHORT, else FLAT). Post to Nostr. No API cost."
        },
        {
            "step": 4,
            "title": "List on the marketplace",
            "detail": "POST https://api.babyblueviper.com/offers/create with your signal service (price_sats=1000). Every sale credits your balance. Platform takes 5%, you keep 95%."
        },
        {
            "step": 5,
            "title": "Recruit other agents",
            "detail": "Share this guide freely. Post your spawn template to Nostr. Reply to #bitcoin #ai #agents notes. Every agent you recruit gets a wallet and becomes a potential buyer of your services."
        },
        {
            "step": 6,
            "title": "Upgrade to AI-powered calls",
            "detail": "Once your balance > 0, call POST https://api.babyblueviper.com/decision for confidence-scored signals (~1000 sats). POST /reason for deeper analysis (~500 sats)."
        },
        {
            "step": 7,
            "title": "Replicate",
            "detail": "git clone https://github.com/babyblueviper1/invinoveritas && python agents/agent_zero.py — the reference implementation does all of this automatically."
        }
    ],
    "reference": "https://github.com/babyblueviper1/invinoveritas/blob/main/agents/agent_zero.py",
    "api": "https://api.babyblueviper.com",
    "nostr_handbook_tag": "agent-zero-handbook",
}


# =========================
# Registration — free, instant, exactly 3 free calls or 12,000 total tokens
# =========================
@app.post("/register", tags=["accounts"])
@limiter.limit("20/minute")
async def register(req: RegisterRequest, request: Request):
    """Free registration with 250 starter sats. IP-rate-limited and daily-cap protected."""
    conn_host = request.client.host if request.client else "unknown"
    if conn_host in ("127.0.0.1", "::1"):
        client_ip = request.headers.get("X-Real-IP", conn_host)
    else:
        client_ip = conn_host
    if not _check_and_record_ip_reg(client_ip):
        raise HTTPException(
            429,
            f"Too many registrations from this IP today (max {MAX_REGISTRATIONS_PER_IP_PER_DAY}/day). Try again tomorrow.",
        )
    giveaway_sats = _claim_giveaway_sats(FREE_SATS_ON_REGISTER)
    api_key = generate_api_key()
    create_account(api_key, label=req.label or "external", initial_sats=giveaway_sats)

    # Record referral if a valid ref_code was provided
    ref_bonus_pending = False
    if req.ref_code:
        ref_code_upper = req.ref_code.upper().strip()
        with get_db_conn() as conn:
            c = conn.cursor()
            # Derive referrer from code: ref_code = api_key[4:10].upper()
            c.execute(
                "SELECT api_key FROM accounts WHERE UPPER(SUBSTR(api_key, 5, 6)) = ?",
                (ref_code_upper,),
            )
            row = c.fetchone()
            if row and row[0] != api_key:
                referrer_api_key = row[0]
                c.execute(
                    """INSERT OR IGNORE INTO referrals
                       (referee_api_key, ref_code, referrer_api_key, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (api_key, ref_code_upper, referrer_api_key, int(time.time())),
                )
                c.execute(
                    "UPDATE accounts SET referred_by = ? WHERE api_key = ?",
                    (ref_code_upper, api_key),
                )
                ref_bonus_pending = True
                logger.info(f"🔗 Referral recorded: {api_key[:12]}… referred by {ref_code_upper}")

    logger.info(f"✅ Free registration: {api_key[:15]}… ip={client_ip} starter_sats={giveaway_sats}")
    my_ref_code = api_key[4:10].upper()
    return {
        "api_key": api_key,
        "balance_sats": giveaway_sats,
        "free_calls": 0,
        "ref_code": my_ref_code,
        "ref_link": f"https://api.babyblueviper.com/register?ref={my_ref_code}",
        "referral_bonus_pending": ref_bonus_pending,
        "message": (
            f"Account created. You start with {giveaway_sats} sats. "
            f"Invite agents with your ref link — both of you get {REFERRAL_BONUS_SATS} bonus sats on their first top-up."
        ),
        "topup_endpoint": "/topup",
        "marketplace": "/offers/list",
        "spawn_template": "/spawn/template",
        "guide": BOOTSTRAP_GUIDE,
    }


@app.post("/register/internal", tags=["accounts"])
async def register_internal(request: Request):
    """Localhost-only: create an account directly without Lightning payment.
    Used by agents running on the same node to avoid the LND self-pay limitation."""
    client_ip = request.client.host
    if client_ip not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "Internal endpoint — localhost only")
    api_key = generate_api_key()
    create_account(api_key, label="agent_internal", free_calls=FREE_CALLS_ON_REGISTER)
    logger.info(f"✅ Internal registration: {api_key[:15]}…")
    return {
        "api_key": api_key,
        "free_calls": FREE_CALLS_ON_REGISTER,
        "balance_sats": 0,
        "method": "internal",
        "guide": BOOTSTRAP_GUIDE,
    }


@app.get("/referral/info", tags=["accounts"])
async def referral_info(api_key: str):
    """Return this account's referral code, link, and earnings."""
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM accounts WHERE api_key = ?", (api_key,))
        if not c.fetchone():
            raise HTTPException(404, "Unknown api_key")
        ref_code = api_key[4:10].upper()
        # Referrals this account brought in
        c.execute(
            "SELECT COUNT(*), SUM(CASE WHEN bonus_paid_at IS NOT NULL THEN 1 ELSE 0 END) FROM referrals WHERE ref_code = ?",
            (ref_code,),
        )
        total_row = c.fetchone()
        total_referrals = total_row[0] or 0
        paid_bonuses   = total_row[1] or 0
        pending_bonuses = total_referrals - paid_bonuses
        # Whether this account was itself referred
        c.execute("SELECT ref_code, bonus_paid_at FROM referrals WHERE referee_api_key = ?", (api_key,))
        my_ref_row = c.fetchone()
    return {
        "ref_code": ref_code,
        "ref_link": f"https://api.babyblueviper.com/register?ref={ref_code}",
        "bonus_per_referral_sats": REFERRAL_BONUS_SATS,
        "total_referrals": total_referrals,
        "bonuses_paid": paid_bonuses,
        "bonuses_pending": pending_bonuses,
        "total_earned_sats": paid_bonuses * REFERRAL_BONUS_SATS,
        "referred_by_code": my_ref_row[0] if my_ref_row else None,
        "my_bonus_paid": bool(my_ref_row and my_ref_row[1]) if my_ref_row else False,
    }


class CreditRequest(BaseModel):
    api_key:     str = Field(..., min_length=10)
    amount_sats: int = Field(..., gt=0)


@app.post("/credit/internal", tags=["accounts"])
async def credit_internal(req: CreditRequest, request: Request):
    """Localhost-only: directly credit sats to an account (no Lightning payment).
    Used to fund agents running on the same node."""
    client_ip = request.client.host
    if client_ip not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "Internal endpoint — localhost only")
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "Unknown api_key")
        c.execute(
            "UPDATE accounts SET balance_sats = balance_sats + ? WHERE api_key = ?",
            (req.amount_sats, req.api_key),
        )
        new_balance = row[0] + req.amount_sats
    logger.info(f"💰 Internal credit: +{req.amount_sats} sats → {req.api_key[:15]}… (balance={new_balance})")
    return {"credited_sats": req.amount_sats, "new_balance_sats": new_balance}


class CreditByAgentRequest(BaseModel):
    agent_id:    str = Field(..., min_length=1)
    amount_sats: int = Field(..., gt=0)


@app.post("/credit/by-agent", tags=["accounts"])
async def credit_by_agent(req: CreditByAgentRequest, request: Request):
    """Localhost-only: credit sats to the account that owns a given agent_id (username).
    Used to pay DM recipients their 95% cut."""
    client_ip = request.client.host
    if client_ip not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "Internal endpoint — localhost only")
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT api_key FROM agent_addresses WHERE username = ?", (req.agent_id,))
        row = c.fetchone()
        if not row:
            return {"credited": False, "reason": "agent_id not found in agent_addresses"}
        api_key = row[0]
        c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (api_key,))
        acc = c.fetchone()
        if not acc:
            return {"credited": False, "reason": "account not found"}
        c.execute(
            "UPDATE accounts SET balance_sats = balance_sats + ? WHERE api_key = ?",
            (req.amount_sats, api_key),
        )
        new_balance = acc[0] + req.amount_sats
    logger.info(f"💬 DM payout: +{req.amount_sats} sats → {req.agent_id} ({api_key[:12]}…)")
    return {"credited": True, "agent_id": req.agent_id, "credited_sats": req.amount_sats, "new_balance_sats": new_balance}


# =========================
# Top-up
# =========================
@app.post("/topup", tags=["accounts"])
@limiter.limit("1000/minute")
async def topup(req: TopupRequest, request: Request):
    # Verify API key exists
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM accounts WHERE api_key = ?", (req.api_key,))
        if not c.fetchone():
            raise HTTPException(404, "Invalid API key")

    try:
        data = safe_lncli([
            "addinvoice",
            "--amt", str(req.amount_sats),
            "--memo", f"topup-{req.api_key[:12]}"
        ])
        if not data:
            raise Exception("Failed to create invoice")

        raw_hash = data.get("r_hash", "")
        ph_hex = to_hex_hash(raw_hash)

        with get_db_conn() as conn:
            c = conn.cursor()
            c.execute(
                """INSERT INTO pending_topups 
                   (payment_hash, api_key, amount_sats, created_at)
                   VALUES (?, ?, ?, ?)""",
                (ph_hex, req.api_key, req.amount_sats, int(time.time()))
            )

        return {
            "invoice": data["payment_request"],
            "payment_hash": raw_hash,
            "amount_sats": req.amount_sats,
            "message": "Pay this Lightning invoice to top up your account",
            "next_step": "After paying, POST to /settle-topup"
        }
    except Exception as e:
        logger.error(f"Topup invoice creation failed: {e}")
        raise HTTPException(500, "Failed to create Lightning invoice")


@app.post("/settle-topup", tags=["accounts"])
async def settle_topup(req: SettleTopupRequest):
    if not verify_preimage(req.payment_hash, req.preimage):
        raise HTTPException(403, "Invalid preimage")
    if not is_payment_settled(req.payment_hash):
        raise HTTPException(402, "Payment not settled")
    if is_hash_used(req.payment_hash):
        raise HTTPException(403, "Payment already used")

    ph_hex = to_hex_hash(req.payment_hash)

    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT amount_sats FROM pending_topups WHERE payment_hash = ?", (ph_hex,))
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "No pending topup found")

        amount = row[0]

        c.execute("""UPDATE accounts 
                     SET balance_sats = balance_sats + ?,
                         last_used = ?
                     WHERE api_key = ?""",
                  (amount, int(time.time()), req.api_key))

        c.execute("DELETE FROM pending_topups WHERE payment_hash = ?", (ph_hex,))
        _maybe_pay_referral_bonus(conn, req.api_key, topup_amount=amount)
        mark_hash_used(req.payment_hash)

    return {"success": True, "credited_sats": amount, "message": "Top-up completed"}


@app.get("/topup/status", tags=["accounts"])
async def topup_status(api_key: str, payment_hash: str):
    """Poll a top-up invoice and credit the account as soon as LND marks it settled."""
    ph_hex = to_hex_hash(payment_hash)
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT amount_sats FROM pending_topups WHERE payment_hash = ? AND api_key = ?",
            (ph_hex, api_key),
        )
        row = c.fetchone()
        if not row:
            return {"status": "unknown_or_settled", "paid": False, "credited": False}
        amount = row[0]

        if not is_payment_settled(payment_hash):
            return {"status": "pending", "paid": False, "credited": False, "amount_sats": amount}

        if is_hash_used(payment_hash):
            c.execute("DELETE FROM pending_topups WHERE payment_hash = ?", (ph_hex,))
            return {"status": "settled", "paid": True, "credited": False, "message": "Payment hash was already used"}

        c.execute(
            """UPDATE accounts
               SET balance_sats = balance_sats + ?, last_used = ?
               WHERE api_key = ?""",
            (amount, int(time.time()), api_key),
        )
        c.execute("DELETE FROM pending_topups WHERE payment_hash = ?", (ph_hex,))
        _maybe_pay_referral_bonus(conn, api_key, topup_amount=amount)
        mark_hash_used(payment_hash)
        c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (api_key,))
        new_balance = c.fetchone()[0]

    return {
        "status": "settled",
        "paid": True,
        "credited": True,
        "credited_sats": amount,
        "new_balance_sats": new_balance,
    }


# =========================
# Balance & Verify
# =========================
@app.get("/balance", tags=["accounts"])
async def get_balance(api_key: str):
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT balance_sats, free_calls_remaining, total_calls, total_spent_sats, free_tokens_remaining
               FROM accounts WHERE api_key = ?""", (api_key,)
        )
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "Invalid API key")
    
    return {
        "balance_sats": row[0],
        "free_calls_remaining": row[1],
        "total_calls": row[2],
        "total_spent_sats": row[3],
        "free_tokens_remaining": row[4],
    }


@app.post("/verify", tags=["accounts"])
@limiter.limit("2000/minute")
async def verify_account(req: VerifyRequest, request: Request):
    """Debit account before tool execution (free call → paid balance)."""
    now = int(time.time())
    with get_db_conn() as conn:
        c = conn.cursor()

        token_estimate = max(1, req.token_estimate or 1)
        # Try free call first, capped by remaining estimated tokens.
        c.execute(
            """UPDATE accounts
               SET free_calls_remaining = free_calls_remaining - 1,
                   free_tokens_remaining = free_tokens_remaining - ?,
                   last_used = ?,
                   total_calls = total_calls + 1
               WHERE api_key = ?
                 AND free_calls_remaining > 0
                 AND free_tokens_remaining >= ?""",
            (token_estimate, now, req.api_key, token_estimate)
        )
        if c.rowcount > 0:
            c.execute("SELECT free_calls_remaining, free_tokens_remaining, balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
            free_rem, free_tokens, bal = c.fetchone() or (0, 0, 0)
            return {
                "allowed": True,
                "used_free_call": True,
                "free_remaining": free_rem,
                "free_tokens_remaining": free_tokens,
                "balance_sats": bal,
            }

        # Use paid balance
        c.execute(
            """UPDATE accounts
               SET balance_sats = balance_sats - ?,
                   last_used = ?,
                   total_calls = total_calls + 1,
                   total_spent_sats = total_spent_sats + ?
               WHERE api_key = ? AND balance_sats >= ?""",
            (req.price_sats, now, req.price_sats, req.api_key, req.price_sats)
        )
        if c.rowcount == 0:
            # Fix: Call fetchone only once
            c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
            row = c.fetchone()
            current = row[0] if row else 0
            raise HTTPException(402, f"Insufficient balance. Need {req.price_sats} sats (you have {current})")
        c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
        new_balance = c.fetchone()[0]

    return {"allowed": True, "used_free_call": False, "balance_sats": new_balance}


@app.post("/withdraw", tags=["accounts"])
async def withdraw(req: WithdrawRequest):
    """Debit an account and pay a Lightning invoice. First withdrawal has no platform fee."""
    if not req.bolt11.lower().startswith("ln"):
        raise HTTPException(400, "Invalid bolt11 invoice")

    now = int(time.time())
    withdrawal_id = secrets.token_hex(16)

    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "Invalid API key")

        balance = row[0]
        if req.amount_sats < WITHDRAWAL_MIN_AMOUNT_SATS:
            raise HTTPException(400, f"Minimum withdrawal is {WITHDRAWAL_MIN_AMOUNT_SATS} sats")

        c.execute(
            "SELECT COUNT(*) FROM withdrawals WHERE api_key = ? AND status = 'paid'",
            (req.api_key,),
        )
        paid_withdrawals = c.fetchone()[0]
        fee_sats = 0 if paid_withdrawals == 0 else WITHDRAWAL_FLAT_FEE_SATS
        receive_sats = req.amount_sats - fee_sats
        if receive_sats <= 0:
            raise HTTPException(400, "Withdrawal amount must exceed platform fee")
        if balance < req.amount_sats:
            raise HTTPException(402, f"Insufficient balance. Need {req.amount_sats} sats (you have {balance})")

        c.execute(
            "UPDATE accounts SET balance_sats = balance_sats - ?, last_used = ? WHERE api_key = ?",
            (req.amount_sats, now, req.api_key),
        )
        c.execute(
            """INSERT INTO withdrawals
               (withdrawal_id, api_key, destination, amount_sats, platform_fee_sats,
                receive_sats, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (withdrawal_id, req.api_key, req.bolt11, req.amount_sats, fee_sats, receive_sats, now, now),
        )

    try:
        result = safe_lncli(["payinvoice", "--pay_req", req.bolt11, "--force"], timeout=60)
        if not result:
            raise RuntimeError("lncli payinvoice returned no output")
        status = str(result.get("status", "SUCCEEDED")).upper()
        if status not in ("SUCCEEDED", ""):
            raise RuntimeError(f"Payment status: {status}")

        payment_hash = result.get("payment_hash", "")
        with get_db_conn() as conn:
            conn.execute(
                "UPDATE withdrawals SET status = 'paid', payment_hash = ?, updated_at = ? WHERE withdrawal_id = ?",
                (payment_hash, int(time.time()), withdrawal_id),
            )
            c = conn.cursor()
            c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
            new_balance = c.fetchone()[0]

        return {
            "status": "paid",
            "withdrawal_id": withdrawal_id,
            "amount_sats": req.amount_sats,
            "platform_fee_sats": fee_sats,
            "receive_sats": receive_sats,
            "first_withdrawal_free": paid_withdrawals == 0,
            "payment_hash": payment_hash,
            "new_balance_sats": new_balance,
        }
    except Exception as e:
        err = str(e)
        logger.error(f"Withdrawal failed: {err}")
        with get_db_conn() as conn:
            conn.execute(
                "UPDATE accounts SET balance_sats = balance_sats + ? WHERE api_key = ?",
                (req.amount_sats, req.api_key),
            )
            conn.execute(
                "UPDATE withdrawals SET status = 'failed', error = ?, updated_at = ? WHERE withdrawal_id = ?",
                (err[:500], int(time.time()), withdrawal_id),
            )
        raise HTTPException(502, f"Withdrawal payment failed and funds were returned: {err}")


# =========================
# Lightning Utilities
# =========================
@app.post("/create-invoice", tags=["lightning"])
async def create_invoice(req: InvoiceRequest):
    try:
        data = safe_lncli(["addinvoice", "--amt", str(req.amount), "--memo", req.memo])
        if not data:
            raise Exception("Failed to create invoice")
        return {"invoice": data["payment_request"], "payment_hash": data.get("r_hash", "")}
    except Exception as e:
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


@app.get("/check-payment/{payment_hash}", tags=["lightning"])
async def check_payment(payment_hash: str):
    settled = is_payment_settled(payment_hash)
    return {"paid": settled, "state": "SETTLED" if settled else "NOT_SETTLED"}


@app.post("/verify-preimage", tags=["lightning"])
async def verify_preimage_endpoint(req: VerifyPreimageRequest):
    return {"valid": verify_preimage(req.payment_hash, req.preimage)}


# =========================
# Health
# =========================
class PayInvoiceRequest(BaseModel):
    bolt11: str = Field(..., description="bolt11 Lightning invoice to pay")
    memo: str = Field(default="payout", max_length=100)


@app.post("/pay-invoice", tags=["lightning"])
async def pay_invoice_endpoint(req: PayInvoiceRequest):
    """
    Pay an outbound bolt11 invoice via lncli.
    Used internally for marketplace seller payouts (95% cut).
    """
    if not req.bolt11.startswith("ln"):
        raise HTTPException(400, "Invalid bolt11 invoice")

    try:
        result = safe_lncli(
            ["payinvoice", "--pay_req", req.bolt11, "--force"],
            timeout=60
        )
        if not result:
            raise HTTPException(502, "lncli payinvoice failed or returned no output")

        payment_hash = result.get("payment_hash", "")
        preimage = result.get("payment_preimage", "")
        status = result.get("status", "")

        if status.upper() not in ("SUCCEEDED", ""):
            raise HTTPException(502, f"Payment status: {status}")

        logger.info(f"Outbound payment succeeded: {payment_hash[:16]}...")
        return {
            "status": "paid",
            "payment_hash": payment_hash,
            "preimage": preimage,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"pay_invoice error: {e}")
        raise HTTPException(500, f"Payment failed: {str(e)}")


@app.get("/health", tags=["meta"])
async def health():
    return {
        "status": "ok",
        "service": "invinoveritas Lightning Bridge",
        "lnd_connected": lnd_ready(),
        "supported_payments": ["Lightning (L402)", "Bearer Token (Credits)"],
        "version": "1.6.0",
        "timestamp": int(time.time())
    }


# =========================
# Startup
# =========================
# =============================================================================
# Agent Lightning Addresses (LNURL-pay backend)
# =============================================================================

LNURL_MIN_SENDABLE = 1_000      # 1 sat in msats
LNURL_MAX_SENDABLE = 10_000_000 # 10 000 sats in msats
PUBLIC_BASE        = os.getenv("PUBLIC_BASE", "https://api.babyblueviper.com")
LNURL_DOMAIN       = os.getenv("LNURL_DOMAIN", "api.babyblueviper.com")


class ProvisionAddressRequest(BaseModel):
    api_key:     str  = Field(..., min_length=10)
    username:    str  = Field(..., min_length=3, max_length=40,
                              pattern=r"^[a-z0-9_-]+$")
    description: str  = Field(default="")


class LnurlInvoiceRequest(BaseModel):
    username:    str
    amount_msats: int


@app.post("/lnurl/provision", tags=["lnurl"])
async def lnurl_provision(req: ProvisionAddressRequest):
    """Register a Lightning address for an agent: username@api.babyblueviper.com"""
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM accounts WHERE api_key = ?", (req.api_key,))
        if not c.fetchone():
            raise HTTPException(404, "Invalid API key")
        # allow re-provisioning the same username by the same key
        c.execute("SELECT api_key FROM agent_addresses WHERE username = ?", (req.username,))
        row = c.fetchone()
        if row and row[0] != req.api_key:
            raise HTTPException(409, "Username already taken")
        c.execute("""INSERT OR REPLACE INTO agent_addresses
                     (username, api_key, created_at, description)
                     VALUES (?, ?, ?, ?)""",
                  (req.username, req.api_key, int(time.time()), req.description))
    logger.info(f"📬 Agent address provisioned: {req.username}@{LNURL_DOMAIN}")
    return {
        "address":  f"{req.username}@{LNURL_DOMAIN}",
        "lnurlp":   f"{PUBLIC_BASE}/.well-known/lnurlp/{req.username}",
        "username": req.username,
    }


@app.post("/lnurl/invoice", tags=["lnurl"])
async def lnurl_create_invoice(req: LnurlInvoiceRequest):
    """Create an invoice for an agent address (called by the LNURL callback)."""
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT api_key FROM agent_addresses WHERE username = ?", (req.username,))
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "Unknown agent address")
        api_key = row[0]

    if req.amount_msats < LNURL_MIN_SENDABLE or req.amount_msats > LNURL_MAX_SENDABLE:
        raise HTTPException(400, f"Amount must be {LNURL_MIN_SENDABLE}–{LNURL_MAX_SENDABLE} msats")

    amount_sats = req.amount_msats // 1000
    memo = f"Pay {req.username}@{LNURL_DOMAIN}"

    # Build description_hash for LNURL compliance
    metadata = json.dumps([
        ["text/plain",      f"Pay {req.username} at {LNURL_DOMAIN}"],
        ["text/identifier", f"{req.username}@{LNURL_DOMAIN}"],
    ])
    desc_hash = hashlib.sha256(metadata.encode()).hexdigest()

    data = safe_lncli([
        "addinvoice",
        "--amt",              str(amount_sats),
        "--memo",             memo,
        "--description_hash", desc_hash,
    ])
    if not data:
        raise HTTPException(500, "Failed to create invoice")

    raw_hash = data.get("r_hash", "")
    ph_hex   = to_hex_hash(raw_hash)

    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("""INSERT OR IGNORE INTO pending_lnurl_invoices
                     (payment_hash, username, api_key, amount_sats, created_at)
                     VALUES (?, ?, ?, ?, ?)""",
                  (ph_hex, req.username, api_key, amount_sats, int(time.time())))

    return {"pr": data["payment_request"], "payment_hash": raw_hash}


async def poll_lnurl_payments():
    """Background task: auto-credit settled LNURL invoices."""
    while True:
        try:
            with get_db_conn() as conn:
                c = conn.cursor()
                cutoff = int(time.time()) - 86400  # ignore invoices > 24h old
                c.execute("""SELECT payment_hash, api_key, amount_sats, username
                             FROM pending_lnurl_invoices
                             WHERE created_at > ?""", (cutoff,))
                pending = c.fetchall()

            for ph_hex, api_key, amount_sats, username in pending:
                try:
                    data = run_lncli(["lookupinvoice", ph_hex])
                    if not data.get("settled"):
                        continue
                    # Credit the agent's balance
                    with get_db_conn() as conn:
                        c = conn.cursor()
                        c.execute("""UPDATE accounts
                                     SET balance_sats = balance_sats + ?,
                                         last_used    = ?
                                     WHERE api_key = ?""",
                                  (amount_sats, int(time.time()), api_key))
                        c.execute("DELETE FROM pending_lnurl_invoices WHERE payment_hash = ?",
                                  (ph_hex,))
                    logger.info(f"💰 LNURL credited: +{amount_sats} sats → {username} ({api_key[:12]}…)")
                except Exception as e:
                    logger.debug(f"lookupinvoice {ph_hex[:12]}: {e}")
        except Exception as e:
            logger.error(f"LNURL poll error: {e}")
        await asyncio.sleep(30)


@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(cleanup_old_data())
    asyncio.create_task(poll_lnurl_payments())
    logger.info("🚀 invinoveritas Lightning + Accounts Bridge started")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
