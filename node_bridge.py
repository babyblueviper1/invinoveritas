import requests
from config import NODE_URL
from typing import Dict, Optional


def create_invoice(amount: int) -> Optional[Dict[str, str]]:
    """
    Create Lightning invoice via bridge.
    Returns: {"invoice": str, "payment_hash": str} or None if failure.
    """
    try:
        r = requests.post(
            f"{NODE_URL}/create_invoice",
            json={"amount": amount, "memo": "invinoveritas reasoning"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        if "invoice" not in data or "payment_hash" not in data:
            return None

        return {
            "invoice": data["invoice"],
            "payment_hash": data["payment_hash"]
        }

    except (requests.exceptions.RequestException, ValueError):
        return None


def check_payment(payment_hash: str) -> bool:
    """
    Check if invoice is paid.
    Returns True if settled, False otherwise.
    """

    if not payment_hash:
        return False

    try:
        r = requests.get(
            f"{NODE_URL}/check/{payment_hash}",
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()

        return data.get("paid", False)

    except (requests.exceptions.RequestException, ValueError):
        return False
