import subprocess
import json
import hashlib
import asyncio
import time
import sqlite3
import secrets
import logging
import base64
import requests
import os
from typing import Dict, Any, Optional
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address

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

# =========================
# x402 Setup
# =========================
try:
    from x402 import x402ResourceServer
    X402_AVAILABLE = True
except ImportError:
    X402_AVAILABLE = False
    logger.warning("x402 library not found. Only basic header check enabled.")

app = FastAPI(title="invinoveritas LND + Accounts + x402 Bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.getenv("DB_PATH", "/root/invinoveritas_accounts.db")

# =========================
# x402 Top-up Configuration + Live Price
# =========================
X402_PAY_TO          = os.getenv("X402_PAY_TO", "").strip()
X402_NETWORK         = os.getenv("X402_NETWORK", "base")
USDC_CONTRACT        = os.getenv("USDC_CONTRACT", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

FREE_CALLS_ON_REGISTER = int(os.getenv("FREE_CALLS_ON_REGISTER", "5"))
LIGHTNING_REGISTER_SATS = int(os.getenv("LIGHTNING_REGISTER_SATS", "1000"))

X402_MIN_TOPUP_USDC = float(os.getenv("X402_MIN_TOPUP_USDC", "15.00"))

# Live price cache
last_price_fetch_time = 0.0
cached_sats_per_usdc = 1000


def save_price_to_history(btc_price_usd: float, sats_per_usdc: int):
    """Save price + automatic cleanup (keep last 7 days)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        now = time.time()

        c.execute(
            "INSERT INTO price_history (timestamp, btc_price_usd, sats_per_usdc) VALUES (?, ?, ?)",
            (now, btc_price_usd, sats_per_usdc)
        )

        # Cleanup old records (> 7 days)
        cutoff = now - (7 * 86400)
        c.execute("DELETE FROM price_history WHERE timestamp < ?", (cutoff,))

        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to save price to history: {e}")


def get_fallback_sats_per_usdc() -> int:
    """Get most recent saved price as fallback"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT sats_per_usdc FROM price_history ORDER BY timestamp DESC LIMIT 1")
        row = c.fetchone()
        conn.close()
        if row and row[0]:
            return int(row[0])
    except Exception:
        pass
    return 1000


def get_live_sats_per_usdc() -> int:
    """Fetch current sats per USDC from Mempool with DB fallback"""
    global last_price_fetch_time, cached_sats_per_usdc

    now = time.time()
    if now - last_price_fetch_time < 600:   # 10 minute cache
        return cached_sats_per_usdc

    try:
        r = requests.get("https://mempool.space/api/v1/prices", timeout=6)
        r.raise_for_status()
        data = r.json()
        btc_price_usd = float(data.get("USD", 0))

        if btc_price_usd > 0:
            sats_per_usdc = int(100_000_000 / btc_price_usd)
            sats_per_usdc = max(600, min(2000, sats_per_usdc))   # safety bounds

            cached_sats_per_usdc = sats_per_usdc
            last_price_fetch_time = now

            save_price_to_history(btc_price_usd, sats_per_usdc)

            logger.info(f"Live BTC price from mempool: ${btc_price_usd:,.0f} → {sats_per_usdc} sats per USDC")
            return sats_per_usdc

    except Exception as e:
        logger.warning(f"Mempool price fetch failed: {e}")

    # Fallback
    fallback = get_fallback_sats_per_usdc()
    logger.info(f"Using fallback SATS_PER_USDC: {fallback}")
    return fallback


# =========================
# Database Initialization + Cleanup
# =========================

def init_db():
    """Initialize all tables in one database file"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Main accounts table
    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        api_key TEXT PRIMARY KEY,
        balance_sats INTEGER DEFAULT 0,
        free_calls_remaining INTEGER DEFAULT 5,
        created_at INTEGER,
        last_used INTEGER,
        label TEXT,
        total_calls INTEGER DEFAULT 0,
        total_spent_sats INTEGER DEFAULT 0
    )''')

    # Pending top-ups
    c.execute('''CREATE TABLE IF NOT EXISTS pending_topups (
        payment_hash TEXT PRIMARY KEY,
        api_key TEXT,
        amount_sats INTEGER,
        created_at INTEGER
    )''')

    # Used L402 payments (replay protection)
    c.execute('''CREATE TABLE IF NOT EXISTS used_payment_hashes (
        payment_hash TEXT PRIMARY KEY,
        used_at INTEGER
    )''')

    # Price history for live SATS_PER_USDC fallback
    c.execute('''CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY,
        timestamp REAL,
        btc_price_usd REAL,
        sats_per_usdc INTEGER,
        source TEXT DEFAULT "mempool"
    )''')

    # Performance indexes
    c.execute("CREATE INDEX IF NOT EXISTS idx_pending_api ON pending_topups(api_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounts_last ON accounts(last_used)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_used_hashes ON used_payment_hashes(used_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_price_time ON price_history(timestamp)")

    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


@contextmanager
def get_db_conn():
    """Context manager for safe DB connections"""
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


async def cleanup_old_data():
    """Comprehensive background cleanup - runs every 6 hours"""
    while True:
        try:
            now = int(time.time())

            with get_db_conn() as conn:
                c = conn.cursor()

                # 1. Clean old pending_topups (24h) - these are unpaid
                c.execute("DELETE FROM pending_topups WHERE created_at < ?", 
                         (now - 86400,))
                pending_cleaned = c.rowcount

                # 2. Clean old used_payment_hashes (30 days)
                c.execute("DELETE FROM used_payment_hashes WHERE used_at < ?", 
                         (now - 30 * 86400,))
                hashes_cleaned = c.rowcount

                # 3. Clean old price_history (7 days)
                c.execute("DELETE FROM price_history WHERE timestamp < ?", 
                         (now - 7 * 86400,))
                price_cleaned = c.rowcount

                # 4. Light cleanup for accounts: only zero out extremely inactive + zero-balance accounts
                #    (e.g. 2 years of no activity and no balance)
                two_years_ago = now - (2 * 365 * 86400)
                c.execute("""
                    UPDATE accounts 
                    SET balance_sats = 0,
                        free_calls_remaining = 0
                    WHERE last_used < ? 
                      AND balance_sats <= 0 
                      AND free_calls_remaining <= 0
                """, (two_years_ago,))
                accounts_zeroed = c.rowcount

                conn.commit()

            if pending_cleaned or hashes_cleaned or price_cleaned or accounts_zeroed:
                logger.info(f"🧹 Cleanup completed — pending: {pending_cleaned}, "
                           f"used_hashes: {hashes_cleaned}, price: {price_cleaned}, "
                           f"accounts_zeroed: {accounts_zeroed}")

        except Exception as e:
            logger.error(f"Error during cleanup_old_data: {e}")

        await asyncio.sleep(6 * 3600)   # Every 6 hours


# =========================
# Startup (bridge.py on VPS)
# =========================
@app.on_event("startup")
async def startup_event():
    """Initialize bridge services"""
    
    # Initialize all tables (accounts, pending_topups, used_payments, price_history)
    init_db()

    # Start background cleanup task
    asyncio.create_task(cleanup_old_data())

    logger.info(f"🚀 invinoveritas LND + Accounts + x402 Bridge started successfully on VPS")
    logger.info("Background task active: cleanup_old_data (every 6 hours)")
    
# =========================
# Pydantic Models
# =========================

class InvoiceRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount in satoshis")
    memo: str = Field("invinoveritas", max_length=100)

class VerifyPreimageRequest(BaseModel):
    payment_hash: str
    preimage: str

class RegisterRequest(BaseModel):
    label: Optional[str] = Field(None, max_length=100)

class RegisterConfirmRequest(BaseModel):
    payment_hash: str
    preimage: str
    label: Optional[str] = None

class TopupRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    amount_sats: int = Field(..., gt=0)
    amount_usdc: Optional[str] = Field(None, description="USDC amount for top-up (minimum 15.00)")

class SettleTopupRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    payment_hash: str
    preimage: str

class VerifyRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    tool: str = Field(..., pattern="^(reason|decide)$")
    price_sats: int = Field(..., gt=0)


# =========================
# LND Helpers
# =========================

def lnd_ready() -> bool:
    """Check if LND is responsive"""
    try:
        # Try standard call
        data = safe_lncli(["getinfo"])
        if data and isinstance(data, dict) and "identity_pubkey" in data:
            logger.info("LND is connected and responsive")
            return True

        # Try with explicit network flag (many nodes need this)
        data = safe_lncli(["--network=mainnet", "getinfo"])
        if data and isinstance(data, dict) and "identity_pubkey" in data:
            logger.info("LND is connected (mainnet flag used)")
            return True

        logger.warning("LND getinfo returned unexpected data")
        return False
    except Exception as e:
        logger.warning(f"LND readiness check failed: {type(e).__name__}: {e}")
        return False

def run_lncli(args: list, timeout: int = 15) -> Dict[str, Any]:
    result = subprocess.run(
        ["lncli"] + args,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise Exception(f"lncli error: {error}")
    return json.loads(result.stdout)

def safe_lncli(args: list, timeout: int = 15):
    """Safe wrapper around lncli commands"""
    try:
        full_cmd = ["lncli"] + args
        result = subprocess.run(
            full_cmd, 
            capture_output=True, 
            text=True, 
            timeout=timeout,
            check=False
        )
        
        if result.returncode != 0:
            logger.warning(f"lncli failed: {result.stderr.strip()}")
            return None
            
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning("lncli returned non-JSON output")
            return None
            
    except subprocess.TimeoutExpired:
        logger.warning("lncli command timed out")
        return None
    except Exception as e:
        logger.warning(f"safe_lncli exception: {e}")
        return None

# =========================
# Payment Helpers
# =========================

def normalize_payment_hash(ph: str) -> str:
    ph = ph.strip()
    if len(ph) == 64 and all(c in "0123456789abcdefABCDEF" for c in ph):
        return ph.lower()
    try:
        decoded = base64.b64decode(ph + "=="[:2])
        return decoded.hex()
    except Exception:
        return ph.lower()

def verify_preimage_logic(payment_hash: str, preimage: str) -> bool:
    try:
        ph = normalize_payment_hash(payment_hash)
        pi = preimage.strip()
        if len(pi) == 64 and all(c in "0123456789abcdefABCDEF" for c in pi):
            pi_bytes = bytes.fromhex(pi)
        else:
            pi_bytes = base64.b64decode(pi + "=="[:2])
        computed = hashlib.sha256(pi_bytes).hexdigest()
        return computed == ph
    except Exception as e:
        logger.warning(f"Preimage verification error: {e}")
        return False

def check_payment_logic(payment_hash: str) -> bool:
    try:
        ph = normalize_payment_hash(payment_hash)
        data = run_lncli(["lookupinvoice", ph], timeout=10)
        return bool(data.get("settled"))
    except Exception:
        return False

def is_hash_used(payment_hash: str) -> bool:
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM used_payment_hashes WHERE payment_hash = ?",
                  (normalize_payment_hash(payment_hash),))
        return c.fetchone() is not None

def mark_hash_used(payment_hash: str):
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO used_payment_hashes (payment_hash, used_at) VALUES (?, ?)",
            (normalize_payment_hash(payment_hash), int(time.time()))
        )

# =========================
# Account Helpers
# =========================

def generate_api_key() -> str:
    return f"ivv_{secrets.token_urlsafe(32)}"


def create_account_db(api_key: str, label: Optional[str] = None):
    """Create new account with 5 free calls"""
    now = int(time.time())
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO accounts 
               (api_key, balance_sats, free_calls_remaining, created_at, last_used, label)
               VALUES (?, 0, ?, ?, ?, ?)""",
            (api_key, FREE_CALLS_ON_REGISTER, now, now, label or None)
        )


