from fastapi import FastAPI, HTTPException, Request
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
from x402 import x402ResourceServer, ResourceConfig
from x402.http import HTTPFacilitatorClient

load_dotenv()

app = FastAPI(title="invinoveritas LND + Accounts Bridge")

DB_PATH = "invinoveritas_accounts.db"

# ========================= X402 CONFIG =========================
X402_CONFIG = {
    "pay_to": os.getenv("X402_PAY_TO"),           # ← Set in .env
    "network": "base-sepolia",                    # Change to "base" for mainnet
    "currency": "USDC",
    "register_price": "0.50",                     # $0.50 USDC for account creation
    "topup_price_multiplier": 1.0,                # Can adjust later
    "description": "invinoveritas Account / Topup",
}

# =========================
# Models
# =========================
class InvoiceRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount in satoshis")
    memo: str = Field("invinoveritas", max_length=100)

class VerifyPreimageRequest(BaseModel):
    payment_hash: str
    preimage: str

# Account system models
class RegisterRequest(BaseModel):
    label: Optional[str] = Field(None, max_length=100)

class TopupRequest(BaseModel):
    api_key: str
    amount_sats: int = Field(..., gt=0)

class SettleTopupRequest(BaseModel):
    api_key: str
    payment_hash: str
    preimage: str

class BalanceRequest(BaseModel):
    api_key: str

class VerifyRequest(BaseModel):
    api_key: str
    tool: str = Field(..., pattern="^(reason|decide)$")
    price_sats: int = Field(..., gt=0)


# =========================
# DB Helpers
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        api_key TEXT PRIMARY KEY,
        balance_sats INTEGER DEFAULT 0,
        free_calls_remaining INTEGER DEFAULT 5,   -- NEW: 5 free calls
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
    conn.commit()
    conn.close()


def get_db():
    return sqlite3.connect(DB_PATH)


def lnd_ready():
    try:
        info = run_lncli(["getinfo"])
        return info.get("synced_to_chain") and info.get("synced_to_graph")
    except:
        return False


# =========================
# LND Helper
# =========================
def run_lncli(args: list, timeout: int = 12) -> Dict[str, Any]:
    try:
        result = subprocess.run(["lncli"] + args, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            raise Exception(f"lncli failed: {error}")
        return json.loads(result.stdout)
    except Exception as e:
        raise Exception(f"lncli error: {str(e)}")


def safe_lncli(args):
    """Run lncli only if LND is ready"""
    if not lnd_ready():
        raise HTTPException(503, "Lightning node syncing. Please try again shortly.")
    return run_lncli(args)


# =========================
# Lightning Payment Helpers
# =========================
def verify_preimage_logic(payment_hash: str, preimage: str) -> bool:
    try:
        ph = payment_hash.strip().lower()
        pi = preimage.strip().lower()
        computed_hash = hashlib.sha256(bytes.fromhex(pi)).hexdigest()
        return computed_hash == ph
    except:
        return False


def check_payment_logic(payment_hash: str) -> bool:
    """Check if payment is settled"""
    try:
        data = run_lncli(["lookupinvoice", payment_hash], timeout=10)
        return data.get("settled", False)
    except:
        return False



# =========================
# Business Logic Helpers
# =========================
async def create_account(api_key: str, label: Optional[str] = None):
    now = int(time.time())
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""INSERT INTO accounts
                     (api_key, balance_sats, free_calls_remaining, created_at, last_used, label)
                     VALUES (?, 0, 5, ?, ?, ?)""",
                  (api_key, now, now, label))
        conn.commit()
    finally:
        conn.close()


# =========================
# Accounts Endpoints with x402 support
# =========================
@app.post("/register")
async def register(req: RegisterRequest, request: Request):
    # Try x402 first if no Lightning preference
    if not request.headers.get("Authorization", "").startswith("L402"):
        return await require_payment(
            price=X402_CONFIG["register_price"],
            pay_to=X402_CONFIG["pay_to"],
            network=X402_CONFIG["network"],
            currency=X402_CONFIG["currency"],
            description="invinoveritas Account Creation ($0.50 USDC)",
            metadata={"action": "register", "label": req.label}
        )(request, lambda r: register_logic(req))

    # Lightning flow (original)
    try:
        data = safe_lncli([
            "addinvoice",
            "--amt", "1000",
            "--memo", "invinoveritas account creation"
        ])
        return {
            "invoice": data["payment_request"],
            "payment_hash": data.get("r_hash"),
            "amount_sats": 1000,
            "message": "Pay this 1000 sat invoice to create your API key",
            "welcome_bonus": {"free_calls": 5},
            "next_step": "After paying, call POST /register/confirm"
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


async def register_logic(req: RegisterRequest):
    """Called after successful x402 payment"""
    api_key = f"ivv_{secrets.token_urlsafe(24)}"
    await create_account(api_key, req.label)
    return {
        "api_key": api_key,
        "message": "Account created successfully via x402!",
        "welcome_bonus": "You now have 5 free tool calls.",
        "free_calls_remaining": 5,
        "payment_method": "x402 (USDC)"
    }


@app.post("/register/confirm")
async def confirm_register(req: SettleTopupRequest):
    if not verify_preimage_logic(req.payment_hash, req.preimage):
        raise HTTPException(403, "Invalid preimage")

    if not check_payment_logic(req.payment_hash):
        raise HTTPException(402, "Payment not yet settled")

    api_key = f"ivv_{secrets.token_urlsafe(24)}"
    now = int(time.time())

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""INSERT INTO accounts 
                     (api_key, balance_sats, free_calls_remaining, created_at, last_used, label)
                     VALUES (?, 0, 5, ?, ?, ?)""",
                  (api_key, now, now, req.label))
        conn.commit()
    finally:
        conn.close()

    return {
        "api_key": api_key,
        "message": "Account created successfully!",
        "welcome_bonus": "You now have 5 free tool calls as a welcome bonus.",
        "free_calls_remaining": 5,
        "next_steps": "Use your api_key with Authorization: Bearer <api_key> on /reason, /decision, or the MCP endpoint."
    }

