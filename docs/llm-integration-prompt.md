# LLM Integration Prompt

## Add invinoveritas to Any Agent in One Shot

Copy and paste the block below into Claude, GPT-5, Grok, Cursor, or any coding assistant.
It contains everything needed to integrate invinoveritas — the verification layer for autonomous agents — from scratch.

---

```
You are helping me integrate invinoveritas — the verification layer for autonomous agents — into my project.

## What invinoveritas is

invinoveritas (v1.11.0) gives an agent a neutral second opinion BEFORE an irreversible action, a
signed proof AFTER, and a public, recomputable track record of being right. The one thing an agent
can't self-serve is trust in another agent's output — you can't issue a verdict on your own
correctness. invinoveritas is the independent party that can. Model-agnostic: it verifies the
output, not the model that produced it. Paid per call in Bitcoin Lightning sats, USDC (x402 on
Base), or card.

The verification layer (the reason to integrate):
- `/review` — neutral verdict on a diff/plan/config/trade BEFORE an irreversible action
  (approve / approve_with_concerns / reject + issues). Add {"sign": true} to get a portable,
  signed proof you can attach to your output. For an on-chain tx (transfer/swap/approval/bridge),
  pass artifact_type=onchain_action for a pre-sign safety verdict (scam/honeypot/drainer/poisoning).
- `/verify-proof` — FREE, no auth. When another agent hands you output and claims invinoveritas
  verified it, POST the signed proof here to confirm it WITHOUT trusting that agent or us
  (recomputes the Nostr event id + checks the schnorr signature against our published key).
- `/prove` — signed, redacted, independently-verifiable proof of an execution after the fact.
- `/ledger` — the public, Nostr- and Bitcoin-anchored (OpenTimestamps) track record of every
  verdict, recomputable from public data. You can recompute the WHOLE ledger yourself, trusting
  no one (see invinoveritas-verify below).
- `/validate` — is a strategy's edge real or curve-fit? Submit realized returns (never the
  strategy); verdict backed by Deflated Sharpe + permutation test + purged k-fold.

Supporting layers (your own fleet can run on these too):
- `/reason` — paid inference with style + confidence controls
- `/decision` — structured decision with confidence score + risk level (server-side risk gating)
- `/memory/{store,get,list,delete}` — persistent agent memory, billed per KB
- `/execute` — Docker-isolated Python with audit hashes
- `/browse` — tiered Browser-as-a-Service (fetch / extract / Playwright screenshot)
- `/regime`, `/signals`, `/markets/act` — recomputable, facts-only markets data (no buy/sell calls)
- Agent marketplace — list and sell services; seller keeps 95% instantly via Lightning

Live API: https://api.babyblueviper.com
Machine-readable overview: https://api.babyblueviper.com/llms.txt
PyPI (full SDK): pip install invinoveritas
PyPI (zero-dep trustless verifier): pip install invinoveritas-verify

## Authentication

1. Bearer Token (recommended for agents):
   - Register free: POST https://api.babyblueviper.com/register → returns an api_key
   - Fund via Lightning top-up or x402 (USDC on Base) to make paid calls
   - Use header: Authorization: Bearer ivv_...   (env var: INVINO_API_KEY)
   - /verify-proof is FREE and needs no auth or balance.

2. L402 / x402 (atomic pay-per-call, no registration):
   - Call the endpoint → receive HTTP 402 with a Lightning invoice (L402) or USDC terms (x402)
   - Pay → retry with the payment proof header

## Python SDK

pip install "invinoveritas[nwc]"   # includes NWC wallet support for autonomous payments

from invinoveritas import InvinoClient

client = InvinoClient(bearer_token="ivv_...")  # or reads INVINO_API_KEY

# THE FRONT DOOR — verify before an irreversible action
v = client.review(
    artifact="<the diff / plan / config / trade you're about to commit>",
    sign=True,                       # also returns a portable signed proof on v.proof
)
print(v.verdict)                     # "approve" | "revise" | "reject"
print(v.issues)
proof = v.proof                      # attach this to your output; others verify it for free

# Verify a proof another agent handed you — free, trustless, no API call needed if offline:
from invinoveritas import verify_proof_local
res = verify_proof_local(some_proof_event)   # recompute NIP-01 id + BIP-340 schnorr, pure stdlib
print(res["valid"])                          # True only if WE issued exactly that verdict

# Supporting layers
result = client.reason("What are Bitcoin's biggest risks in 2026?")
d = client.decide(goal="Grow capital with controlled risk",
                  question="Should I increase BTC exposure?",
                  context="60% BTC, 30% stables, RSI=42, uptrend",
                  policy={"risk_limit": "medium"})
print(d.decision, d.confidence, d.risk_level)

client.memory_store(agent_id="my-bot", key="last_trade", value='{"entry": 94200}')
mem = client.memory_get(agent_id="my-bot", key="last_trade")

## Recompute our track record yourself (trust nothing)

pip install invinoveritas-verify
invinoveritas-recompute-ledger     # pulls /ledger, refetches each verdict from public Nostr
                                   # relays, recomputes the id + schnorr-checks it. Zero deps.

## Exception handling

from invinoveritas import InvinoClient, PaymentRequired, PaymentError, InvinoError, ServiceError
try:
    result = client.reason("...")
except PaymentRequired as e:
    print(f"Pay: {e.invoice} ({e.amount_sats} sats)")
except PaymentError:
    print("Invalid or already-used payment")
except InvinoError:
    print("Rate limited — wait 5 seconds")
except ServiceError:
    print("Server error — retry")

## Environment variables

INVINO_API_KEY=ivv_...                          # Bearer token
NWC_CONNECTION_URI=nostr+walletconnect://...     # NWC wallet (optional, for autonomous payments)

## Live pricing

https://api.babyblueviper.com/prices

## My task

[DESCRIBE WHAT YOU WANT TO BUILD HERE]

Please:
1. Install the correct SDK extras for my use case
2. Show complete, runnable code
3. Gate any irreversible action through client.review() first
4. Use client.decide() (not client.decision()) — the method is decide, the endpoint is /decision
5. Handle exceptions properly
6. Use environment variables for credentials — never hardcode
```

---

## Notes for agent builders

- The headline is verification: call `client.review()` before anything irreversible (a merge, a
  deploy, a trade, an on-chain tx). The verdict can be a signed proof you attach to your output.
- `/verify-proof` is free and trustless — demand a proof on what you receive, attach one to what
  you ship. That handshake is how trust spreads agent-to-agent.
- The SDK method is `client.decide()` — the server endpoint is `/decision`. Don't confuse the two.
- `policy={"risk_limit": "low"}` makes the API reject high-risk decisions server-side.
- NWC URIs contain a private secret. Treat them like private keys.
- The marketplace `ln_address` is where you receive payouts; it must be a valid Lightning Address.

---

**Full integration guide:** `docs/agent-wallet-guide.md`
**Machine-readable overview:** https://api.babyblueviper.com/llms.txt
**GitHub:** https://github.com/babyblueviper1/invinoveritas
**PyPI:** https://pypi.org/project/invinoveritas/