# =========================
# Registration Endpoints
# =========================

@app.post("/register", tags=["accounts"])
@limiter.limit("10/minute")
async def register(req: RegisterRequest, request: Request):
    """Create new account via Lightning (~1000 sats) or x402 USDC (min $15)."""
    x402_header = request.headers.get("X-Payment")
    api_key = generate_api_key()

    # x402 registration flow
    if x402_header and X402_AVAILABLE and X402_PAY_TO:
        try:
            create_account_db(api_key, req.label)
            logger.info(f"Account created via x402: {api_key[:15]}...")

            return {
                "status": "success",
                "api_key": api_key,
                "free_calls_remaining": FREE_CALLS_ON_REGISTER,
                "message": f"Account successfully created with {FREE_CALLS_ON_REGISTER} free calls.",
                "important_note": (
                    "Your account and any credits (including future top-ups) will remain active "
                    "for at least 2 years of inactivity. Only completely unused accounts with "
                    "zero balance for over 2 years may be archived (balance reset to 0)."
                ),
                "payment_method": "x402 USDC (registration)",
                "next_steps": "Use 'Authorization: Bearer <api_key>' for all calls. Top up anytime at /topup."
            }
        except Exception as e:
            logger.error(f"x402 registration failed: {e}")
            raise HTTPException(500, "Failed to create account")

    # x402 challenge
    if X402_AVAILABLE and X402_PAY_TO:
        accepts = [{
            "scheme": "exact",
            "network": X402_NETWORK,
            "maxAmountRequired": str(X402_MIN_TOPUP_USDC),
            "resource": str(request.url),
            "description": f"invinoveritas account registration (min ${X402_MIN_TOPUP_USDC} USDC)",
            "payTo": X402_PAY_TO,
            "asset": USDC_CONTRACT,
            "extra": {"name": "USD Coin"}
        }]
        return JSONResponse(
            status_code=402,
            content={
                "x402Version": 1,
                "accepts": accepts,
                "error": "Payment required",
                "message": f"Registration requires minimum ${X402_MIN_TOPUP_USDC} USDC via x402 on Base.",
                "lightning_alternative": f"Pay ~{LIGHTNING_REGISTER_SATS} sats via Lightning for cheaper/faster registration.",
                "note": "Accounts stay active for at least 2 years even with no usage."
            },
            headers={"X-Payment-Required": "true"}
        )

    # Lightning registration fallback
    try:
        data = safe_lncli([
            "addinvoice",
            "--amt", str(LIGHTNING_REGISTER_SATS),
            "--memo", "invinoveritas account creation"
        ])
        return {
            "invoice": data["payment_request"],
            "payment_hash": data.get("r_hash", ""),
            "amount_sats": LIGHTNING_REGISTER_SATS,
            "message": f"Pay this Lightning invoice (~{LIGHTNING_REGISTER_SATS} sats) to create your account + receive {FREE_CALLS_ON_REGISTER} free calls.",
            "free_calls_on_creation": FREE_CALLS_ON_REGISTER,
            "important_note": (
                "Your account and any balance will remain active for at least 2 years of inactivity. "
                "Only completely unused accounts with zero balance for over 2 years may be archived."
            ),
            "next_step": "After paying, POST to /register/confirm with the payment_hash to finalize."
        }
    except Exception as e:
        logger.error(f"Lightning invoice creation failed: {e}")
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