@app.post("/topup", tags=["credit"])
async def topup(req: TopupRequest, request: Request):
    # x402 fallback
    if not request.headers.get("Authorization", "").startswith("L402"):
        # For simplicity we charge fixed $1 USDC per topup (you can improve later)
        return await require_payment(
            price="1.00",
            pay_to=X402_CONFIG["pay_to"],
            network=X402_CONFIG["network"],
            currency=X402_CONFIG["currency"],
            description=f"invinoveritas Topup for {req.api_key[:8]}...",
            metadata={"action": "topup", "api_key": req.api_key, "amount_sats": req.amount_sats}
        )(request, lambda r: topup_logic(req))
    if not lnd_ready():
        raise HTTPException(503, "Lightning node syncing. Please try again shortly.")

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT 1 FROM accounts WHERE api_key = ?", (req.api_key,))
        if not c.fetchone():
            raise HTTPException(404, "Invalid API key")

        data = safe_lncli([
            "addinvoice",
            "--amt", str(req.amount_sats),
            "--memo", f"topup-{req.api_key[:8]}"
        ])
        invoice = data["payment_request"]
        payment_hash = data.get("r_hash", "")

        now = int(time.time())
        c.execute("""INSERT INTO pending_topups 
                     (payment_hash, api_key, amount_sats, created_at) 
                     VALUES (?, ?, ?, ?)""",
                  (payment_hash, req.api_key, req.amount_sats, now))
        conn.commit()
    finally:
        conn.close()

    return {
        "invoice": invoice,
        "payment_hash": payment_hash,
        "amount_sats": req.amount_sats,
        "message": "Pay this invoice to top up your account"
    }
