"""
invinoveritas Unified Agent Client

Automatically handles the full L402 Lightning payment flow:
1. Calls endpoint → gets 402 + invoice
2. Pays via LND (preferred) or Core Lightning (CLN)
3. Retries with Authorization: L402 <token>:<preimage>

Usage examples:
  python agent_client.py --endpoint reason --question "How should I approach the upcoming market shift?"
  python agent_client.py --endpoint decision --goal "Launch new product" --context "Competitor X just raised funding" --question "Should we launch in Q2 or Q3?"
"""

import os
import sys
import json
import argparse
import requests
from typing import Dict, Any, Optional

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
API_BASE = os.getenv("API_BASE", "https://api.babyblueviper.com").rstrip("/")

LND_DIR = os.getenv("LND_DIR")
CLN_RPC_PATH = os.getenv("CLN_RPC_PATH")


# =========================
# HELPERS
# =========================
def pay_invoice(bolt11: str) -> str:
    """Pay bolt11 invoice using LND or CLN. Returns preimage hex."""
    if LND_DIR and LNDClient:
        print("→ Paying via LND...")
        lnd = LNDClient(LND_DIR)
        resp = lnd.send_payment_sync(payment_request=bolt11)
        return resp.payment_preimage.hex()

    if CLN_RPC_PATH and LightningRpc:
        print("→ Paying via Core Lightning...")
        rpc = LightningRpc(CLN_RPC_PATH)
        result = rpc.pay(bolt11)
        return result.get("payment_preimage")

    raise RuntimeError("No Lightning node configured. Set LND_DIR or CLN_RPC_PATH.")


def parse_l402_header(www_auth: str) -> tuple[str, str]:
    """Extract token (payment_hash) and bolt11 from WWW-Authenticate: L402 header."""
    if not www_auth or "L402" not in www_auth:
        raise ValueError(f"Invalid L402 header received: {www_auth}")

    try:
        token = www_auth.split('token="')[1].split('"')[0]
        invoice = www_auth.split('invoice="')[1].split('"')[0]
        return token, invoice
    except (IndexError, AttributeError) as e:
        raise ValueError(f"Failed to parse L402 header: {www_auth}") from e


def call_with_l402(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Full L402 flow: request → pay → retry."""
    url = f"{API_BASE}/{endpoint}"

    # First request - expect 402 Payment Required
    resp = requests.post(url, json=payload, timeout=15, headers={"User-Agent": "invinoveritas-agent/1.0"})

    if resp.status_code == 200:
        return resp.json()  # Already paid (rare)

    if resp.status_code != 402:
        try:
            error = resp.json()
        except Exception:
            error = resp.text
        raise RuntimeError(f"Unexpected status {resp.status_code}: {error}")

    # Parse invoice from L402 header
    www_auth = resp.headers.get("WWW-Authenticate", "")
    token, bolt11 = parse_l402_header(www_auth)

    print(f"→ Received invoice for {endpoint} endpoint")

    # Pay the invoice
    preimage = pay_invoice(bolt11)
    print(f"→ Payment successful. Preimage: {preimage[:16]}...")

    # Retry with payment proof
    auth_header = f"L402 {token}:{preimage}"
    retry_resp = requests.post(
        url,
        json=payload,
        headers={
            "Authorization": auth_header,
            "User-Agent": "invinoveritas-agent/1.0"
        },
        timeout=25,
    )
    retry_resp.raise_for_status()
    return retry_resp.json()


# =========================
# MAIN
# =========================
def main():
    parser = argparse.ArgumentParser(
        description="invinoveritas Agent Client - Lightning-paid AI reasoning & decisions",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--endpoint", choices=["reason", "decision"], required=True,
                        help="Which endpoint to call")
    parser.add_argument("--question", type=str, help="Question for /reason")
    parser.add_argument("--goal", type=str, help="Goal for /decision")
    parser.add_argument("--context", type=str, help="Context for /decision")

    args = parser.parse_args()

    # Build payload
    if args.endpoint == "decision":
        if not all([args.goal, args.context, args.question]):
            parser.error("--endpoint=decision requires --goal, --context and --question")
        payload = {
            "goal": args.goal.strip(),
            "context": args.context.strip(),
            "question": args.question.strip()
        }
    else:  # reason
        if not args.question:
            parser.error("--endpoint=reason requires --question")
        payload = {"question": args.question.strip()}

    print(f"🚀 Calling /{args.endpoint} via invinoveritas...")

    try:
        result = call_with_l402(args.endpoint, payload)

        print("\n🎉 Success! Response received:")
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