# =========================
# Top-up Endpoints
# =========================

@app.post("/topup", tags=["accounts"])
@limiter.limit("10/minute")
async def topup(req: TopupRequest, request: Request):
    """Top up existing Bearer account via Lightning or x402 USDC."""
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM accounts WHERE api_key = ?", (req.api_key,))
        if not c.fetchone():
            raise HTTPException(404, "Invalid API key")

    x402_header = request.headers.get("X-Payment")

    # x402 USDC Bulk Top-up
    if x402_header and X402_AVAILABLE and X402_PAY_TO:
        try:
            usdc_amount = float(req.amount_usdc or X402_MIN_TOPUP_USDC)
            if usdc_amount < X402_MIN_TOPUP_USDC:
                raise HTTPException(400, f"Minimum x402 top-up is ${X402_MIN_TOPUP_USDC} USDC")

            sats_to_credit = int(usdc_amount * get_live_sats_per_usdc())

            with get_db_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """UPDATE accounts 
                       SET balance_sats = balance_sats + ?,
                           last_used = ?
                       WHERE api_key = ?""",
                    (sats_to_credit, int(time.time()), req.api_key)
                )
                c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
                new_balance = c.fetchone()[0]

            logger.info(f"x402 top-up: ${usdc_amount} USDC → {sats_to_credit} virtual sats")

            return {
                "success": True,
                "credited_usdc": usdc_amount,
                "credited_sats": sats_to_credit,
                "new_balance_sats": new_balance,
                "message": "Top-up completed successfully.",
                "important_note": (
                    "Your updated balance will remain available for at least 2 years of inactivity. "
                    "Only completely unused + zero-balance accounts older than 2 years may be archived."
                ),
                "payment_method": "x402 USDC (bulk top-up)",
                "rate_used": "live from mempool.space"
            }
        except ValueError:
            raise HTTPException(400, "Invalid amount_usdc")
        except Exception as e:
            logger.error(f"x402 top-up failed: {e}")
            raise HTTPException(500, "Top-up failed")

    # Lightning top-up (unchanged)
    try:
        data = safe_lncli([
            "addinvoice",
            "--amt", str(req.amount_sats),
            "--memo", f"topup-{req.api_key[:12]}"
        ])
        payment_hash = data.get("r_hash", "")

        with get_db_conn() as conn:
            c = conn.cursor()
            c.execute(
                """INSERT INTO pending_topups (payment_hash, api_key, amount_sats, created_at)
                   VALUES (?, ?, ?, ?)""",
                (normalize_payment_hash(payment_hash), req.api_key, req.amount_sats, int(time.time()))
            )

        return {
            "invoice": data["payment_request"],
            "payment_hash": payment_hash,
            "amount_sats": req.amount_sats,
            "message": "Pay this Lightning invoice to top up your account.",
            "next_step": "POST /settle-topup"
        }
    except Exception as e:
        logger.error(f"Lightning top-up failed: {e}")
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


