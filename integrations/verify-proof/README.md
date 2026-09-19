# invinoveritas verify-proof — the portable verifier ("Aqueduct")

Verify an **invinoveritas** verdict proof **offline, on your own infrastructure, trusting no one — not
even our API, and not us.** An invinoveritas proof is a schnorr-signed Nostr event; these tools recompute
its event id (NIP-01), check the BIP-340 signature against our **published** key, and confirm it's a real
verdict — all locally. A `valid` result is something you *proved*, not something we *told* you.

> This is what "recomputable, not a score" means in your hands. A score you have to trust; a proof you
> recompute. Run the verifier; believe the math.

## Why it exists
Trust shouldn't require a phone-home. Our proofs are verifiable against a public key, so verification can
live anywhere — in your CI, your agent, your edge function — with no call to us and no secret. Every place
you run this is one more independent check on the same public record. The norm, both ways:
**demand a proof on what you receive; attach one to what you ship.**

## Artifacts
| Path | What | Deps |
|---|---|---|
| `python/` | Reference verifier + CLI. **Zero dependencies** (pure-stdlib BIP-340). | none |
| `npm/` | JS/TS verifier. | `@noble/curves` (audited) |
| `mcp/` | MCP server exposing `verify_proof` as a tool for any MCP host. | — |
| `action/` | GitHub Action — gate a workflow on a valid proof. | — |

## Quickstart (Python, zero install)
```bash
curl -s https://api.babyblueviper.com/.well-known/agent-handshake \
  | python3 -c "import sys,json; json.dump(json.load(sys.stdin)['try_it_now']['sample_proof']['event'], open('proof.json','w'))"
python3 python/verify_proof.py proof.json     # → {"valid": true, ...}, computed entirely on your machine
```

## Verify our key yourself (don't trust the constant we ship)
Each artifact pins `PUBLISHED_PUBKEY`. Re-derive it any time and confirm it matches:
```bash
curl -s https://api.babyblueviper.com/.well-known/agent-handshake | grep -o '"verifier_pubkey":"[a-f0-9]*"'
```
If a proof's `pubkey` ≠ that key, it is **not** an invinoveritas verdict — by design, no one can forge one
without our private key, and nothing here needs that key.

## Trust model
- **`valid`** ⇒ invinoveritas issued exactly this verdict (id integrity + schnorr + our key + proof shape).
- It does **not** assert freshness or that the proof was meant for *your* interaction — bind it to your
  input (artifact hash) and check recency yourself.
- Verdicts here are **byte-identical** to `POST https://api.babyblueviper.com/verify-proof`. The endpoint
  is a convenience; this is the same check without the round trip.

Public track record: https://api.babyblueviper.com/ledger
