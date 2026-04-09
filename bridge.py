import subprocess
import json
import hashlib
import time
import sqlite3
import secrets
import logging
import base64
import os
from typing import Dict, Any, Optional
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

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
# x402 Setup (simple header check for now)
# =========================
try:
    from x402 import x402ResourceServer  # Future full integration point
    X402_AVAILABLE = True
except ImportError:
    X402_AVAILABLE = False
    logger.warning("x402 library not found. Only basic header check enabled.")

app = FastAPI(title="invinoveritas LND + Accounts + x402 Bridge")

# CORS - restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to your frontend domains in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.getenv("DB_PATH", "/root/invinoveritas_accounts.db")

# =========================
# Configuration
# =========================
X402_PAY_TO = os.getenv("X402_PAY_TO", "").strip()
X402_NETWORK = os.getenv("X402_NETWORK", "base")
USDC_CONTRACT = os.getenv("USDC_CONTRACT", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
REGISTER_PRICE_USDC = os.getenv("REGISTER_PRICE_USDC", "0.50")
FREE_CALLS_ON_REGISTER = int(os.getenv("FREE_CALLS_ON_REGISTER", "5"))

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
    amount_usdc: Optional[str] = Field(None, description="USDC amount for x402 topup (e.g. '1.00')")

class SettleTopupRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    payment_hash: str
    preimage: str

class VerifyRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    tool: str = Field(..., pattern="^(reason|decide)$")
    price_sats: int = Field(..., gt=0)

# =========================
# Database
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
    logger.info("Database initialized")

@contextmanager
def get_db_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def cleanup_old_hashes():
    with get_db_conn() as conn:
        c = conn.cursor()
        thirty_days = int(time.time()) - 30 * 86400
        c.execute("DELETE FROM used_payment_hashes WHERE used_at < ?", (thirty_days,))
        if c.rowcount:
            logger.info(f"Cleaned {c.rowcount} old payment hashes")

# =========================
# LND Helpers
# =========================

def lnd_ready() -> bool:
    try:
        info = run_lncli(["getinfo"])
        return bool(info.get("synced_to_chain"))
    except Exception:
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

def safe_lncli(args):
    if not lnd_ready():
        raise HTTPException(503, "Lightning node is syncing. Please try again shortly.")
    return run_lncli(args)

# =========================
# Payment Helpers
# =========================

def normalize_payment_hash(ph: str) -> str:
    """Normalize LND payment hash (handles hex or base64)."""
    ph = ph.strip()
    if len(ph) == 64 and all(c in "0123456789abcdefABCDEF" for c in ph):
        return ph.lower()
    try:
        # Try base64 decode to hex
        decoded = base64.b64decode(ph + "=="[:2])  # safe padding
        return decoded.hex()
    except Exception:
        return ph.lower()

def verify_preimage_logic(payment_hash: str, preimage: str) -> bool:
    try:
        ph = normalize_payment_hash(payment_hash)
        pi = preimage.strip()
        # Convert preimage to bytes
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
    now = int(time.time())
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO accounts 
               (api_key, balance_sats, free_calls_remaining, created_at, last_used, label)
               VALUES (?, 0, ?, ?, ?, ?)""",
            (api_key, FREE_CALLS_ON_REGISTER, now, now, label)
        )

# =========================
# Startup
# =========================
@app.on_event("startup")
async def startup_event():
    init_db()
    cleanup_old_hashes()
    logger.info("invinoveritas LND + Accounts + x402 service started successfully")

# =========================
# Registration Endpoints
# =========================

@app.post("/register", tags=["accounts"])
@limiter.limit("10/minute")
async def register(req: RegisterRequest, request: Request):
    """Create new account via x402 USDC (preferred) or Lightning invoice."""
    x402_header = request.headers.get("X-Payment")

    if x402_header and X402_AVAILABLE and X402_PAY_TO:
        try:
            api_key = generate_api_key()
            create_account_db(api_key, req.label)
            logger.info(f"New account via x402: {api_key[:15]}...")
            return {
                "api_key": api_key,
                "message": "Account created via USDC (x402)",
                "free_calls_remaining": FREE_CALLS_ON_REGISTER,
                "payment_method": "x402 USDC"
            }
        except Exception as e:
            logger.error(f"Account creation failed: {e}")
            raise HTTPException(500, "Failed to create account")

    # x402 challenge response
    if X402_AVAILABLE and X402_PAY_TO:
        accepts = [{
            "scheme": "exact",
            "network": X402_NETWORK,
            "maxAmountRequired": REGISTER_PRICE_USDC,
            "resource": str(request.url),
            "description": "invinoveritas account registration",
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
                "lightning_alternative": "Omit X-Payment header for Lightning flow"
            },
            headers={"X-Payment-Required": "true"}
        )

    # Lightning fallback
    try:
        data = safe_lncli([
            "addinvoice",
            "--amt", "1000",
            "--memo", "invinoveritas account creation"
        ])
        return {
            "invoice": data["payment_request"],
            "payment_hash": data.get("r_hash", ""),
            "amount_sats": 1000,
            "message": "Pay this invoice to create account",
            "free_calls_on_creation": FREE_CALLS_ON_REGISTER,
            "next_step": "POST /register/confirm with payment_hash + preimage"
        }
    except Exception as e:
        logger.error(f"Invoice creation failed: {e}")
        raise HTTPException(500, f"Failed to create Lightning invoice: {str(e)}")


@app.post("/register/confirm", tags=["accounts"])
@limiter.limit("5/minute")
async def confirm_register(req: RegisterConfirmRequest):
    if is_hash_used(req.payment_hash):
        raise HTTPException(403, "This payment has already been used")

    if not verify_preimage_logic(req.payment_hash, req.preimage):
        raise HTTPException(403, "Invalid preimage")

    if not check_payment_logic(req.payment_hash):
        raise HTTPException(402, "Payment not settled yet. Try again shortly.")

    mark_hash_used(req.payment_hash)

    api_key = generate_api_key()
    create_account_db(api_key, req.label)

    logger.info(f"Account created via Lightning: {api_key[:15]}...")
    return {
        "api_key": api_key,
        "message": "Account created successfully",
        "free_calls_remaining": FREE_CALLS_ON_REGISTER,
        "payment_method": "Lightning"
    }

# =========================
# Top-up Endpoints
# =========================

@app.post("/topup", tags=["accounts"])
@limiter.limit("10/minute")
async def topup(req: TopupRequest, request: Request):
    """Top up balance via Lightning or x402 USDC."""
    # Verify API key exists
    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM accounts WHERE api_key = ?", (req.api_key,))
        if not c.fetchone():
            raise HTTPException(404, "Invalid API key")

    x402_header = request.headers.get("X-Payment")
    if x402_header and X402_AVAILABLE and X402_PAY_TO:
        try:
            with get_db_conn() as conn:
                c = conn.cursor()
                c.execute(
                    """UPDATE accounts 
                       SET balance_sats = balance_sats + ?,
                           last_used = ?
                       WHERE api_key = ?""",
                    (req.amount_sats, int(time.time()), req.api_key)
                )
                c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
                new_balance = c.fetchone()[0]
            logger.info(f"Top-up via x402 for {req.api_key[:12]}... +{req.amount_sats} sats")
            return {
                "success": True,
                "credited_sats": req.amount_sats,
                "new_balance_sats": new_balance,
                "payment_method": "x402 USDC"
            }
        except Exception as e:
            logger.error(f"Top-up failed: {e}")
            raise HTTPException(500, "Top-up failed")

    # x402 challenge
    usdc_amount = req.amount_usdc or "1.00"
    if X402_AVAILABLE and X402_PAY_TO:
        accepts = [{
            "scheme": "exact",
            "network": X402_NETWORK,
            "maxAmountRequired": usdc_amount,
            "resource": str(request.url),
            "description": f"Top-up for {req.api_key[:12]}...",
            "payTo": X402_PAY_TO,
            "asset": USDC_CONTRACT
        }]
        return JSONResponse(
            status_code=402,
            content={
                "x402Version": 1,
                "accepts": accepts,
                "error": "Payment required",
                "lightning_alternative": "Omit X-Payment for Lightning invoice"
            },
            headers={"X-Payment-Required": "true"}
        )

    # Lightning top-up
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
            "message": "Pay this invoice to top up",
            "next_step": "POST /settle-topup"
        }
    except Exception as e:
        logger.error(f"Top-up invoice failed: {e}")
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


@app.post("/settle-topup", tags=["accounts"])
@limiter.limit("5/minute")
async def settle_topup(req: SettleTopupRequest):
    if is_hash_used(req.payment_hash):
        raise HTTPException(403, "Payment already used")

    if not verify_preimage_logic(req.payment_hash, req.preimage):
        raise HTTPException(403, "Invalid preimage")

    if not check_payment_logic(req.payment_hash):
        raise HTTPException(402, "Payment not settled yet")

    with get_db_conn() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT api_key, amount_sats FROM pending_topups WHERE payment_hash = ?",
            (normalize_payment_hash(req.payment_hash),)
        )
        row = c.fetchone()
        if not row or row[0] != req.api_key:
            raise HTTPException(404, "No matching pending top-up")

        amount = row[1]
        mark_hash_used(req.payment_hash)

        c.execute(
            """UPDATE accounts 
               SET balance_sats = balance_sats + ?,
                   last_used = ?
               WHERE api_key = ?""",
            (amount, int(time.time()), req.api_key)
        )
        c.execute("DELETE FROM pending_topups WHERE payment_hash = ?",
                  (normalize_payment_hash(req.payment_hash),))
        c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
        new_balance = c.fetchone()[0]

    logger.info(f"Top-up settled for {req.api_key[:12]}... +{amount} sats")
    return {
        "success": True,
        "credited_sats": amount,
        "new_balance_sats": new_balance,
        "payment_method": "Lightning"
    }

# =========================
# Balance & Verify
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


@app.post("/verify", tags=["accounts"])
@limiter.limit("30/minute")
async def verify_account(req: VerifyRequest):
    """Called by your main app to debit before tool execution. Atomic updates."""
    now = int(time.time())

    with get_db_conn() as conn:
        c = conn.cursor()

        # Try free call first (atomic)
        c.execute(
            """UPDATE accounts 
               SET free_calls_remaining = free_calls_remaining - 1,
                   last_used = ?,
                   total_calls = total_calls + 1
               WHERE api_key = ? AND free_calls_remaining > 0""",
            (now, req.api_key)
        )
        if c.rowcount > 0:
            # Free call used
            c.execute("SELECT free_calls_remaining, balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
            free_rem, bal = c.fetchone()
            return {
                "allowed": True,
                "used_free_call": True,
                "free_remaining": free_rem,
                "balance_sats": bal
            }

        # No free calls → deduct from balance (atomic)
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
            # Check current balance for error message
            c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
            row = c.fetchone()
            balance = row[0] if row else 0
            raise HTTPException(
                402,
                f"Insufficient balance. Need {req.price_sats} sats, have {balance}. Top up at /topup"
            )

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
# Health Check
# =========================

@app.get("/health", tags=["meta"])
async def health():
    return {
        "status": "ok",
        "service": "invinoveritas LND + Accounts + x402 Bridge",
        "lnd_connected": lnd_ready(),
        "x402_available": X402_AVAILABLE and bool(X402_PAY_TO),
        "x402_network": X402_NETWORK,
        "supported_payments": ["Lightning", "USDC via x402 (Base)"],
    }

# =========================
# Run
# =========================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