# =========================
# Balance & Verify (unchanged)
# =========================

@app.get("/balance", tags=["accounts"])
async def get_balance(api_key: str):
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT balance_sats, free_calls_remaining, total_calls, total_spent_sats 
               FROM accounts WHERE api_key = ?""",
            (api_key,)
        )
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "Invalid API key")

    return {
        "balance_sats": row[0],
        "free_calls_remaining": row[1],
        "total_calls": row[2],
        "total_spent_sats": row[3]
    }



# Verify / Debit Endpoint (Called by main app on Render)
# =========================

@app.post("/verify", tags=["accounts"])
@limiter.limit("30/minute")
async def verify_account(req: VerifyRequest, request: Request):
    """Atomic debit before tool execution. Called by the main Render app."""
    now = int(time.time())

    with get_db_conn() as conn:
        c = conn.cursor()

        # 1. Try free call first (atomic)
        c.execute(
            """UPDATE accounts 
               SET free_calls_remaining = free_calls_remaining - 1,
                   last_used = ?,
                   total_calls = total_calls + 1
               WHERE api_key = ? AND free_calls_remaining > 0""",
            (now, req.api_key)
        )
        if c.rowcount > 0:
            # Free call was used
            c.execute("SELECT free_calls_remaining, balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
            free_rem, bal = c.fetchone() or (0, 0)
            return {
                "allowed": True,
                "used_free_call": True,
                "free_remaining": free_rem,
                "balance_sats": bal
            }

        # 2. No free calls left → deduct from paid balance (atomic)
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
            # Insufficient balance
            c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
            row = c.fetchone()
            current_balance = row[0] if row else 0

            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Insufficient balance",
                    "required_sats": req.price_sats,
                    "current_balance": current_balance,
                    "message": f"Need {req.price_sats} sats, you have {current_balance}. Top up at /topup",
                    "note": "Accounts with balance stay active for at least 2 years of inactivity."
                }
            )

        # Success — return new balance
        c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
        new_balance = c.fetchone()[0]

    return {
        "allowed": True,
        "used_free_call": False,
        "free_remaining": 0,
        "balance_sats": new_balance
    }


# =========================
# Lightning Utilities
# =========================

@app.post("/create-invoice", tags=["lightning"])
async def create_invoice(req: InvoiceRequest):
    try:
        data = safe_lncli([
            "addinvoice",
            "--amt", str(req.amount),
            "--memo", req.memo
        ])
        return {
            "invoice": data["payment_request"],
            "payment_hash": data.get("r_hash", "")
        }
    except Exception as e:
        logger.error(f"Create invoice failed: {e}")
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


@app.get("/check-payment/{payment_hash}", tags=["lightning"])
async def check_payment(payment_hash: str):
    if not payment_hash or len(payment_hash) < 40:
        raise HTTPException(400, "Invalid payment_hash")
    try:
        settled = check_payment_logic(payment_hash)
        return {"paid": settled, "state": "SETTLED" if settled else "NOT_SETTLED"}
    except Exception:
        return {"paid": False, "state": "ERROR"}


@app.post("/verify-preimage", tags=["lightning"])
async def verify_preimage(req: VerifyPreimageRequest):
    valid = verify_preimage_logic(req.payment_hash, req.preimage)
    return {"valid": valid}


# =========================
# Health
# =========================

@app.get("/health", tags=["meta"])
async def health():
    """Bridge health check — focused on infrastructure and payment backend."""
    return {
        "status": "ok",
        "service": "invinoveritas LND + Accounts + x402 Bridge",
        "description": "Backend payment and account management service",
        "lnd_connected": lnd_ready(),
        "x402_available": X402_AVAILABLE and bool(X402_PAY_TO),
        "x402_network": X402_NETWORK,
        "database": "healthy",   # You can add a quick DB ping if you want
        "supported_payments": [
            "Bearer Token (credits — recommended for agents)",
            "x402 USDC (bulk top-ups, min $15)",
            "L402 Lightning (pay-per-call)"
        ],
        "account_policy": "Accounts with balance or free calls remain active for at least 2 years of inactivity.",
        "version": "0.5.0",
        "recommended": "Use Bearer Token for daily usage. Top up via x402 or Lightning when needed.",
        "timestamp": int(time.time())
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
