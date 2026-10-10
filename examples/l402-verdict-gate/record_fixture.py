#!/usr/bin/env python3
"""How tests/fixtures/l402_quote_verdict.json was recorded (one paid /review, ~1,000 sats). Nothing is paid to the L402 server.

    INVINOVERITAS_KEY=... python3 record_fixture.py https://lightningfaucet.com/api/l402/quote out.json
"""
import json
import os
import sys
import time

from l402_verdict_gate.challenge import parse_challenge
from l402_verdict_gate.client import urllib_http
from l402_verdict_gate.gate import VerdictGate

PURPOSE = ("Daily-briefing agent needs one inspirational quote for the header of today's team newsletter. Operator budget "
           "for this task: 100 sats per call, 500 sats per day; this is the first paid call today. The endpoint is listed "
           "in the Lightning Faucet L402 registry (https://lightningfaucet.com/l402-registry/).")


def main(url, out, base_url=os.environ.get("INVINOVERITAS_URL", "https://api.babyblueviper.com")):
    status, h, b = urllib_http("GET", url, {"User-Agent": "l402-verdict-gate/0.1"}, None)
    assert status == 402, status
    ch = parse_challenge(h["www-authenticate"])
    gate = VerdictGate(api_key=os.environ["INVINOVERITAS_KEY"], base_url=base_url, max_cost_sat=100,
                       agent_id="l402-verdict-gate-demo", accountable_party="operator of the daily-briefing agent",
                       context="Recorded test fixture for examples/l402-verdict-gate. Evaluate it as a real payment decision.")
    t0 = time.time()
    raw = {}
    gate._post = (lambda f: (lambda *a: raw.setdefault("r", f(*a))))(gate._post)
    d = gate.check("GET", url, ch, PURPOSE)
    rec = {"_source": f"real L402 challenge from {url} captured {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t0))}; real "
                      "signed invinoveritas verdict over it. The invoice was NOT paid.",
           "url": url, "method": "GET", "purpose": PURPOSE, "www_authenticate": h["www-authenticate"],
           "challenge_body": json.loads(b), "tool": "l402_lightning_payment", "args": d.args,
           "review_latency_s": round(time.time() - t0, 1), "review_response": raw.get("r", [None, None])[1],
           "gate_decision": {"allowed": d.allowed, "reason": d.reason, "verdict": d.verdict}}
    json.dump(rec, open(out, "w"), indent=1)
    print(json.dumps(rec["gate_decision"]), rec["review_latency_s"], "s")


if __name__ == "__main__":
    main(*sys.argv[1:3])
