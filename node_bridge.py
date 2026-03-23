import requests
from config import NODE_URL


def create_invoice(amount):
    try:
        r = requests.post(
            f"{NODE_URL}/create_invoice",
            json={"amount": amount},
            timeout=10
        )
        r.raise_for_status()
        return r.json()

    except requests.exceptions.RequestException as e:
        return {
            "error": "unable to reach lightning node",
            "details": str(e)
        }


def check_payment(payment_hash):
    try:
        r = requests.get(
            f"{NODE_URL}/check/{payment_hash}",
            timeout=10
        )
        r.raise_for_status()
        return r.json()["paid"]

    except requests.exceptions.RequestException:
        return False
