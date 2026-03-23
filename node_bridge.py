import requests
from config import NODE_URL
from typing import Dict, Union, Optional

def create_invoice(amount: int) -> Dict[str, Union[str, int, bool]]:
    """
    Create Lightning invoice via bridge.
    Returns: {"invoice": str, "payment_hash": str} or {"error": str, "details": str}
    """
    try:
        r = requests.post(
            f"{NODE_URL}/create_invoice",
            json={"amount": amount, "memo": "invinoveritas reasoning"},  # optional: add memo for traceability
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        # Optional: validate shape
        if "invoice" not in data or "payment_hash" not in data:
            return {"error": "invalid response from node bridge"}
        return data

    except requests.exceptions.RequestException as e:
        return {"error": "unable to reach lightning node", "details": str(e)}
    except ValueError as e:
        return {"error": "invalid JSON from node bridge", "details": str(e)}


def check_payment(payment_hash: str) -> bool:
    """
    Check if invoice is paid.
    Returns True if settled, False otherwise (including errors).
    """
    if not payment_hash:
        return False

    try:
        r = requests.get(
            f"{NODE_URL}/check/{payment_hash}",
            timeout=8,  # slightly shorter timeout for polling
        )
        r.raise_for_status()
        data = r.json()
        return data.get("paid", False)  # safer access

    except (requests.exceptions.RequestException, ValueError):
        return False  # treat any failure as unpaid → safe default
