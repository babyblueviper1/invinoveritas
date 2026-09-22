# invinoveritas-verify (Python)

**Verify an [invinoveritas](https://api.babyblueviper.com) verdict proof OFFLINE — trusting no one, not even our API, and not us.** An invinoveritas proof is a schnorr-signed Nostr event; this recomputes its event id (NIP-01), checks the BIP-340 signature against our **published** key, and confirms it's a real verdict — all on your machine. A `valid` result is something you *proved*, not something we *told* you.

**Zero dependencies** — pure stdlib (`hashlib`). A verifier that shipped a sketchy crypto dependency would be self-defeating; there is nothing here to trust but ~120 readable lines, and the only input that matters is a *public* key.

```bash
pip install invinoveritas-verify
```

```python
from invinoveritas_verify import verify_proof

# `event` is the signed proof from a /review {sign:true} or /prove response.
result = verify_proof(event)
if result["valid"]:
    print("invinoveritas issued exactly this verdict —", result["checks"])
    # {'id_integrity': True, 'signature_valid': True, 'issued_by_invinoveritas': True, 'is_proof_event': True}
```

CLI:

```bash
curl -s https://api.babyblueviper.com/.well-known/agent-handshake \
  | python -c "import sys,json; json.dump(json.load(sys.stdin)['try_it_now']['sample_proof']['event'], open('proof.json','w'))"
python -m invinoveritas_verify proof.json     # → {"valid": true, ...}, computed entirely on your machine
```

## Recompute the WHOLE ledger (not just one proof)

One command pulls our public verdict ledger and recomputes **every** entry — fetching each raw signed
verdict straight from public Nostr relays (not from us), recomputing the NIP-01 event id from those
bytes, and checking the BIP-340 signature against our published key:

```bash
invinoveritas-recompute-ledger            # or: python recompute_ledger.py
```

```
RECOMPUTED: 23/32 verdicts schnorr-verified from relay bytes against 6786…fbb7.
  · 9 raw events rotated off relays (NIP-33); 9 carry a CONFIRMED Bitcoin-PoW anchor — ots verify.
You trusted no one: the bytes came from public relays, the math ran here.
```

Still zero dependencies — the relay fetch is a minimal stdlib WebSocket client. Verdict events are
NIP-33 parameterized-replaceable, so an older verdict's raw event may have rotated off relays; those
can't be schnorr-recomputed anymore, but each one also carries a Bitcoin-PoW
[OpenTimestamps](https://opentimestamps.org) anchor on its event id, recomputable relay-independently:
`ots verify -d <event_id> <event_id>.ots`.

**v0.4.0 — hash-chain check.** Signature verification alone proves each entry existed and wasn't
tampered; it doesn't prove there's only *one* history (a server could show different entries to
different requesters). Entries from #40 onward hash-link to the previous entry
(`head_hash = sha256(content_hash + "|" + prev_head_hash)`), so this tool now also fetches each
chained entry's full record, independently recomputes `content_hash` and `head_hash` from those
bytes, and checks `prev_head_hash` against the *actual* predecessor's recomputed head — not the
server's claim. A tampered record or a spliced-in alternate history breaks the chain visibly.
Entries #1-39 predate this and are unaffected (still signature-only, as before).

## Compliance bundle — oversight evidence a regulator can recompute

Running an agent you're on the hook for? Every `/review {"sign": true}` returns a signed verdict
proof — keep them. This packages the ones that gated your agent's actions into a single,
self-verifying **compliance bundle** an auditor or counterparty re-checks without trusting your logs
OR our attestation:

```bash
# assemble (runs on YOUR proofs, on YOUR machine — we never store your action history)
invinoveritas-compliance-export ./my_proofs --subject "AcmeBot prod" --out bundle.json

# an auditor verifies it — re-checks every signature + that no displayed field was altered
invinoveritas-compliance-export --verify bundle.json
# → PASS — every verdict is an authentic invinoveritas judgment, bundle untampered.
```

Two independent tamper checks: each entry's BIP-340 signature is re-verified against our published
key (the cryptographic truth), and every displayed field is cross-checked against the signed content,
so the bundle can't misrepresent what we actually issued. Still zero dependencies. Self-custody by
design — "trust no one" includes not trusting us with a database of what your agent did.

## Verify our key yourself

The package pins `PUBLISHED_PUBKEY`. Re-derive it any time and confirm it matches:

```bash
curl -s https://api.babyblueviper.com/.well-known/agent-handshake | grep -o '"verifier_pubkey":"[a-f0-9]*"'
```

If a proof's `pubkey` ≠ that key, it is **not** an invinoveritas verdict.

## Trust model

- `valid` ⇒ invinoveritas issued exactly this verdict (id integrity + schnorr + our key + proof shape).
- It does **not** assert freshness or that the proof was meant for *your* interaction — bind it to your input and check recency yourself.
- Verdicts are **byte-identical** to `POST https://api.babyblueviper.com/verify-proof`. The endpoint is a convenience; this is the same check without the round trip — "recomputable, not a score."

## Related

- **`invinoveritas`** (PyPI) — the full Python SDK, incl. the *online* verify-before-pay client (`preflight_verify`, `verify_proof`) and now `verify_proof_local` (the same offline check).
- **`invinoveritas-verify`** (npm) — the JavaScript/TypeScript twin.

**Known cross-language divergence (disclosed, low impact):** on raw JSON with an integral-valued float `created_at` literal (e.g. `1781569676.0`), this package correctly rejects it (Python's `json.loads` keeps the float type, out of the strict-typing scope). The npm twin's `JSON.parse` collapses that literal into a plain integer before its verifier ever sees it, so it currently verifies such an event — see `invinoveritas-verify`'s own README for the same disclosure. The hashed bytes are identical either way, so nothing forged verifies in either language; this is a verdict-parity gap on an edge case, not a security issue.

Public track record: https://api.babyblueviper.com/ledger
