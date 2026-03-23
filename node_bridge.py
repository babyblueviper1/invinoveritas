import requests
from config import NODE_URL


def create_invoice(amount):
    r = requests.post(
        f"{NODE_URL}/create_invoice",
        json={"amount": amount},
        timeout=10
    )
    return r.json()


def check_payment(payment_hash):
    r = requests.get(
        f"{NODE_URL}/check/{payment_hash}",
        timeout=10
    )
    return r.json()["paid"]
