from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import subprocess
import json
import hashlib
import time
from typing import Dict, Any, List

app = FastAPI(title="invinoveritas LND Bridge")

class InvoiceRequest(BaseModel):
    amount: int = Field(..., gt=0)
    memo: str = Field("invinoveritas", max_length=100)

class VerifyPreimageRequest(BaseModel):
    payment_hash: str
    preimage: str


def run_lncli(args: list, timeout: int = 12) -> Dict:
    """Robust lncli wrapper"""
    try:
        result = subprocess.run(["lncli"] + args, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise Exception(result.stderr.strip() or result.stdout.strip())
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise Exception("lncli timeout")
    except Exception as e:
        raise Exception(f"lncli error: {str(e)}")


@app.post("/create-invoice")
async def create_invoice(req: InvoiceRequest):
    if req.amount < 1:
        raise HTTPException(400, "Amount must be at least 1 sat")

    try:
        data = run_lncli(["addinvoice", "--amt", str(req.amount), "--memo", req.memo])
        return {
            "invoice": data["payment_request"],
            "payment_hash": data.get("r_hash", "")
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to create invoice: {str(e)}")


@app.get("/check-payment/{payment_hash}")
async def check_payment(payment_hash: str):
    """More robust payment check"""
    if not payment_hash or len(payment_hash) != 64:
        raise HTTPException(400, "Invalid payment_hash")

    try:
        # Try lookupinvoice first
        data = run_lncli(["lookupinvoice", payment_hash], timeout=8)
        settled = data.get("settled", False)
        
        if settled:
            return {"paid": True, "state": "SETTLED"}
        
        # If not settled, try listinvoices as fallback (more reliable for recent payments)
        list_data = run_lncli(["listinvoices", "--max_invoices", "50"], timeout=8)
        
        for inv in list_data.get("invoices", []):
            if inv.get("r_hash") == payment_hash:
                return {"paid": inv.get("settled", False), "state": inv.get("state", "UNKNOWN")}
        
        return {"paid": False, "state": "UNKNOWN"}
        
    except Exception:
        return {"paid": False, "state": "CHECK_FAILED"}


@app.post("/verify-preimage")
async def verify_preimage(req: VerifyPreimageRequest):
    if not req.payment_hash or not req.preimage:
        raise HTTPException(400, "Missing fields")

    try:
        ph = req.payment_hash.strip().lower()
        pi = req.preimage.strip().lower()
        computed = hashlib.sha256(bytes.fromhex(pi)).hexdigest()
        return {"valid": computed == ph}
    except Exception:
        return {"valid": False}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "lnd-bridge"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
