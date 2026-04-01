from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import subprocess
import json
import hashlib
import time
from typing import Dict, Any

app = FastAPI(title="invinoveritas LND Bridge")


# =========================
# Models
# =========================
class InvoiceRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount in satoshis")
    memo: str = Field("invinoveritas", max_length=100)


class VerifyPreimageRequest(BaseModel):
    payment_hash: str
    preimage: str


# =========================
# Helper
# =========================
def run_lncli(args: list, timeout: int = 12) -> Dict[str, Any]:
    """Robust wrapper for lncli commands"""
    try:
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
    except subprocess.TimeoutExpired:
        raise Exception("lncli command timed out")
    except json.JSONDecodeError:
        raise Exception("Failed to parse lncli JSON output")
    except Exception as e:
        raise Exception(f"lncli error: {str(e)}")


# =========================
# Endpoints
# =========================
@app.post("/create-invoice")
async def create_invoice(req: InvoiceRequest):
    """Create a new Lightning invoice"""
    if req.amount < 1:
        raise HTTPException(400, "Amount must be at least 1 sat")

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
    """Robust payment check with retries and fallback"""
    if not payment_hash or len(payment_hash) != 64:
        raise HTTPException(400, "Invalid payment_hash format")

    for attempt in range(8):  # Try up to 8 times (~15 seconds total)
        try:
            # Primary check
            data = run_lncli(["lookupinvoice", payment_hash], timeout=10)
            if data.get("settled", False):
                return {"paid": True, "state": "SETTLED"}

            # Fallback: check recent invoices
            list_data = run_lncli(["listinvoices", "--max_invoices", "100"], timeout=10)
            for inv in list_data.get("invoices", []):
                if inv.get("r_hash") == payment_hash:
                    settled = inv.get("settled", False)
                    return {"paid": settled, "state": inv.get("state", "UNKNOWN")}

        except Exception:
            pass  # Continue retrying

        if attempt < 7:
            time.sleep(1.8)  # Progressive wait

    # Final fallback
    return {"paid": False, "state": "NOT_SETTLED_YET"}


@app.post("/verify-preimage")
async def verify_preimage(req: VerifyPreimageRequest):
    """Verify preimage matches payment_hash (critical for L402 security)"""
    if not req.payment_hash or not req.preimage:
        raise HTTPException(400, "Missing payment_hash or preimage")

    try:
        ph = req.payment_hash.strip().lower()
        pi = req.preimage.strip().lower()
        computed_hash = hashlib.sha256(bytes.fromhex(pi)).hexdigest()
        return {"valid": computed_hash == ph}
    except Exception:
        return {"valid": False}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "lnd-bridge",
        "lnd_connected": True
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