async def topup_logic(req: TopupRequest):
    """Called after successful x402 topup"""
    # For now we credit a fixed amount. You can make it dynamic later.
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""UPDATE accounts 
                     SET balance_sats = balance_sats + ?,
                         last_used = ?
                     WHERE api_key = ?""",
                  (req.amount_sats, int(time.time()), req.api_key))
        conn.commit()
    finally:
        conn.close()
    return {"success": True, "credited_sats": req.amount_sats, "payment_method": "x402"}

@app.post("/settle-topup", tags=["credit"])
async def settle_topup(req: SettleTopupRequest):
    if not lnd_ready():
        raise HTTPException(503, "Lightning node syncing. Please try again shortly.")

    if not verify_preimage_logic(req.payment_hash, req.preimage):
        raise HTTPException(403, "Invalid preimage")

    if not check_payment_logic(req.payment_hash):
        raise HTTPException(402, "Payment not yet settled")

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT api_key, amount_sats FROM pending_topups WHERE payment_hash = ?", 
                  (req.payment_hash,))
        row = c.fetchone()
        if not row or row[0] != req.api_key:
            raise HTTPException(404, "No pending top-up found for this payment")

        amount = row[1]

        c.execute("""UPDATE accounts 
                     SET balance_sats = balance_sats + ?,
                         last_used = ?
                     WHERE api_key = ?""",
                  (amount, int(time.time()), req.api_key))

        c.execute("DELETE FROM pending_topups WHERE payment_hash = ?", (req.payment_hash,))
        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "credited_sats": amount,
        "message": "Account topped up successfully!"
    }


@app.get("/balance", tags=["credit"])
async def get_balance(api_key: str):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("""SELECT balance_sats, free_calls_remaining, total_calls, total_spent_sats 
                     FROM accounts WHERE api_key = ?""", (api_key,))
        row = c.fetchone()
        if not row:
            raise HTTPException(404, "Invalid API key")
    finally:
        conn.close()

    return {
        "balance_sats": row[0],
        "free_calls_remaining": row[1],
        "total_calls": row[2],
        "total_spent_sats": row[3]
    }


@app.post("/verify", tags=["credit"])
async def verify_account(req: VerifyRequest):
    conn = get_db()
    try:
        c = conn.cursor()
        now = int(time.time())

        c.execute("""SELECT balance_sats, free_calls_remaining 
                     FROM accounts WHERE api_key = ?""", (req.api_key,))
        row = c.fetchone()
        if not row:
            raise HTTPException(401, "Invalid API key")

        balance = row[0]
        free_calls = row[1]

        # Use free call first
        if free_calls > 0:
            c.execute("""UPDATE accounts 
                         SET free_calls_remaining = free_calls_remaining - 1,
                             last_used = ?,
                             total_calls = total_calls + 1
                         WHERE api_key = ?""",
                      (now, req.api_key))
            conn.commit()
            return {
                "allowed": True,
                "used_free_call": True,
                "free_remaining": free_calls - 1,
                "new_balance": balance
            }

        # Charge balance
        if balance < req.price_sats:
            raise HTTPException(
                402, 
                f"Insufficient balance and no free calls left. Need {req.price_sats} sats."
            )

        c.execute("""UPDATE accounts 
                     SET balance_sats = balance_sats - ?,
                         last_used = ?,
                         total_calls = total_calls + 1,
                         total_spent_sats = total_spent_sats + ?
                     WHERE api_key = ?""",
                  (req.price_sats, now, req.price_sats, req.api_key))
        conn.commit()

    finally:
        conn.close()

    return {
        "allowed": True,
        "used_free_call": False,
        "free_remaining": 0,
        "new_balance": balance - req.price_sats
    }

# =========================
# Lightning Endpoints
# =========================
@app.post("/create-invoice")
async def create_invoice(req: InvoiceRequest):
    """Create a new Lightning invoice"""
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


@app.get("/check-payment/{payment_hash}")
async def check_payment(payment_hash: str):
    """Check if a payment has been settled"""
    if not payment_hash or len(payment_hash) != 64:
        raise HTTPException(400, "Invalid payment_hash format")

    for attempt in range(8):
        try:
            data = run_lncli(["lookupinvoice", payment_hash], timeout=10)
            if data.get("settled", False):
                return {"paid": True, "state": "SETTLED"}

            # Fallback check
            list_data = run_lncli(["listinvoices", "--max_invoices", "100"], timeout=10)
            for inv in list_data.get("invoices", []):
                if inv.get("r_hash") == payment_hash:
                    settled = inv.get("settled", False)
                    return {"paid": settled, "state": inv.get("state", "UNKNOWN")}
        except:
            pass

        if attempt < 7:
            time.sleep(1.8)

    return {"paid": False, "state": "NOT_SETTLED_YET"}


@app.post("/verify-preimage")
async def verify_preimage(req: VerifyPreimageRequest):
    """Verify preimage matches payment_hash"""
    if not req.payment_hash or not req.preimage:
        raise HTTPException(400, "Missing payment_hash or preimage")

    valid = verify_preimage_logic(req.payment_hash, req.preimage)
    return {"valid": valid}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "lnd-bridge + accounts + x402",
        "supported_payments": ["Lightning", "x402 (USDC)"],
        "lnd_connected": lnd_ready()
    }


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8081)
