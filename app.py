from fastapi import FastAPI
from node_bridge import create_invoice, check_payment
from ai import premium_reasoning
from config import SUBSCRIPTION_PRICE
import time

app = FastAPI()


@app.get("/")
def home():
    return {"status": "API running"}


@app.post("/subscribe")
def subscribe():
    invoice = create_invoice(SUBSCRIPTION_PRICE)

    payment_hash = invoice["payment_hash"]

    # wait for payment automatically
    for _ in range(90):
        if check_payment(payment_hash):
            return {
                "status": "subscribed",
                "subscription_key": payment_hash
            }

        time.sleep(1)

    return {
        "status": "payment_required",
        "invoice": invoice["invoice"],
        "price": SUBSCRIPTION_PRICE
    }


@app.post("/premium")
def premium(subscription_key: str, question: str):

    if not check_payment(subscription_key):
        return {"error": "subscription required"}

    result = premium_reasoning(question)

    return {
        "status": "unlocked",
        "result": result
    }
