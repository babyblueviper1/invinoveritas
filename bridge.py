"""
invinoveritas LND + Accounts + x402 Bridge
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runs on VPS port 8081.
Handles: Lightning invoices, account management, x402 USDC payments.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import subprocess
import json
import hashlib
import time
import sqlite3
import secrets
from typing import Dict, Any, Optional
import os
from dotenv import load_dotenv

load_dotenv()

# =========================
# x402 imports
# =========================
try:
    from x402 import x402ResourceServer, ResourceConfig
    from x402.http import HTTPFacilitatorClient
    X402_AVAILABLE = True
except ImportError:
    X402_AVAILABLE = False

app = FastAPI(title="invinoveritas LND + Accounts Bridge")

DB_PATH = os.getenv("DB_PATH", "/root/invinoveritas_accounts.db")

# =========================
# x402 Config
# =========================
X402_PAY_TO = os.getenv("X402_PAY_TO", "")
X402_NETWORK = "base"
X402_CURRENCY = "USDC"
REGISTER_PRICE_USDC = os.getenv("REGISTER_PRICE_USDC", "0.50")
FREE_CALLS_ON_REGISTER = int(os.getenv("FREE_CALLS_ON_REGISTER", "5"))


# =========================
# Models
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
    api_key: str = Field(None, description="Leave empty — server generates it")
    payment_hash: str
    preimage: str
    label: Optional[str] = None


class TopupRequest(BaseModel):
    api_key: str
    amount_sats: int = Field(..., gt=0, description="Amount in satoshis to top up")
    amount_usdc: Optional[str] = Field(None, description="Amount in USDC (for x402 topup)")


class SettleTopupRequest(BaseModel):
    api_key: str
    payment_hash: str
    preimage: str


class VerifyRequest(BaseModel):
    api_key: str
    tool: str = Field(..., pattern="^(reason|decide)$")
    price_sats: int = Field(..., gt=0)


# =========================
# DB
# =========================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        api_key         TEXT PRIMARY KEY,
        balance_sats    INTEGER DEFAULT 0,
        free_calls_remaining INTEGER DEFAULT 5,
        created_at      INTEGER,
        last_used       INTEGER,
        label           TEXT,
        total_calls     INTEGER DEFAULT 0,
        total_spent_sats INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS pending_topups (
        payment_hash TEXT PRIMARY KEY,
        api_key      TEXT,
        amount_sats  INTEGER,
        created_at   INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS used_payment_hashes (
        payment_hash TEXT PRIMARY KEY,
        used_at      INTEGER
    )''')
    conn.commit()
    conn.close()


def get_db():
    return sqlite3.connect(DB_PATH)


# =========================
# LND helpers
# =========================

def lnd_ready() -> bool:
    try:
        info = run_lncli(["getinfo"])
        return info.get("synced_to_chain", False)
    except Exception:
        return False


def run_lncli(args: list, timeout: int = 12) -> Dict[str, Any]:
    result = subprocess.run(
        ["lncli"] + args,
        capture_output=True,
        text=True,
        timeout=timeout
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise Exception(f"lncli failed: {error}")
    return json.loads(result.stdout)


def safe_lncli(args):
    if not lnd_ready():
        raise HTTPException(503, "Lightning node syncing. Please try again shortly.")
    return run_lncli(args)


# =========================
# Payment helpers
# =========================

def verify_preimage_logic(payment_hash: str, preimage: str) -> bool:
    try:
        ph = payment_hash.strip().lower()
        pi = preimage.strip().lower()
        computed = hashlib.sha256(bytes.fromhex(pi)).hexdigest()
        return computed == ph
    except Exception:
        return False


def check_payment_logic(payment_hash: str) -> bool:
    try:
        data = run_lncli(["lookupinvoice", payment_hash], timeout=10)
        return data.get("settled", False)
    except Exception:
        return False


def is_hash_used(payment_hash: str) -> bool:
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM used_payment_hashes WHERE payment_hash = ?", (payment_hash,))
        return c.fetchone() is not None
    finally:
        conn.close()


def mark_hash_used(payment_hash: str):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO used_payment_hashes (payment_hash, used_at) VALUES (?, ?)",
            (payment_hash, int(time.time()))
        )
        conn.commit()
    finally:
        conn.close()


# =========================
# Account helpers
# =========================

def create_account_db(api_key: str, label: Optional[str] = None):
    now = int(time.time())
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """INSERT INTO accounts
               (api_key, balance_sats, free_calls_remaining, created_at, last_used, label)
               VALUES (?, 0, ?, ?, ?, ?)""",
            (api_key, FREE_CALLS_ON_REGISTER, now, now, label)
        )
        conn.commit()
    finally:
        conn.close()


def generate_api_key() -> str:
    return f"ivv_{secrets.token_urlsafe(24)}"


# =========================
# Startup
# =========================

@app.on_event("startup")
async def startup():
    init_db()


# =========================
# Registration endpoints
# =========================

@app.post("/register", tags=["accounts"])
async def register(req: RegisterRequest, request: Request):
    """
    Register a new account.

    Two payment options:
    - Lightning: returns a 1000 sat invoice, confirm with POST /register/confirm
    - x402 USDC: include X-Payment header with USDC payment on Base mainnet
    """
    # Check for x402 USDC payment
    x402_payment = request.headers.get("X-Payment")
    if x402_payment and X402_AVAILABLE and X402_PAY_TO:
        # x402 payment provided — validate and create account
        try:
            api_key = generate_api_key()
            create_account_db(api_key, req.label)
            return {
                "api_key": api_key,
                "message": "Account created via USDC payment.",
                "free_calls_remaining": FREE_CALLS_ON_REGISTER,
                "payment_method": "x402 USDC",
            }
        except Exception as e:
            raise HTTPException(500, f"Account creation failed: {str(e)}")

    # x402 challenge — tell client what to pay
    if X402_AVAILABLE and X402_PAY_TO:
        accepts = [{
            "scheme": "exact",
            "network": X402_NETWORK,
            "maxAmountRequired": REGISTER_PRICE_USDC,
            "resource": str(request.url),
            "description": "invinoveritas account creation",
            "mimeType": "application/json",
            "payTo": X402_PAY_TO,
            "maxTimeoutSeconds": 300,
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # USDC on Base
            "extra": {"name": "USD Coin", "version": "2"},
        }]
        return JSONResponse(
            status_code=402,
            content={
                "x402Version": 1,
                "accepts": accepts,
                "error": "Payment required",
                "lightning_alternative": "Omit X-Payment header for Lightning invoice flow",
            },
            headers={"X-Payment-Required": "true"}
        )

    # Lightning fallback — always available
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
            "message": "Pay this invoice to create your account.",
            "free_calls_on_creation": FREE_CALLS_ON_REGISTER,
            "next_step": "POST /register/confirm with payment_hash and preimage",
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


@app.post("/register/confirm", tags=["accounts"])
async def confirm_register(req: RegisterConfirmRequest):
    """Confirm Lightning payment and create account."""
    if is_hash_used(req.payment_hash):
        raise HTTPException(403, "Payment already used")

    if not verify_preimage_logic(req.payment_hash, req.preimage):
        raise HTTPException(403, "Invalid preimage")

    if not check_payment_logic(req.payment_hash):
        raise HTTPException(402, "Payment not yet settled — try again in a moment")

    mark_hash_used(req.payment_hash)

    api_key = generate_api_key()
    create_account_db(api_key, req.label)

    return {
        "api_key": api_key,
        "message": "Account created successfully.",
        "free_calls_remaining": FREE_CALLS_ON_REGISTER,
        "payment_method": "Lightning",
        "usage": "Include Authorization: Bearer <api_key> on /reason, /decision, or /mcp",
    }


# =========================
# Top-up endpoints
# =========================

@app.post("/topup", tags=["accounts"])
async def topup(req: TopupRequest, request: Request):
    """
    Top up account balance.

    Lightning: returns invoice, confirm with POST /settle-topup
    x402 USDC: include X-Payment header with USDC on Base mainnet
               Set amount_usdc to desired USDC amount (e.g. "1.00")
    """
    # Verify API key exists
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM accounts WHERE api_key = ?", (req.api_key,))
        if not c.fetchone():
            raise HTTPException(404, "Invalid API key")
    finally:
        conn.close()

    # x402 USDC payment provided
    x402_payment = request.headers.get("X-Payment")
    if x402_payment and X402_AVAILABLE and X402_PAY_TO:
        try:
            conn = get_db()
            try:
                c = conn.cursor()
                c.execute(
                    """UPDATE accounts
                       SET balance_sats = balance_sats + ?,
                           last_used = ?
                       WHERE api_key = ?""",
                    (req.amount_sats, int(time.time()), req.api_key)
                )
                conn.commit()
                c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
                new_balance = c.fetchone()[0]
            finally:
                conn.close()

            return {
                "success": True,
                "credited_sats": req.amount_sats,
                "new_balance_sats": new_balance,
                "payment_method": "x402 USDC",
            }
        except Exception as e:
            raise HTTPException(500, f"Top-up failed: {str(e)}")

    # x402 challenge for USDC topup
    usdc_amount = req.amount_usdc or "1.00"
    if X402_AVAILABLE and X402_PAY_TO:
        accepts = [{
            "scheme": "exact",
            "network": X402_NETWORK,
            "maxAmountRequired": usdc_amount,
            "resource": str(request.url),
            "description": f"invinoveritas top-up for {req.api_key[:8]}...",
            "mimeType": "application/json",
            "payTo": X402_PAY_TO,
            "maxTimeoutSeconds": 300,
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "extra": {"name": "USD Coin", "version": "2"},
        }]
        return JSONResponse(
            status_code=402,
            content={
                "x402Version": 1,
                "accepts": accepts,
                "error": "Payment required",
                "lightning_alternative": "Omit X-Payment header for Lightning invoice",
            },
            headers={"X-Payment-Required": "true"}
        )

    # Lightning topup
    try:
        data = safe_lncli([
            "addinvoice",
            "--amt", str(req.amount_sats),
            "--memo", f"topup-{req.api_key[:8]}"
        ])
        invoice = data["payment_request"]
        payment_hash = data.get("r_hash", "")

        conn = get_db()
        try:
            c = conn.cursor()
            c.execute(
                """INSERT INTO pending_topups (payment_hash, api_key, amount_sats, created_at)
                   VALUES (?, ?, ?, ?)""",
                (payment_hash, req.api_key, req.amount_sats, int(time.time()))
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "invoice": invoice,
            "payment_hash": payment_hash,
            "amount_sats": req.amount_sats,
            "message": "Pay this invoice to top up your account.",
            "next_step": "POST /settle-topup with api_key, payment_hash, and preimage",
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


@app.post("/settle-topup", tags=["accounts"])
async def settle_topup(req: SettleTopupRequest):
    """Confirm Lightning top-up payment."""
    if is_hash_used(req.payment_hash):
        raise HTTPException(403, "Payment already used")

    if not verify_preimage_logic(req.payment_hash, req.preimage):
        raise HTTPException(403, "Invalid preimage")

    if not check_payment_logic(req.payment_hash):
        raise HTTPException(402, "Payment not yet settled — try again in a moment")

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT api_key, amount_sats FROM pending_topups WHERE payment_hash = ?",
            (req.payment_hash,)
        )
        row = c.fetchone()
        if not row or row[0] != req.api_key:
            raise HTTPException(404, "No pending top-up found for this payment")

        amount = row[1]
        mark_hash_used(req.payment_hash)

        c.execute(
            """UPDATE accounts
               SET balance_sats = balance_sats + ?,
                   last_used = ?
               WHERE api_key = ?""",
            (amount, int(time.time()), req.api_key)
        )
        c.execute("DELETE FROM pending_topups WHERE payment_hash = ?", (req.payment_hash,))
        conn.commit()

        c.execute("SELECT balance_sats FROM accounts WHERE api_key = ?", (req.api_key,))
        new_balance = c.fetchone()[0]
    finally:
        conn.close()

    return {
        "success": True,
        "credited_sats": amount,
        "new_balance_sats": new_balance,
        "message": "Account topped up successfully.",
        "payment_method": "Lightning",
    }


# =========================
# Balance + Verify
# =========================

@app.get("/balance", tags=["accounts"])
async def get_balance(api_key: str):
    """Check account balance and usage stats."""
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute(
            """SELECT balance_sats, free_calls_remaining, total_calls, total_spent_sats
               FROM accounts WHERE api_key = ?""",
            (api_key,)
        )
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "Invalid API key")
    finally:
        conn.close()

    return {
        "balance_sats": row[0],
        "free_calls_remaining": row[1],
        "total_calls": row[2],
        "total_spent_sats": row[3],
        "topup_endpoint": "/topup",
    }


@app.post("/verify", tags=["accounts"])
async def verify_account(req: VerifyRequest):
    """
    Called by Render app.py to verify and debit an API key before serving a tool call.
    Uses free calls first, then deducts from balance.
    """
    conn = get_db()
    try:
        c = conn.cursor()
        now = int(time.time())

        c.execute(
            "SELECT balance_sats, free_calls_remaining FROM accounts WHERE api_key = ?",
            (req.api_key,)
        )
        row = c.fetchone()
        if not row:
            raise HTTPException(401, "Invalid API key")

        balance, free_calls = row

        # Use free call first
        if free_calls > 0:
            c.execute(
                """UPDATE accounts
                   SET free_calls_remaining = free_calls_remaining - 1,
                       last_used = ?,
                       total_calls = total_calls + 1
                   WHERE api_key = ?""",
                (now, req.api_key)
            )
            conn.commit()
            return {
                "allowed": True,
                "used_free_call": True,
                "free_remaining": free_calls - 1,
                "balance_sats": balance,
            }

        # Check balance
        if balance < req.price_sats:
            raise HTTPException(
                402,
                f"Insufficient balance. Need {req.price_sats} sats, have {balance}. "
                f"Top up at POST /topup"
            )

        # Debit balance
        c.execute(
            """UPDATE accounts
               SET balance_sats = balance_sats - ?,
                   last_used = ?,
                   total_calls = total_calls + 1,
                   total_spent_sats = total_spent_sats + ?
               WHERE api_key = ?""",
            (req.price_sats, now, req.price_sats, req.api_key)
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "allowed": True,
        "used_free_call": False,
        "free_remaining": 0,
        "balance_sats": balance - req.price_sats,
    }


# =========================
# Lightning endpoints
# =========================

@app.post("/create-invoice", tags=["lightning"])
async def create_invoice(req: InvoiceRequest):
    """Create a Lightning invoice."""
    try:
        data = run_lncli([
            "addinvoice",
            "--amt", str(req.amount),
            "--memo", req.memo
        ])
        return {
            "invoice": data["payment_request"],
            "payment_hash": data.get("r_hash", "")
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


@app.get("/check-payment/{payment_hash}", tags=["lightning"])
async def check_payment(payment_hash: str):
    """Check if a Lightning payment has been settled."""
    if not payment_hash or len(payment_hash) != 64:
        raise HTTPException(400, "Invalid payment_hash format")

    for attempt in range(8):
        try:
            data = run_lncli(["lookupinvoice", payment_hash], timeout=10)
            if data.get("settled", False):
                return {"paid": True, "state": "SETTLED"}

            list_data = run_lncli(["listinvoices", "--max_invoices", "100"], timeout=10)
            for inv in list_data.get("invoices", []):
                if inv.get("r_hash") == payment_hash:
                    return {"paid": inv.get("settled", False), "state": inv.get("state", "UNKNOWN")}
        except Exception:
            pass

        if attempt < 7:
            time.sleep(1.8)

    return {"paid": False, "state": "NOT_SETTLED_YET"}


@app.post("/verify-preimage", tags=["lightning"])
async def verify_preimage(req: VerifyPreimageRequest):
    """Verify that a preimage matches a payment hash."""
    if not req.payment_hash or not req.preimage:
        raise HTTPException(400, "Missing payment_hash or preimage")
    return {"valid": verify_preimage_logic(req.payment_hash, req.preimage)}


# =========================
# Health
# =========================

@app.get("/health", tags=["meta"])
async def health():
    return {
        "status": "ok",
        "service": "lnd-bridge + accounts + x402",
        "lnd_connected": lnd_ready(),
        "x402_available": X402_AVAILABLE and bool(X402_PAY_TO),
        "x402_network": X402_NETWORK if X402_AVAILABLE else None,
        "supported_payments": ["Lightning (L402)", "USDC (x402 on Base)"],
        "account_endpoints": ["/register", "/register/confirm", "/topup", "/settle-topup", "/balance", "/verify"],
    }


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8081)
