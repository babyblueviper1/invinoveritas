import requests
from config import NODE_URL


# =============================
# Create Lightning Invoice
# =============================

def create_invoice(amount_sats: int):

    try:
        response = requests.post(
            f"{NODE_URL}/create-invoice",
            json={"amount": amount_sats},
            timeout=10
        )

        if response.status_code != 200:
            return {"error": f"Node returned {response.status_code}"}

        data = response.json()

        return {
            "invoice": data.get("invoice"),
            "payment_hash": data.get("payment_hash")
        }

    except Exception as e:
        return {"error": str(e)}


# =============================
# Check if invoice is paid
# =============================

def check_payment(payment_hash: str):

    try:
        response = requests.get(
            f"{NODE_URL}/check-payment/{payment_hash}",
            timeout=10
        )

        if response.status_code != 200:
            return False

        data = response.json()

        return data.get("paid", False)

    except Exception:
        return False
