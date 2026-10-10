#!/usr/bin/env python3
"""Live L402 demo, run from this directory (examples/l402-verdict-gate).

    python3 l402_demo.py mismatch   joke endpoint, but the agent's task is a BTC price for a trade -> expect reject, nothing paid
    python3 l402_demo.py pay        quote endpoint for the newsletter task -> verdict -> 10 sats over Lightning -> 200 -> receipt
Env: INVINOVERITAS_KEY, LND_MACAROON (pay-only), LND_TLS_CERT, LND_REST (default https://127.0.0.1:8080).
"""
import json
import os
import sys
import time

from l402_verdict_gate import LndRestWallet, VerdictGate, l402_request, verify_receipt
from l402_verdict_gate.challenge import parse_challenge
from l402_verdict_gate.client import PaymentBlocked, urllib_http

MODE = sys.argv[1]
T0 = time.time()
QUOTE = "https://lightningfaucet.com/api/l402/quote"
JOKE = "https://lightningfaucet.com/api/l402/joke"
NEWSLETTER = ("Daily-briefing agent needs one inspirational quote for the header of today's team newsletter. Operator budget "
              "for this task: 100 sats per call, 500 sats per day; this is the first paid call today. The endpoint is listed "
              "in the Lightning Faucet L402 registry (https://lightningfaucet.com/l402-registry/).")
TRADING = ("Trading agent needs the current BTC/USD spot price from a reliable market-data source to size an order in the next "
           "minute. Operator budget for this task: 100 sats per call.")


def say(s):
    print(s, flush=True)


def secs():
    return f"{time.time() - T0:.1f} s"


def show(d):
    say(f"3. Verdict: {str(d.verdict).upper()} in {secs()}  ->  {'ALLOWED to pay' if d.allowed else 'BLOCKED, nothing paid'}")
    if d.proof:
        say("   Proof checked offline: " + ", ".join(f"{k} {'OK' if v else 'FAIL'}" for k, v in d.proof.get("checks", {}).items()))
    if d.summary:
        say(f"   Reviewer: {d.summary}")
    if not d.allowed and not d.summary:
        say(f"   Reason: {d.reason}")


url, purpose = (JOKE, TRADING) if MODE == "mismatch" else (QUOTE, NEWSLETTER)
gate = VerdictGate(api_key=os.environ["INVINOVERITAS_KEY"], max_cost_sat=100, agent_id="l402-verdict-gate-live-demo",
                   accountable_party="operator of the agent (live demo)",
                   context="Live demo of examples/l402-verdict-gate: if allowed, this invoice WILL be paid.")
say(f"1. GET {url}")
status, h, _ = urllib_http("GET", url, {"User-Agent": "l402-verdict-gate/0.1"}, None)
ch = parse_challenge(h["www-authenticate"])
from l402_verdict_gate.bolt11 import decode as _decode  # noqa: E402
inv = _decode(ch.invoice)
say(f"   {status} Payment Required: L402 invoice for {inv.amount_msat // 1000} sats, payment_hash {inv.payment_hash[:16]}...")
say(f"2. Agent's task: {purpose.split('.')[0]}.")
say("   Asking invinoveritas for a signed verdict on the exact payment intent (endpoint, invoice, amount, payee, purpose)...")

if MODE == "mismatch":
    show(gate.check("GET", url, ch, purpose))
    sys.exit(0)

wallet = LndRestWallet(os.environ.get("LND_REST", "https://127.0.0.1:8080"), os.environ["LND_MACAROON"], os.environ.get("LND_TLS_CERT"))
try:
    st, _, body, receipt = l402_request(url, gate, wallet, purpose=purpose, max_fee_sat=5, on_decision=show)
except PaymentBlocked as e:
    say(f"STOPPED: {e.decision.reason}")
    sys.exit(0)
say(f"4. Paid over Lightning ({int(receipt['amount_msat']) // 1000} sats incl. fee); sha256(preimage) == payment_hash checked before the credential was sent.")
say(f"5. HTTP {st}: {body.decode()[:200]}")
v = verify_receipt(receipt)
say(f"6. Receipt {receipt['receipt_id'][:23]}...: {'VALID' if v['valid'] else 'INVALID'} offline against the pinned invinoveritas key")
say("   " + ", ".join(f"{k} {'OK' if ok else 'FAIL'}" for k, ok in v.get("checks", {}).items()))
os.makedirs("receipts", exist_ok=True)
path = f"receipts/receipt_{int(time.time())}.json"
json.dump(receipt, open(path, "w"), indent=1)
say(f"Done in {secs()}.")
