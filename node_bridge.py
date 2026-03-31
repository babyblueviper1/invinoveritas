import requests
import os
from typing import Dict, Optional

# Load from config or .env
NODE_URL = os.getenv("LND_REST_URL", "http://127.0.0.1:8080")   # Usually http://localhost:8080 or https if TLS
MACAROON_HEX = os.getenv("LND_MACAROON_HEX")                    # Bake a restricted invoice macaroon!

HEADERS = {
    "Grpc-Metadata-macaroon": MACAROON_HEX,
    "Content-Type": "application/json"
}

# =============================
# Create Lightning Invoice
# =============================
def create_invoice(amount_sats: int, memo: str = "invinoveritas reasoning") -> Dict:
    """
    Creates a new Lightning invoice directly via LND REST.
    Returns dict with 'invoice' (bolt11) and 'payment_hash'.
    """
    try:
        payload = {
            "value": str(amount_sats),      # amount in sats
            "memo": memo,
            "expiry": 3600                  # 1 hour expiry (adjust as needed)
        }

        response = requests.post(
            f"{NODE_URL}/v1/invoices",
            json=payload,
            headers=HEADERS,
            timeout=15
        )

        if response.status_code != 200:
            return {"error": f"LND returned {response.status_code}: {response.text}"}

        data = response.json()

        return {
            "invoice": data.get("payment_request"),   # the bolt11 string
            "payment_hash": data.get("r_hash")        # base64 or hex depending on LND version
        }

    except Exception as e:
        return {"error": f"Exception creating invoice: {str(e)}"}


# =============================
# Check if invoice is paid
# =============================
def check_payment(payment_hash: str) -> bool:
    """
    Checks payment status using LookupInvoice.
    payment_hash should be the hex or base64 value returned by create_invoice.
    """
    try:
        # LND expects r_hash_str as hex usually
        response = requests.get(
            f"{NODE_URL}/v1/invoice/{payment_hash}",
            headers=HEADERS,
            timeout=10
        )

        if response.status_code != 200:
            return False

        data = response.json()
        # 'settled' is the reliable field for paid invoices
        return data.get("settled", False)

    except Exception:
        return False
