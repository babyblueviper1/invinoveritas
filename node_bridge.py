import requests
from config import NODE_URL
import time
from typing import Dict, Any, Optional

# Optional: Add a small retry mechanism for better reliability
def _make_request(method: str, url: str, json_data: Optional[Dict] = None, timeout: int = 10) -> Dict[str, Any]:
    """Internal helper with basic retry logic"""
    for attempt in range(3):  # retry up to 3 times
        try:
            if method == "POST":
                response = requests.post(url, json=json_data, timeout=timeout)
            else:  # GET
                response = requests.get(url, timeout=timeout)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            if attempt == 2:  # last attempt
                print(f"Bridge request failed after {attempt+1} attempts: {e}")
                raise
            time.sleep(0.5 * (attempt + 1))  # exponential backoff
    
    return {"error": "Unknown bridge error"}


def create_invoice(amount_sats: int, memo: str = "invinoveritas") -> Dict[str, Any]:
    """
    Calls the Lightning bridge on your VPS to create a new invoice.
    
    Returns:
        {
            "payment_hash": "...",
            "invoice": "lnbc...",
            "amount": 500,
            ...
        }
        or {"error": "..."} on failure
    """
    if amount_sats < 1:
        return {"error": "Amount must be at least 1 sat"}

    try:
        payload = {
            "amount": amount_sats,
            "memo": memo[:100]  # prevent overly long memos
        }
        
        url = f"{NODE_URL}/create-invoice"
        data = _make_request("POST", url, json_data=payload, timeout=15)
        
        # Basic validation of response
        if not isinstance(data, dict):
            return {"error": "Invalid response from bridge"}
            
        if "payment_hash" not in data or "invoice" not in data:
            return {"error": "Bridge response missing required fields (payment_hash or invoice)"}
            
        return data
        
    except Exception as e:
        print(f"Create invoice error: {e}")
        return {"error": f"Bridge error: {str(e)}"}


def check_payment(payment_hash: str) -> bool:
    """
    Calls the bridge to check if an invoice has been paid.
    
    Returns True only if the payment is confirmed settled.
    """
    if not payment_hash or not isinstance(payment_hash, str):
        print("Invalid payment_hash provided")
        return False

    try:
        url = f"{NODE_URL}/check-payment/{payment_hash}"
        data = _make_request("GET", url, timeout=10)
        
        if not isinstance(data, dict):
            return False
            
        paid = data.get("paid", False)
        # Optional: log status for debugging
        if not paid and data.get("status"):
            print(f"Payment status for {payment_hash[:8]}...: {data.get('status')}")
            
        return bool(paid)
        
    except Exception as e:
        print(f"Check payment error for {payment_hash[:8]}...: {e}")
        return False


# ================ RECOMMENDED ADDITION ================
def verify_preimage(payment_hash: str, preimage: str) -> bool:
    """
    IMPORTANT: Verify that the provided preimage actually matches the payment_hash.
    This prevents fake preimages from being accepted.
    
    Call this in app.py before marking the payment as used.
    """
    if not payment_hash or not preimage:
        return False
    
    try:
        url = f"{NODE_URL}/verify-preimage"
        payload = {
            "payment_hash": payment_hash,
            "preimage": preimage
        }
        data = _make_request("POST", url, json_data=payload, timeout=8)
        
        return bool(data.get("valid", False))
        
    except Exception as e:
        print(f"Preimage verification error: {e}")
        return False
