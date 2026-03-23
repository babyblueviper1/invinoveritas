from config import OPENAI_API_KEY
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment
from ai import premium_reasoning
from config import SUBSCRIPTION_PRICE
import time
import os

app = FastAPI()


# -------- Request model (important for JSON requests) --------

class PremiumRequest(BaseModel):
    subscription_key: str
    question: str


# -------- Home page --------

@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>invinoveritas API is running</h1>"


# -------- Health check (Render uses this sometimes) --------

@app.get("/health")
def health():
    return {"status": "ok"}


# -------- Subscribe --------

@app.post("/subscribe")
def subscribe():
    invoice = create_invoice(SUBSCRIPTION_PRICE)
    payment_hash = invoice["payment_hash"]

    # wait automatically for payment
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


# -------- Premium reasoning --------

@app.post("/premium")
def premium(data: PremiumRequest):

    if not check_payment(data.subscription_key):
        return {"error": "subscription required"}

    result = premium_reasoning(data.question)

    return {
        "status": "unlocked",
        "result": result
    }
