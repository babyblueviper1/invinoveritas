"""
invinoveritas Unified Agent Client
Automatically fetches price → requests invoice → pays → retries with L402
Supports LND (preferred) and Core Lightning (CLN)
"""

import os
import sys
import json
import argparse
import requests

# Try importing Lightning clients
try:
    from lndgrpc import LNDClient
except ImportError:
    LNDClient = None

try:
    from pyln.client import LightningRpc
except ImportError:
    LightningRpc = None


# =========================
# CONFIG
# =========================
API_BASE = os.getenv("API_BASE", "https://your-api.onrender.com")

LND_DIR = os.getenv("LND_DIR")           # e.g. /root/.lnd
CLN_RPC_PATH = os.getenv("CLN_RPC_PATH")


# =========================
# HELPERS
# =========================
def fetch_price(endpoint: str) -> int:
    """Fetch current dynamic price"""
    resp = requests.get(f"{API_BASE}/price/{endpoint}", timeout=10)
    resp.raise_for_status()
    price = resp.json().get("price_sats")
    if price is None:
        raise ValueError(f"No price_sats returned for {endpoint}")
    return int(price)


def request_invoice(endpoint: str, payload: dict):
    """Request invoice and extract token + bolt11 from L402 response"""
    resp = requests.post(f"{API_BASE}/{endpoint}", json=payload, timeout=15)

    if resp.status_code == 200:
        return None, None, resp.json()   # already paid or free

    if resp.status_code != 402:
        resp.raise_for_status()

    www_auth = resp.headers.get("WWW-Authenticate")
    if not www_auth or "L402" not in www_auth:
        raise ValueError("Invalid L402 response from server")

    try:
        # Format: L402 token="xxx", invoice="lnbc..."
        token_part = www_auth.split('token="')[1].split('"')[0]
        invoice_part = www_auth.split('invoice="')[1].split('"')[0]
        return token_part, invoice_part, None
    except Exception as e:
        raise ValueError(f"Failed to parse L402 header: {e}")


def pay_with_lnd(bolt11: str) -> str:
    """Pay using LND (recommended)"""
    if not LNDClient:
        raise RuntimeError("lndgrpc not installed. Run: pip install lndgrpc")
    if not LND_DIR:
        raise RuntimeError("LND_DIR environment variable not set")

    print("Paying via LND...")
    lnd = LNDClient(LND_DIR)
    response = lnd.send_payment_sync(payment_request=bolt11)
    return response.payment_preimage.hex()


def pay_with_cln(bolt11: str) -> str:
    """Pay using Core Lightning"""
    if not LightningRpc:
        raise RuntimeError("pyln-client not installed. Run: pip install pyln-client")
    if not CLN_RPC_PATH:
        raise RuntimeError("CLN_RPC_PATH environment variable not set")

    print("Paying via Core Lightning...")
    rpc = LightningRpc(CLN_RPC_PATH)
    result = rpc.pay(bolt11)
    return result.get("payment_preimage")


def main():
    parser = argparse.ArgumentParser(description="invinoveritas Agent Client")
    parser.add_argument("--endpoint", choices=["reason", "decision"], required=True)
    parser.add_argument("--question", type=str, help="Question for /reason")
    parser.add_argument("--goal", type=str, help="Goal for /decision")
    parser.add_argument("--context", type=str, help="Context for /decision")
    args = parser.parse_args()

    # Build payload
    if args.endpoint == "decision":
        if not all([args.goal, args.context, args.question]):
            print("Error: --endpoint=decision requires --goal, --context and --question")
            sys.exit(1)
        payload = {
            "goal": args.goal,
            "context": args.context,
            "question": args.question
        }
    else:
        if not args.question:
            print("Error: --endpoint=reason requires --question")
            sys.exit(1)
        payload = {"question": args.question}

    # Step 1: Get current price
    try:
        price = fetch_price(args.endpoint)
        print(f"Current price for /{args.endpoint}: {price} sats")
    except Exception as e:
        print(f"❌ Failed to fetch price: {e}")
        sys.exit(1)

    # Step 2: Request invoice
    try:
        token, bolt11, already_paid = request_invoice(args.endpoint, payload)
        if already_paid:
            print("✅ Already paid or free response:")
            print(json.dumps(already_paid, indent=2))
            sys.exit(0)
    except Exception as e:
        print(f"❌ Failed to request invoice: {e}")
        sys.exit(1)

    print(f"✅ Received invoice for {price} sats")
    print(f"Token : {token[:20]}...")

    # Step 3: Pay the invoice
    try:
        if LND_DIR and LNDClient:
            preimage = pay_with_lnd(bolt11)
        elif CLN_RPC_PATH and LightningRpc:
            preimage = pay_with_cln(bolt11)
        else:
            print("❌ No Lightning node configured. Set LND_DIR or CLN_RPC_PATH")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Payment failed: {e}")
        sys.exit(1)

    print(f"✅ Payment successful! Preimage: {preimage[:20]}...")

    # Step 4: Retry with L402 header
    auth_header = f"L402 {token}:{preimage}"
    try:
        resp = requests.post(
            f"{API_BASE}/{args.endpoint}",
            json=payload,
            headers={"Authorization": auth_header},
            timeout=20
        )
        resp.raise_for_status()
        print("\n🎉 Success! AI Response:")
        print(json.dumps(resp.json(), indent=2))
    except Exception as e:
        print(f"❌ Failed to get final response: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
