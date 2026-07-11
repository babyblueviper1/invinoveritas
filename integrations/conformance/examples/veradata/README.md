# VeraData — AAT hash-chain conformance fixture

A recompute-real fixture for VeraData's Agent Attestation Trail (AAT) — a per-query hash chain
(`query_hash` → `event_hash` → `chain_hash`) attached to their `/sanctions` responses, per the
schema provided in [x402-foundation/x402#2749](https://github.com/x402-foundation/x402/issues/2749)
(comment from `teodorofodocrispin-cmyk`, 2026-07-01T15:51:49Z).

## What this checks

Three independent recomputes over one fixture, plus a boundary check on what the verdict can claim:

- `genesis = SHA256("veradata-aat-genesis-v1")`
- `query_hash = SHA256(normalize(name) + "|" + country + "|" + sorted(lists_checked))`
- `event_hash = SHA256("sha256:" + query_hash + "|" + risk_score:.4f + "|" + checked_at + "|" + policy_ref)`
- `chain_hash = SHA256("sha256:" + prev_hash + "|" + "sha256:" + event_hash)`

**The load-bearing detail a naive recompute gets wrong:** every hash used as an input to the *next*
hash carries its own literal `sha256:` prefix — this wasn't stated explicitly in the source comment
and was found by independent recompute (bare-hex inputs produce a different `event_hash`/`chain_hash`
and fail to match the claimed values). Documented in `recompute_construction.prefix_convention` in
the fixture so a third recomputer doesn't have to rediscover it.

**Overclaim boundary:** `risk_score: 0.0` / `risk_category: CLEAN` is *not found in `lists_checked` at
`checked_at`*, never *entity is globally clean*. The checker asserts `lists_checked` and `matches`
travel alongside the verdict rather than the category standing alone — the same "occurrence, not
absence" discipline this suite already applies to `/review`'s `source_class`/`vantage_limitation`
(shipped the same day this fixture was built, on the parallel `GenAI-LLM-Top10#41` thread).

## What this does NOT check

`chain_stored: true` proves the entry exists in VeraData's own DB, not that it was written at
`checked_at` — that's a self-stored-anchor limitation both sides agree is real (see the source
thread). Closing it needs an external, non-repudiable time anchor (e.g. Bitcoin OTS) on the
`chain_hash`, which is a separate, not-yet-built integration — this fixture only certifies the hash
chain's internal consistency, honestly, not temporal precedence.

Run offline (zero-dep):

```bash
python3 check_chain.py
```
