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

FREE_CALLS_ON_REGISTER = int(os.getenv("FREE_CALLS_ON_REGISTER", "5"))
LIGHTNING_REGISTER_SATS = int(os.getenv("LIGHTNING_REGISTER_SATS", "1000"))

# =========================
# Database Initialization + Cleanup
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
   
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
    
    # Performance indexes
    c.execute("CREATE INDEX IF NOT EXISTS idx_pending_api ON pending_topups(api_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_accounts_last ON accounts(last_used)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_used_hashes ON used_payment_hashes(used_at)")
    
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


@contextmanager
def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


async def cleanup_old_data():
    while True:
        try:
            now = int(time.time())
            with get_db_conn() as conn:
                c = conn.cursor()
                c.execute("DELETE FROM pending_topups WHERE created_at < ?", (now - 86400,))
                c.execute("DELETE FROM used_payment_hashes WHERE used_at < ?", (now - 30 * 86400,))
                conn.commit()
            logger.info("🧹 Cleanup completed")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        await asyncio.sleep(6 * 3600)


# =========================
# Startup
# =========================
@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(cleanup_old_data())
    logger.info("🚀 invinoveritas Lightning + Accounts Bridge started (Lightning only)")


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

class RegisterConfirmRequest(BaseModel):
    payment_hash: str
    preimage: str
    label: Optional[str] = None

class TopupRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    amount_sats: int = Field(..., gt=0)

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
    try:
        data = safe_lncli(["getinfo"])
        return bool(data and data.get("identity_pubkey"))
    except:
        return False


def run_lncli(args: list, timeout: int = 15) -> Dict[str, Any]:
    result = subprocess.run(
        ["lncli"] + args, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise Exception(f"lncli error: {error}")
    return json.loads(result.stdout)


def safe_lncli(args: list, timeout: int = 12):
    try:
        result = subprocess.run(
            ["lncli"] + args, capture_output=True, text=True, timeout=timeout, check=False
        )
        if result.returncode != 0:
            return None
        stdout = result.stdout.strip()
        return json.loads(stdout) if stdout else None
    except:
        return None


# =========================
# Payment Helpers
# =========================
def normalize_payment_hash(ph: str) -> str:
    ph = ph.strip().lower()
    if len(ph) == 64 and all(c in "0123456789abcdef" for c in ph):
        return ph
    try:
        decoded = base64.b64decode(ph + "=="[:2])
        return decoded.hex().lower()
    except:
        return ph


def verify_preimage_logic(payment_hash: str, preimage: str) -> bool:
    try:
        ph = normalize_payment_hash(payment_hash)
        pi = preimage.strip()
        if len(pi) == 64 and all(c in "0123456789abcdef" for c in pi):
            pi_bytes = bytes.fromhex(pi)
        else:
            pi_bytes = base64.b64decode(pi + "=="[:2])
        return hashlib.sha256(pi_bytes).hexdigest() == ph
    except:
        return False


def check_payment_logic(payment_hash: str) -> bool:
    try:
        ph = normalize_payment_hash(payment_hash)
        data = run_lncli(["lookupinvoice", ph])
        return bool(data.get("settled"))
    except:
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
# Registration
# =========================
@app.post("/register", tags=["accounts"])
@limiter.limit("10/minute")
async def register(req: RegisterRequest, request: Request):
    api_key = generate_api_key()
    
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
            "message": f"Pay this Lightning invoice to create your account + receive {FREE_CALLS_ON_REGISTER} complementary calls.",
            "free_calls_on_creation": FREE_CALLS_ON_REGISTER,
            "next_step": "After paying, POST to /register/confirm with payment_hash and preimage.",
            "important_note": "Accounts stay active for at least 2 years of inactivity."
        }
    except Exception as e:
        logger.error(f"Invoice creation failed: {e}")
        raise HTTPException(500, "Failed to create Lightning invoice")


@app.post("/register/confirm", tags=["accounts"])
async def confirm_register(req: RegisterConfirmRequest):
    if not verify_preimage_logic(req.payment_hash, req.preimage):
        raise HTTPException(403, "Invalid preimage")
    if not check_payment_logic(req.payment_hash):
        raise HTTPException(402, "Payment not settled yet")
    if is_hash_used(req.payment_hash):
        raise HTTPException(403, "Payment already used")

    api_key = generate_api_key()
    create_account_db(api_key, req.label)
    mark_hash_used(req.payment_hash)

    return {
        "status": "success",
        "api_key": api_key,
        "free_calls_remaining": FREE_CALLS_ON_REGISTER,
        "message": "Account created successfully!",
        "next_steps": "Use Authorization: Bearer <api_key>"
    }


