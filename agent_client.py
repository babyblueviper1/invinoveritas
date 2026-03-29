"""
invinoveritas Unified Agent Client – LND & CLN with Dynamic Pricing
-------------------------------------------------------------------
Automatically fetches current price, requests invoice, pays, and retries.
"""

import os
import requests
import json
import sys
import time

# LND
try:
    import grpc
    from lndgrpc import LNDClient
except ImportError:
    pass

# CLN
try:
    from pyln.client import LightningRpc
except ImportError:
    pass

# -------------------------
# CONFIG
# -------------------------
API_BASE = "https://your-api.onrender.com"  # deployed FastAPI
ENDPOINT = "reason"  # or "decision"

# For /decision endpoint
DECISION_PAYLOAD = {
    "goal": "Grow capital safely",
    "context": "User holds BTC and cash",
    "question": "Should exposure be increased?"
}

# Node config (set one of these in environment variables)
LND_DIR = os.getenv("LND_DIR")          # ~/.lnd for LND
CLN_RPC_PATH = os.getenv("CLN_RPC_PATH") # ~/.lightning/lightning-rpc for CLN

# -------------------------
# Helper functions
# -------------------------
def fetch_price(endpoint: str) -> int:
    """Fetch current dynamic price from API."""
    resp = requests.get(f"{API_BASE}/price/{endpoint}")
    resp.raise_for_status()
    price_sats = resp.json().get("price_sats")
    if price_sats is None:
        raise ValueError(f"No price returned for endpoint {endpoint}")
    return price_sats

def request_invoice(endpoint: str, payload: dict):
    """Request Lightning invoice from API."""
    resp = requests.post(f"{API_BASE}/{endpoint}", json=payload)
    if resp.status_code != 402:
        # Already paid or free
        return None, None, resp.json()
    www_auth = resp.headers.get("WWW-Authenticate")
    challenge_parts = www_auth.split("token=")[1].split(", invoice=")
    macaroon = challenge_parts[0].strip('"')
    bolt11 = challenge_parts[1].strip('"')
    return macaroon, bolt11, None

def pay_lnd(bolt11: str) -> str:
    lnd = LNDClient(LND_DIR)
    result = lnd.send_payment(bolt11)
    return result.payment_preimage

def pay_cln(bolt11: str) -> str:
    rpc = LightningRpc(CLN_RPC_PATH)
    result = rpc.pay(bolt11)
    return result.get("payment_preimage")

# -------------------------
# MAIN FLOW
# -------------------------
payload = DECISION_PAYLOAD if ENDPOINT == "decision" else {"question": "Explain Bitcoin as a long-term strategy"}

# Fetch dynamic price
price_sats = fetch_price(ENDPOINT)
print(f"{ENDPOINT} current price: {price_sats} sats")

# Request invoice
macaroon, bolt11, pre_paid = request_invoice(ENDPOINT, payload)

if pre_paid:
    print("Response (already paid or free):", json.dumps(pre_paid, indent=2))
    sys.exit(0)

print(f"Invoice: {bolt11}")
print(f"Temporary token: {macaroon}")

# Pay invoice via configured node
preimage = None
if LND_DIR:
    print("Paying via LND...")
    preimage = pay_lnd(bolt11)
elif CLN_RPC_PATH:
    print("Paying via CLN...")
    preimage = pay_cln(bolt11)
else:
    print("No Lightning node configured. Set LND_DIR or CLN_RPC_PATH.")
    sys.exit(1)

print("Payment successful, preimage:", preimage)

# Retry request with Authorization header
auth_header = f"L402 {macaroon}:{preimage}"
resp = requests.post(f"{API_BASE}/{ENDPOINT}", json=payload, headers={"Authorization": auth_header})
resp.raise_for_status()
print("AI Output:", json.dumps(resp.json(), indent=2))
