import requests
from config import NODE_URL

# This file runs on Render and calls the bridge running on your VPS

def create_invoice(amount_sats: int, memo: str = "invinoveritas"):
    """
    Calls the bridge on your VPS to create a Lightning invoice.
    """
    try:
        payload = {
            "amount": amount_sats,
            "memo": memo
        }
        
        response = requests.post(
            f"{NODE_URL}/create-invoice",
            json=payload,
            timeout=15
        )
        response.raise_for_status()
        return response.json()
        
    except Exception as e:
        return {"error": f"Bridge error: {str(e)}"}


def check_payment(payment_hash: str) -> bool:
    """
    Calls the bridge on your VPS to check if an invoice was paid.
    """
    try:
        response = requests.get(
            f"{NODE_URL}/check-payment/{payment_hash}",
            timeout=10
        )
        response.raise_for_status()
        return response.json().get("paid", False)
        
    except Exception as e:
        print(f"Check payment error: {e}")
        return False
