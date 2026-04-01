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
            time.sleep(0.6 * (attempt + 1))  # backoff
    
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
    Check if the invoice has been paid.
    """
    if not payment_hash or len(payment_hash) != 64:
        print("Invalid payment_hash provided")
        return False

    try:
        url = f"{NODE_URL.rstrip('/')}/check-payment/{payment_hash}"
        data = _make_request("GET", url, timeout=10)
        
        if "error" in data:
            return False
            
        return bool(data.get("paid", False))
        
    except Exception as e:
        print(f"Check payment error for {payment_hash[:12]}...: {e}")
        return False


def verify_preimage(payment_hash: str, preimage: str) -> bool:
    """
    Verify that the provided preimage matches the payment_hash.
    This is the most important security check for L402.
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
            print(f"Preimage verification error: {data['error']}")
            return False

        return bool(data.get("valid", False))
        
    except Exception as e:
        print(f"Preimage verification failed: {e}")
        return False


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
