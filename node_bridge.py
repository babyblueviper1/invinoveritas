import requests
import hashlib
from config import NODE_URL
import time
from typing import Dict, Any, Optional

# =========================
# Helper
# =========================
def _make_request(method: str, url: str, json_data: Optional[Dict] = None, timeout: int = 12) -> Dict[str, Any]:
    """Internal helper with retry logic for Render ↔ VPS communication"""
    for attempt in range(3):
        try:
            if method.upper() == "POST":
                response = requests.post(url, json=json_data, timeout=timeout)
            else:
                response = requests.get(url, timeout=timeout)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            if attempt == 2:  # last attempt
                print(f"Bridge request failed after {attempt+1} attempts to {url}: {e}")
                return {"error": f"Bridge communication failed: {str(e)}"}
            time.sleep(0.7 * (attempt + 1))  # backoff
    
    return {"error": "Unknown bridge error"}


# =========================
# Main Functions
# =========================
def create_invoice(amount_sats: int, memo: str = "invinoveritas") -> Dict[str, Any]:
    """
    Create a Lightning invoice via the VPS bridge.
    """
    if amount_sats < 1:
        return {"error": "Amount must be at least 1 sat"}

    try:
        payload = {
            "amount": amount_sats,
            "memo": memo[:100]
        }
        
        url = f"{NODE_URL.rstrip('/')}/create-invoice"
        data = _make_request("POST", url, json_data=payload, timeout=15)
        
        if "error" in data:
            return data

        if not isinstance(data, dict) or "invoice" not in data or "payment_hash" not in data:
            return {"error": "Invalid response from bridge"}

        return {
            "invoice": data["invoice"],
            "payment_hash": data["payment_hash"]
        }
        
    except Exception as e:
        print(f"Create invoice error: {e}")
        return {"error": f"Bridge error: {str(e)}"}


def check_payment(payment_hash: str) -> bool:
    """
    Robust payment check with multiple retries and longer patience.
    This should greatly reduce 'Payment not settled yet' issues.
    """
    if not payment_hash or len(payment_hash) != 64:
        print("Invalid payment_hash provided")
        return False

    for attempt in range(10):        # Up to ~20 seconds of patience
        try:
            url = f"{NODE_URL.rstrip('/')}/check-payment/{payment_hash}"
            data = _make_request("GET", url, timeout=12)
            
            if data.get("paid", False):
                print(f"Payment {payment_hash[:12]}... confirmed settled on attempt {attempt+1}")
                return True
                
            # If not settled yet, wait before next attempt
            if attempt < 9:
                wait_time = 1.8 if attempt < 4 else 2.5
                time.sleep(wait_time)
                
        except Exception as e:
            print(f"Check payment attempt {attempt+1} failed: {e}")
            if attempt < 9:
                time.sleep(2.0)
    
    print(f"Payment {payment_hash[:12]}... still not settled after retries")
    return False


def verify_preimage(payment_hash: str, preimage: str) -> bool:
    """
    Verify that the provided preimage matches the payment_hash.
    Critical for L402 security.
    """
    if not payment_hash or not preimage:
        return False

    try:
        url = f"{NODE_URL.rstrip('/')}/verify-preimage"
        payload = {
            "payment_hash": payment_hash.strip().lower(),
            "preimage": preimage.strip().lower()
        }
        
        data = _make_request("POST", url, json_data=payload, timeout=8)
        
        if "error" in data:
            print(f"Preimage verification error: {data.get('error')}")
            return False

        return bool(data.get("valid", False))
        
    except Exception as e:
        print(f"Preimage verification failed: {e}")
        return False


# =========================
# Outbound Payments (Marketplace seller payouts)
# =========================
def pay_bolt11(bolt11: str, memo: str = "payout") -> Dict[str, Any]:
    """
    Pay an outbound Lightning invoice via the VPS bridge.
    Used for marketplace seller payouts (90% of sale price).
    Returns {"payment_hash": ..., "preimage": ...} or {"error": ...}
    """
    if not bolt11 or not bolt11.startswith("ln"):
        return {"error": "Invalid bolt11 invoice"}

    try:
        url = f"{NODE_URL.rstrip('/')}/pay-invoice"
        data = _make_request("POST", url, json_data={"bolt11": bolt11, "memo": memo}, timeout=30)
        if "error" in data:
            return data
        return {
            "payment_hash": data.get("payment_hash", ""),
            "preimage": data.get("preimage", ""),
        }
    except Exception as e:
        print(f"pay_bolt11 error: {e}")
        return {"error": f"Payment failed: {str(e)}"}


def fetch_lnurl_invoice(lightning_address: str, amount_sats: int) -> Dict[str, Any]:
    """
    Resolve a Lightning Address (user@domain.com) or LNURL to a bolt11 invoice.
    Returns {"bolt11": ...} or {"error": ...}
    """
    try:
        if "@" in lightning_address:
            user, domain = lightning_address.split("@", 1)
            lnurl_url = f"https://{domain}/.well-known/lnurlp/{user}"
        else:
            lnurl_url = lightning_address

        resp = requests.get(lnurl_url, timeout=10)
        resp.raise_for_status()
        meta = resp.json()

        callback = meta.get("callback")
        min_sendable = meta.get("minSendable", 1000)  # millisats
        max_sendable = meta.get("maxSendable", 10_000_000_000)

        amount_msats = amount_sats * 1000
        if not (min_sendable <= amount_msats <= max_sendable):
            return {"error": f"Amount {amount_sats} sats out of range for this address"}

        invoice_resp = requests.get(callback, params={"amount": amount_msats}, timeout=10)
        invoice_resp.raise_for_status()
        invoice_data = invoice_resp.json()
        bolt11 = invoice_data.get("pr") or invoice_data.get("invoice")
        if not bolt11:
            return {"error": "No invoice returned from Lightning address"}
        return {"bolt11": bolt11}

    except Exception as e:
        print(f"fetch_lnurl_invoice error: {e}")
        return {"error": f"Failed to fetch invoice from Lightning address: {str(e)}"}


# =========================
# Optional: Bridge Health Check
# =========================
def check_bridge_health() -> bool:
    """Quick check if the bridge is reachable"""
    try:
        url = f"{NODE_URL.rstrip('/')}/health"
        data = _make_request("GET", url, timeout=5)
        return data.get("status") == "ok"
    except Exception:
        return False
