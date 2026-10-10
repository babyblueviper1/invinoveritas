#!/usr/bin/env python3
"""Offline walkthrough, for a screen share. No network, no payments.

Part 1 replays the real recording: a live L402 challenge from lightningfaucet.com and the real signed invinoveritas
verdict over it, checked here offline. Part 2 runs the whole loop (402 -> verdict -> pay -> preimage check -> retry ->
receipt) against a fake server and a mock wallet, with a test issuer key, because only a real payment reveals a real preimage.
    python3 demo.py
"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "tests"))
from l402_verdict_gate import (MockWallet, VerdictGate, decode_invoice, l402_request, parse_challenge,  # noqa: E402
                               verify_receipt)

rec = json.load(open(os.path.join(os.path.dirname(__file__), "tests", "fixtures", "l402_quote_verdict.json")))
ev = rec["review_response"]["proof"]["event"]
va = json.loads(ev["content"])["verified_at"]
ch = parse_challenge(rec["www_authenticate"])
inv = decode_invoice(ch.invoice)
print("1. 402 from", rec["url"])
print(f"   {ch.prefix} {ch.credential_param}=..., invoice {inv.amount_msat // 1000} sats to {inv.payee_pubkey[:16]}..., "
      f"payment_hash {inv.payment_hash[:16]}..., expires in {inv.expiry}s; credential commits to the same hash: "
      f"{ch.credential_payment_hash == inv.payment_hash}")
gate = VerdictGate(max_cost_sat=100, accountable_party="operator of the daily-briefing agent", now=lambda: va + 5)
print("2. local checks:", gate.local_checks(ch, rec["url"])[1] or "pass")
d = gate.decide(rec["review_response"], rec["args"], inv)
print(f"3. verdict {d.verdict} (confidence {d.confidence}), recorded in {rec['review_latency_s']}s; offline proof checks:")
for k, v in d.proof["checks"].items():
    print(f"   {'ok  ' if v else 'FAIL'} {k}")
print("   ->", "PAY" if d.allowed else "DO NOT PAY", "-", d.reason)
for i in rec["review_response"].get("issues", []):
    if i.get("severity") in ("medium", "high", "critical"):
        print(f"   concern ({i['severity']}): {i['description'][:160]}...")
d2 = gate.decide(rec["review_response"], dict(rec["args"], amount_msat="20000"), inv)
print("   same verdict, amount changed to 20 sats ->", "PAY" if d2.allowed else "DO NOT PAY", "-", d2.reason)

print("\n4. full loop with a mock wallet (test issuer key, synthetic invoice):")
from helpers import ISSUER_PK, aperture_macaroon, make_invoice, sign_verdict  # noqa: E402
import base64  # noqa: E402
pre = hashlib.sha256(b"demo").hexdigest()
ph = hashlib.sha256(bytes.fromhex(pre)).hexdigest()
www = f'L402 macaroon="{base64.b64encode(aperture_macaroon(ph, location="pulse.example")).decode()}", invoice="{make_invoice(ph, amount="10u")}"'
url, purpose = "https://pulse.example/v1/match/fra-mar/live", "live stats for the agent's match summary"
g = VerdictGate(pubkey=ISSUER_PK, now=lambda: 1791658015)
c = parse_challenge(www)
g._post = lambda *a: (200, sign_verdict(g.bind_args("GET", url, c, purpose, decode_invoice(c.invoice)), g.tool))


def server(method, u, headers, body):
    auth = headers.get("Authorization", "")
    if auth and hashlib.sha256(bytes.fromhex(auth.rsplit(":", 1)[1])).hexdigest() == ph:
        return 200, {}, b'{"minute": 67, "score": "1-1"}'
    return 402, {"www-authenticate": www}, b""


status, _, body, receipt = l402_request(url, g, MockWallet({ph: pre}), purpose=purpose, http=server, now=lambda: 1791658020)
print("   ", status, body.decode())
print("   receipt", receipt["receipt_id"][:23] + "...", "valid:", verify_receipt(receipt, pubkey=ISSUER_PK)["valid"])
