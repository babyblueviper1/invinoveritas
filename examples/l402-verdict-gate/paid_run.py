"""One real paid run (this produced tests/fixtures/paid_run_receipt.json; it PAYS the invoice if the verdict allows it).

    INVINOVERITAS_KEY=... python3 paid_run.py https://lightningfaucet.com/api/l402/quote pay-only.macaroon receipt.json

One real paid run: live L402 challenge -> real signed verdict -> real Lightning payment -> credential -> 200 -> receipt."""
import json, os, sys, time
from l402_verdict_gate import VerdictGate, LndRestWallet, l402_request
from l402_verdict_gate.client import PaymentBlocked

URL = sys.argv[1]
PURPOSE = ("Daily-briefing agent needs one inspirational quote for the header of today's team newsletter. Operator budget "
           "for this task: 100 sats per call, 500 sats per day; this is the first paid call today. The endpoint is listed "
           "in the Lightning Faucet L402 registry (https://lightningfaucet.com/l402-registry/).")
gate = VerdictGate(api_key=os.environ["INVINOVERITAS_KEY"], max_cost_sat=100, agent_id="l402-verdict-gate-demo",
                   accountable_party="operator of the daily-briefing agent",
                   context="Live end-to-end run of examples/l402-verdict-gate: if allowed, this invoice WILL be paid.")
wallet = LndRestWallet(os.environ.get("LND_REST", "https://127.0.0.1:8080"), sys.argv[2], os.environ.get("LND_TLS_CERT"))
t0 = time.time()
try:
    st, h, b, receipt = l402_request(URL, gate, wallet, purpose=PURPOSE, max_fee_sat=5,
                                     on_decision=lambda d: print("verdict:", d.verdict, "allowed:", d.allowed, d.reason, round(time.time() - t0, 1), "s"))
except PaymentBlocked as e:
    print("BLOCKED, nothing paid:", e.decision.reason); sys.exit(2)
print("status", st, b[:300])
json.dump(receipt, open(sys.argv[3], "w"), indent=1)
print("receipt ->", sys.argv[3], "total", round(time.time() - t0, 1), "s")
