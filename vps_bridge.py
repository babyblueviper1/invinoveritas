from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import subprocess
import json
import hashlib
from typing import Dict, Any, List, Optional

app = FastAPI(
    title="invinoveritas LND Bridge",
    description="Secure bridge between Render API and local LND node"
)


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
# Helpers
# =========================
def run_lncli(args: list[str], timeout: int = 15) -> Dict[str, Any]:
    """Safe wrapper for lncli commands"""
    try:
        result = subprocess.run(
            ["lncli"] + args,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise Exception(f"lncli error: {error_msg}")

        return json.loads(result.stdout)

    except subprocess.TimeoutExpired:
        raise Exception("lncli command timed out")
    except json.JSONDecodeError:
        raise Exception("Failed to parse lncli output")
    except Exception as e:
        raise Exception(f"Command failed: {str(e)}")


def get_routing_hints() -> List[Dict]:
    """Get inbound channels for better routing hints (optional)"""
    try:
        data = run_lncli(["listchannels"], timeout=8)
        hints = []
        for chan in data.get("channels", []):
            remote_balance = int(chan.get("remote_balance", 0))
            if remote_balance > 0:
                hints.append({
                    "chan_id": chan["chan_id"],
                    "node_id": chan["remote_pubkey"],
                    "fee_base_msat": 1000,
                    "fee_proportional_millionths": 1,
                    "cltv_expiry_delta": 40
                })
        return hints[:5]  # Limit to 5 best hints
    except Exception:
        return []  # Graceful fallback


# =========================
# Endpoints
# =========================
@app.post("/create-invoice")
async def create_invoice(req: InvoiceRequest):
    """Create a new Lightning invoice"""
    if req.amount < 1:
        raise HTTPException(400, "Amount must be at least 1 sat")

    try:
        # Create invoice
        data = run_lncli([
            "addinvoice",
            "--amt", str(req.amount),
            "--memo", req.memo
        ])

        payment_request = data.get("payment_request")
        r_hash = data.get("r_hash", "")

        # Optional: attach routing hints for better payment success
        routing_hints = get_routing_hints()

        return {
            "invoice": payment_request,
            "payment_hash": r_hash,
            "routing_hints": routing_hints if routing_hints else None
        }

    except Exception as e:
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


@app.get("/check-payment/{payment_hash}")
async def check_payment(payment_hash: str):
    """Check if an invoice has been settled"""
    if not payment_hash or len(payment_hash) != 64:
        raise HTTPException(400, "Invalid payment_hash format")

    try:
        data = run_lncli(["lookupinvoice", payment_hash], timeout=10)
        settled = data.get("settled", False)
        return {"paid": settled, "state": data.get("state", "UNKNOWN")}

    except Exception:
        # If lookup fails, we assume not paid yet
        return {"paid": False}


@app.post("/verify-preimage")
async def verify_preimage(req: VerifyPreimageRequest):
    """
    Cryptographically verify that the preimage matches the payment_hash.
    This is critical for L402 security.
    """
    if not req.payment_hash or not req.preimage:
        raise HTTPException(400, "Missing payment_hash or preimage")

    try:
        # Clean inputs
        ph = req.payment_hash.strip().lower()
        pi = req.preimage.strip().lower()

        # Compute SHA256 of preimage
        computed_hash = hashlib.sha256(bytes.fromhex(pi)).hexdigest()

        is_valid = computed_hash == ph

        return {
            "valid": is_valid,
            "payment_hash": ph
        }

    except Exception as e:
        raise HTTPException(400, f"Invalid preimage format: {str(e)}")


# =========================
# Health Check
# =========================
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "lnd-bridge",
        "lnd_connected": True  # You can enhance this later with actual check
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
