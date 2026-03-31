import requests
import os
from typing import Dict, Optional

# Load from config
from config import LND_REST_URL, LND_MACAROON_HEX

if not LND_MACAROON_HEX:
    raise ValueError("LND_MACAROON_HEX is missing in config! Please set it.")

HEADERS = {
    "Grpc-Metadata-macaroon": LND_MACAROON_HEX,
    "Content-Type": "application/json"
}


# =============================
# Create Lightning Invoice
# =============================
def create_invoice(amount_sats: int, memo: str = "invinoveritas") -> Dict:
    """
    Creates a Lightning invoice directly via LND.
    Returns: {"invoice": "lnbc...", "payment_hash": "..."}
    """
    try:
        payload = {
            "value": str(amount_sats),
            "memo": memo,
            "expiry": 3600,          # 1 hour validity
            "private": True          # Recommended for privacy
        }

        response = requests.post(
            f"{LND_REST_URL}/v1/invoices",
            json=payload,
            headers=HEADERS,
            timeout=15
        )

        if response.status_code != 200:
            return {
                "error": f"LND returned {response.status_code}",
                "details": response.text
            }

        data = response.json()

        return {
            "invoice": data.get("payment_request"),
            "payment_hash": data.get("r_hash")        # base64 encoded
        }

    except Exception as e:
        return {"error": f"Exception: {str(e)}"}


# =============================
# Check if invoice is paid
# =============================
def check_payment(payment_hash: str) -> bool:
    """
    Checks whether the invoice has been paid.
    Works with the payment_hash returned by create_invoice.
    """
    try:
        response = requests.get(
            f"{LND_REST_URL}/v1/invoice/{payment_hash}",
            headers=HEADERS,
            timeout=10
        )

        if response.status_code != 200:
            return False

        data = response.json()
        return data.get("settled", False)   # True = paid

    except Exception:
        return False


# =============================
# Optional: Get invoice details
# =============================
def get_invoice_details(payment_hash: str) -> Dict:
    """Returns full invoice info (useful for debugging)"""
    try:
        response = requests.get(
            f"{LND_REST_URL}/v1/invoice/{payment_hash}",
            headers=HEADERS,
            timeout=10
        )
        if response.status_code == 200:
            return response.json()
        return {"error": response.text}
    except Exception as e:
        return {"error": str(e)}
