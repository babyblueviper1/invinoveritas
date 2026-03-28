from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment
from ai import premium_reasoning
from config import SUBSCRIPTION_PRICE
import os

app = FastAPI(title="invinoveritas – Lightning-paid Decision Intelligence")

PRICE_SATS = SUBSCRIPTION_PRICE


class ReasoningRequest(BaseModel):
    question: str


@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>invinoveritas API is running ⚡🤖</h1>"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/reason")
async def reason(request: Request, data: ReasoningRequest):

    # Basic prompt safety guard (protect cost)
    if len(data.question) > 2000:
        raise HTTPException(400, "Prompt too long for this endpoint")

    auth = request.headers.get("Authorization")

    # Step 1: No payment yet → send Lightning invoice
    if not auth or not auth.startswith("L402 "):
        invoice_data = create_invoice(PRICE_SATS)
        invoice = invoice_data["invoice"]
        payment_hash = invoice_data["payment_hash"]

        # For v1: use payment_hash as temporary credential
        macaroon = payment_hash

        challenge = f'token="{macaroon}", invoice="{invoice}"'

        raise HTTPException(
            status_code=402,
            detail="Payment Required – pay Lightning invoice to unlock premium reasoning",
            headers={
                "WWW-Authenticate": f'L402 {challenge}',
                "Retry-After": "10"
            }
        )

    # Step 2: Authorization header present → verify payment
    try:
        _, creds = auth.split(" ", 1)
        macaroon, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 credentials")

    if not check_payment(macaroon):
        raise HTTPException(403, "Invalid or unpaid credential")

    # Step 3: Paid → run premium reasoning
    result = premium_reasoning(data.question)

    return {
        "status": "success",
        "type": "premium_reasoning",
        "answer": result
    }
