from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment  # your existing functions
from ai import premium_reasoning
from config import SUBSCRIPTION_PRICE  # rename mentally to REASONING_PRICE_SATS
import os

app = FastAPI(title="invinoveritas – Lightning-paid AI Reasoning")

PRICE_SATS = SUBSCRIPTION_PRICE  # e.g. 10000 sats per reasoning call; make dynamic later

class ReasoningRequest(BaseModel):
    question: str

# Home / health unchanged
@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>invinoveritas API is running ⚡🤖</h1>"

@app.get("/health")
def health():
    return {"status": "ok"}

# New: Main paid reasoning endpoint (agent-friendly)
@app.post("/reason")
async def reason(request: Request, data: ReasoningRequest):
    # Check for L402 Authorization header
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("L402 "):
        # First request: issue challenge
        invoice_data = create_invoice(PRICE_SATS)
        invoice = invoice_data["invoice"]  # bolt11 string
        payment_hash = invoice_data["payment_hash"]

        # For simplicity, use payment_hash as "macaroon" identifier (real L402 uses macaroons for scoped auth)
        # In production → bake real macaroon with caveats (e.g. valid for 1 request, tied to hash)
        macaroon = payment_hash  # placeholder; upgrade later

        challenge = f'token="{macaroon}", invoice="{invoice}"'

        headers = {
            "WWW-Authenticate": f'L402 {challenge}',
            "Retry-After": "10"  # hint for agents
        }
        raise HTTPException(
            status_code=402,
            detail="Payment Required – pay Lightning invoice to access reasoning",
            headers=headers
        )

    # Parse Authorization: L402 <macaroon>:<preimage>
    try:
        _, creds = auth.split(" ", 1)
        macaroon, preimage = creds.split(":", 1)
    except:
        raise HTTPException(401, "Invalid L402 credentials")

    # Verify payment (your existing function checks preimage matches settled invoice)
    if not check_payment(macaroon):  # macaroon here is payment_hash
        raise HTTPException(403, "Invalid or unpaid credential")

    # Paid → run AI
    result = premium_reasoning(data.question)

    return {
        "status": "reasoned",
        "answer": result
    }

# Optional: Keep old /subscribe for human testing, but deprecate it
# ...
