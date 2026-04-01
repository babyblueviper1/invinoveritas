import requests
import hashlib
from config import NODE_URL
import time
from typing import Dict, Any, Optional

def _make_request(method: str, url: str, json_data: Optional[Dict] = None, timeout: int = 10) -> Dict[str, Any]:
    """Helper with retry logic for flaky Render ↔ VPS connections"""
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
                return {"error": f"Bridge request failed: {str(e)}"}
            time.sleep(0.5 * (attempt + 1))  # backoff
    
    return {"error": "Unknown bridge error"}


def create_invoice(amount_sats: int, memo: str = "invinoveritas") -> Dict[str, Any]:
    """
    Create a Lightning invoice via your LND bridge on VPS.
    """
    if amount_sats < 1:
        return {"error": "Amount must be at least 1 sat"}

    try:
        payload = {
            "amount": amount_sats,
            "memo": memo[:100]   # safety limit
        }
        
        url = f"{NODE_URL.rstrip('/')}/create-invoice"
        data = _make_request("POST", url, json_data=payload, timeout=15)
        
        if "error" in data:
            return data
            
        # Basic sanity check on response from bridge
        if not isinstance(data, dict) or "payment_hash" not in data or "invoice" not in data:
            return {"error": "Invalid response from bridge (missing payment_hash or invoice)"}
            
        return data
        
    except Exception as e:
        print(f"Create invoice error: {e}")
        return {"error": f"Bridge error: {str(e)}"}


def check_payment(payment_hash: str) -> bool:
    """
    Check if the invoice has been paid (settled) on LND.
    """
    if not payment_hash or len(payment_hash) != 64:  # quick sanity check (64 hex chars)
        print("Invalid payment_hash format")
        return False

    try:
        url = f"{NODE_URL.rstrip('/')}/check-payment/{payment_hash}"
        data = _make_request("GET", url, timeout=10)
        
        if "error" in data:
            print(f"Check payment error: {data['error']}")
            return False
            
        paid = data.get("paid", False)
        return bool(paid)
        
    except Exception as e:
        print(f"Check payment error for {payment_hash[:12]}...: {e}")
        return False


def verify_preimage(payment_hash: str, preimage: str) -> bool:
    """
    Cryptographically verify that the provided preimage matches the payment_hash.
    
    This is the most secure way for L402 — no extra RPC call needed if you trust the hash.
    LND uses SHA-256(preimage) == payment_hash.
    """
    if not payment_hash or not preimage:
        return False
    
    try:
        # Clean inputs
        ph = payment_hash.strip().lower()
        pi = preimage.strip().lower()
        
        # Compute SHA256 of preimage and compare (hex)
        computed_hash = hashlib.sha256(bytes.fromhex(pi)).hexdigest()
        
        is_valid = computed_hash == ph
        
        if not is_valid:
            print(f"Preimage verification FAILED for hash {ph[:12]}...")
            
        return is_valid
        
    except Exception as e:
        print(f"Preimage verification error: {e}")
        return False
