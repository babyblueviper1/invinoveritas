"""
invinoveritas Unified Agent Client – LND & CLN with Dynamic Pricing
-------------------------------------------------------------------
Automatically fetches current price, requests invoice, pays, and retries.
Supports CLI arguments for flexible use.
"""

import os
import sys
import time
import json
import argparse
import requests

# LND
try:
    import grpc
    from lndgrpc import LNDClient
except ImportError:
    LNDClient = None

# CLN
try:
    from pyln.client import LightningRpc
except ImportError:
    LightningRpc = None

# -------------------------
# CONFIG
# -------------------------
API_BASE = os.getenv("API_BASE", "https://your-api.onrender.com")

# Node config (set one of these environment variables)
LND_DIR = os.getenv("LND_DIR")          # e.g., ~/.lnd
CLN_RPC_PATH = os.getenv("CLN_RPC_PATH") # e.g., ~/.lightning/lightning-rpc

# -------------------------
# HELPER FUNCTIONS
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
    if not LNDClient:
        raise RuntimeError("lndgrpc not installed")
    lnd = LNDClient(LND_DIR)
    result = lnd.send_payment(bolt11)
    return result.payment_preimage

def pay_cln(bolt11: str) -> str:
    if not LightningRpc:
        raise RuntimeError("pyln-client not installed")
    rpc = LightningRpc(CLN_RPC_PATH)
    result = rpc.pay(bolt11)
    return result.get("payment_preimage")

def main():
    parser = argparse.ArgumentParser(description="invinoveritas Agent Client")
    parser.add_argument("--endpoint", choices=["reason", "decision"], required=True, help="API endpoint")
    parser.add_argument("--question", type=str, help="Question for /reason or /decision")
    parser.add_argument("--goal", type=str, help="Goal for /decision")
    parser.add_argument("--context", type=str, help="Context for /decision")
    args = parser.parse_args()

    if args.endpoint == "decision":
        if not all([args.goal, args.context, args.question]):
            print("For /decision you must provide --goal, --context, --question")
            sys.exit(1)
        payload = {
            "goal": args.goal,
            "context": args.context,
            "question": args.question
        }
    else:
        if not args.question:
            print("For /reason you must provide --question")
            sys.exit(1)
        payload = {"question": args.question}

    # Fetch current price
    price_sats = fetch_price(args.endpoint)
    print(f"{args.endpoint} current price: {price_sats} sats")

    # Request invoice
    macaroon, bolt11, pre_paid = request_invoice(args.endpoint, payload)
    if pre_paid:
        print("Response (already paid or free):", json.dumps(pre_paid, indent=2))
        sys.exit(0)

    print(f"Invoice: {bolt11}")
    print(f"Temporary token: {macaroon}")

    # Pay invoice
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
    resp = requests.post(f"{API_BASE}/{args.endpoint}", json=payload, headers={"Authorization": auth_header})
    resp.raise_for_status()
    print("AI Output:", json.dumps(resp.json(), indent=2))

if __name__ == "__main__":
    main()