# =========================
# Top-up
# =========================
@app.post("/topup", tags=["accounts"])
@limiter.limit("10/minute")
async def topup(req: TopupRequest, request: Request):
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
        payment_hash = data.get("r_hash", "")
        
        with get_db_conn() as conn:
            c = conn.cursor()
            c.execute(
                """INSERT INTO pending_topups 
                   (payment_hash, api_key, amount_sats, created_at)
                   VALUES (?, ?, ?, ?)""",
                (normalize_payment_hash(payment_hash), req.api_key, req.amount_sats, int(time.time()))
            )
        
        return {
            "invoice": data["payment_request"],
            "payment_hash": payment_hash,
            "amount_sats": req.amount_sats,
            "message": "Pay this Lightning invoice to top up your account",
            "next_step": "POST /settle-topup"
        }
    except Exception as e:
        logger.error(f"Topup failed: {e}")
        raise HTTPException(500, "Failed to create Lightning invoice")


@app.post("/settle-topup", tags=["accounts"])
async def settle_topup(req: SettleTopupRequest):
    if not verify_preimage_logic(req.payment_hash, req.preimage):
        raise HTTPException(403, "Invalid preimage")
    if not check_payment_logic(req.payment_hash):
        raise HTTPException(402, "Payment not settled")
    if is_hash_used(req.payment_hash):
        raise HTTPException(403, "Payment already used")

    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT amount_sats FROM pending_topups WHERE payment_hash = ?", 
                  (normalize_payment_hash(req.payment_hash),))
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "No pending topup found")
        
        amount = row[0]
        c.execute("""UPDATE accounts 
                     SET balance_sats = balance_sats + ?,
                         last_used = ?
                     WHERE api_key = ?""",
                  (amount, int(time.time()), req.api_key))
        
        c.execute("DELETE FROM pending_topups WHERE payment_hash = ?", 
                  (normalize_payment_hash(req.payment_hash),))
        mark_hash_used(req.payment_hash)
        conn.commit()

    return {"success": True, "credited_sats": amount, "message": "Top-up completed"}


# =========================
# Balance & Verify
# =========================
@app.get("/balance", tags=["accounts"])
async def get_balance(api_key: str):
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT balance_sats, free_calls_remaining, total_calls, total_spent_sats
               FROM accounts WHERE api_key = ?""", (api_key,)
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


@app.post("/verify", tags=["accounts"])
@limiter.limit("30/minute")
async def verify_account(req: VerifyRequest, request: Request):   # ← Add , request: Request here
    """Called by your main app to debit before tool execution. Atomic updates."""
    now = int(time.time())
    with get_db_conn() as conn:
        c = conn.cursor()
        
        # Free call
        c.execute(
            """UPDATE accounts
               SET free_calls_remaining = free_calls_remaining - 1,
                   last_used = ?,
                   total_calls = total_calls + 1
               WHERE api_key = ? AND free_calls_remaining > 0""",
            (now, req.api_key)
        )
        if c.rowcount > 0:
            c.execute("SELECT free_calls_remaining, balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
            free_rem, bal = c.fetchone() or (0, 0)
            return {"allowed": True, "used_free_call": True, "free_remaining": free_rem, "balance_sats": bal}
        
        # Paid balance
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
            c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
            current = c.fetchone()[0] if c.fetchone() else 0
            raise HTTPException(402, f"Insufficient balance. Need {req.price_sats} sats (you have {current})")
        
        c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
        new_balance = c.fetchone()[0]

    return {"allowed": True, "used_free_call": False, "balance_sats": new_balance}


# =========================
# Lightning Utilities
# =========================
@app.post("/create-invoice", tags=["lightning"])
async def create_invoice(req: InvoiceRequest):
    try:
        data = safe_lncli(["addinvoice", "--amt", str(req.amount), "--memo", req.memo])
        return {"invoice": data["payment_request"], "payment_hash": data.get("r_hash", "")}
    except Exception as e:
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


@app.get("/check-payment/{payment_hash}", tags=["lightning"])
async def check_payment(payment_hash: str):
    settled = check_payment_logic(payment_hash)
    return {"paid": settled, "state": "SETTLED" if settled else "NOT_SETTLED"}


@app.post("/verify-preimage", tags=["lightning"])
async def verify_preimage(req: VerifyPreimageRequest):
    return {"valid": verify_preimage_logic(req.payment_hash, req.preimage)}


# =========================
# Health
# =========================
@app.get("/health", tags=["meta"])
async def health():
    return {
        "status": "ok",
        "service": "invinoveritas Lightning Bridge",
        "lnd_connected": lnd_ready(),
        "supported_payments": ["Lightning (L402)", "Bearer Token (Credits)"],
        "version": "0.5.0-lightning-only",
        "timestamp": int(time.time())
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
