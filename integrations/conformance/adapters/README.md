# Live-endpoint adapters

The verifier in the parent directory checks portable static fixtures. This runs the same three
invariants — `canonical_envelope`, `admission_invariant`, `anchoring_invariant` — against a **live
governance endpoint**, so an implementer can point the suite at a running service and see where the
invariants hold and where the gaps are.

```bash
python3 adapters/live_check.py adapters/safeagent.mapping.json      # live, BIP-340 over the hash
python3 adapters/live_check.py adapters/invinoveritas.mapping.json  # NIP-01 Nostr-event scheme (sample)
```

Zero third-party deps — the crypto is the vendored BIP-340 / NIP-01 core (`../_bip340_nostr.py`).

## How it works

It's **mapping-driven**: a small JSON says how to obtain the governance block and where each field
lives. The verifier is agnostic to the signature scheme — it normalizes per `sig_scheme`:

| `sig_scheme` | check |
|---|---|
| `bip340-hash` / `bip340-schnorr` | BIP-340 schnorr directly over the 32-byte envelope hash |
| `nostr-event` | recompute the NIP-01 event id, verify schnorr over it |
| `ed25519-jcs` | Ed25519 over canonical bytes — verified if an ed25519 lib (PyNaCl) is present, else `unverified_here` |

A mapping fetches live (`fetch`) or reads a saved response (`response_file`). For endpoints that
deduplicate identical claims, put the literal `__NONCE__` anywhere in the request body and the runner
substitutes a unique token per run.

```json
{
  "name": "your-endpoint",
  "fetch": { "method": "POST", "url": "https://…/claim", "body": { "scope": "… __NONCE__" }, "governance_path": ["governance"] },
  "fields": { "envelope_hash": "envelope_hash", "pubkey": "verifier_pubkey", "signature": "signature", "sig_scheme": "sig_scheme", "anchor_endpoint": "anchor_endpoint" },
  "trust_policy": { "independent_verifier_pubkeys": ["<your published governance pubkey>"] }
}
```

## What the result states mean

- `pass` — the invariant holds against the live response.
- `fail` — a specific invariant is broken (with the same negative-case codes as the fixtures).
- `pending` — the anchor is submitted but not yet Bitcoin-confirmed, so "ordered before the outcome"
  is not yet assertable (distinguish `submitted` vs `confirmed` in your `/anchor` response).
- `not_provided` — the endpoint didn't expose enough to run this check (e.g. the raw canonical claim
  for `canonical_envelope`). Exposing it enables the recompute.

## Notes per invariant

- **canonical_envelope** recomputes `SHA-256(JCS(claim))` only if the endpoint returns the raw claim.
  If it returns only the hash, the binding is *asserted*, not recomputed — surface the canonical claim
  to close this.
- **admission_invariant** = a valid signature over the envelope hash by a key in your
  `independent_verifier_pubkeys` that isn't the actor's. Publishing the governance pubkey (e.g. at
  `/.well-known/` or `/governance/pubkey`) is what makes "independent identity" checkable.
- **anchoring_invariant** = the anchor's accepted point (the Bitcoin block) provably precedes the
  terminal outcome. A background OTS submission is `pending` until it confirms.
