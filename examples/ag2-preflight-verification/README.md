# AG2 pre-flight verification — worked example

A runnable composition of [ag2ai/ag2#3156](https://github.com/ag2ai/ag2/issues/3156)
(safal207, 2026-08-14) against the invinoveritas production `/review` +
`/verify-proof` mechanism. This is an example in *this* repo, not a PR against
`ag2ai/ag2`.

The issue splits a slow, once-per-logical-operation judgment (human approval,
risk model, independent verifier) from a fast deterministic per-tool-call gate
such as TealTiger ([ag2ai/ag2#3128](https://github.com/ag2ai/ag2/issues/3128)).
Core invariant:

```text
preflight_verdict.intent_ref == proposed_action.intent_ref
```

A validly-signed verdict that binds a *different* `intent_ref` must not
authorize execution. Signature validity and action binding are independent
dimensions — the same discipline as the AG2 Beta external-attestation triple
in `integrations/conformance/examples/ag2-beta/`.

```text
logical operation / plan
        ↓
freeze canonical intent          ← sha256(JCS(canonical_arguments))
        ↓
pre-flight verifier(s)           ← POST /review(sign=true)
        ↓
intent-bound verdict + evidence  ← decision_ref + schnorr event
        ↓
fast deterministic governance    ← TealTiger (not implemented here)
        ↓
tool execution
```

## Run

From the repo root:

```bash
venv/bin/python -m py_compile \
  examples/ag2-preflight-verification/preflight_contract.py \
  examples/ag2-preflight-verification/preflight_verifier.py \
  examples/ag2-preflight-verification/test_preflight.py

# hyphen in the directory name is not a valid Python package; run the file:
venv/bin/python examples/ag2-preflight-verification/test_preflight.py -v
```

Live `/review` (optional; needs `OPERATOR_FULL_API_KEY` in `.env` or the
environment):

```bash
venv/bin/python examples/ag2-preflight-verification/preflight_verifier.py
```

`/verify-proof` is free and no-auth. `/review` is a paid call.

## Files

| file | what |
|---|---|
| `preflight_contract.py` | safal207's dataclasses + `PreflightVerifier` Protocol, copied from the issue body |
| `preflight_verifier.py` | adapter + join/middleware that compose against production `/review` and `verify_proof_event` |
| `test_preflight.py` | the six failure-semantics cases, plus a live `/review` test when a key is present |

## Field mapping

| #3156 field | invinoveritas production field | how the adapter joins them |
|---|---|---|
| `ProposedAction.canonical_arguments` | `/review` `artifact` (string) | adapter JCS-canonicalizes the dict, then submits **that exact string** as `artifact` |
| `ProposedAction.intent_ref` | `proof_payload.artifact_hash` | both are `sha256` of those JCS bytes. Derived here; a producer-asserted `intent_ref` that does not recompute is rejected (`intent_ref_recompute_failed`) |
| `PreflightVerdict.intent_ref` | `proof_payload.artifact_hash` | copied from the *derived* hash after `verify_proof_event` confirms `artifact_hash_matches` |
| verdict-binds-to-intent invariant | `decision_ref` | `decision_ref = sha256(JCS({artifact_hash, artifact_type, policy_version, verdict, source_class, …}))` — a signed binding of a verdict to a specific `artifact_hash`. Recomputed by `compute_decision_ref` / `verify_proof_event` |
| `PreflightVerdict.verdict_id` | Nostr `event.id` | the kind-30078 event id of the signed `/review` proof |
| `PreflightVerdict.decision` `allow` / `deny` / `refer` | `/review` `verdict` `approve` / `reject` / `approve_with_concerns` | `approve→allow`, `reject→deny`, `approve_with_concerns→refer`. Residual concern is not collapsed to a binary — same tri-state discipline as the rest of this platform |
| `PreflightVerdict.verifier_id` | `proof_payload.verifier_pubkey` (fallback: `"invinoveritas"`) | published schnorr key that signed the event |
| `PreflightVerdict.authority_basis` | `mediator_evidence.authority_basis`, else `source_class={source_class}` | for a typical unregistered caller this is `source_class=agent_reported`. A registered independent mediator carries the decomposed evidence safal207 asked for on crewAI#4877 |
| `PreflightVerdict.evidence_refs` | `decision_ref`, `nostr:{event.id}`, `artifact_hash:{…}` | pointers a later audit record can retain |
| `PreflightVerdict.issued_at` | `proof_payload.verified_at` | unix seconds → UTC datetime |
| `PreflightVerdict.expires_at` | *(none)* | production proofs have `verified_at` + `/verify-proof`'s `age_seconds`; they do **not** carry an issuer-declared expiry. The gate honors `expires_at` when present; our issuer always returns `None` |
| `PreflightVerdict.revalidate_if` | *(none)* | production proofs do not declare revalidation conditions. The gate honors the field when another verifier sets it; unknown names fail closed. Our issuer always returns `[]` |
| `ProposedAction.logical_operation_id` | *(none)* | see honest gaps |
| `ProposedAction.execution_id` | *(none)* | see honest gaps |
| `ProposedAction.tool_name` | `/review` `artifact_type` (heuristic) | `erc20_*` / `swap` / `approve` / … → `onchain_action`; otherwise `plan` |

Canonicalization is the production JCS already used by `compute_decision_ref` and `sign_payload` in `services/proof_signing.py`:

```python
json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

One honesty note on `artifact_hash` itself: production hashes the **raw submitted artifact string**. It does not re-canonicalize structured JSON. The adapter canonicalizes *before* submit so `artifact_hash == intent_ref`. A caller who POSTed non-canonical JSON to `/review` would get a different `artifact_hash`; that is why derivation happens on this side of the seam.

## Tests

| case (from #3156) | what the test actually checks | reason_code |
|---|---|---|
| 1 matching evidence | real signed proof (`build_verdict_proof` / live `/review`); `artifact_hash` recomputes to `intent_ref`; `decision_ref` recomputes; join is `eligible` | `intent_bound_and_verified` |
| 2 mismatched evidence | the **same** valid schnorr event presented against a different amount; signature still valid; binding fails; join is `blocked` | `intent_ref_mismatch` |
| 3 missing required evidence | no verdict at all; distinct reason from mismatch | `required_evidence_missing` |
| 4 expired / stale | `expires_at` in the past (his field; we do not emit it) → blocked | `verdict_expired` |
| 5 retry / re-drive | same `logical_operation_id`, new `execution_id`, unchanged intent → cached verdict reused; changed arguments → mismatch | reuse via example-gate cache |
| 6 verifier timeout | hung verifier; `on_timeout="allow"` is refused at construction | `verifier_timeout` |

Matching means the *join* held — eligible to proceed to deterministic governance — not that the tool may execute. An unlimited-allowance artifact typically comes back `reject`/`deny`; `may_execute` is then False even though binding matched.

## Honest gaps

Confirmed by searching `services/proof_signing.py` and `routes/inference.py`: neither `logical_operation_id` / `execution_id` nor `revalidate_if` exists in production today.

### 1. `logical_operation_id` vs `execution_id`

Production treats each submitted artifact as independent. `artifact_hash` is a content hash of the judged bytes. If the **same** artifact string is resubmitted, the **same** `decision_ref` recomputes — a retry with identical canonical content is naturally idempotent at the hash layer. There is no field that says "this is attempt 2 of operation X" as opposed to "this is a wholly separate new operation with the same bytes."

Retry reuse in this example is implemented in `PreflightVerificationMiddleware._cache`, keyed by `(logical_operation_id, derived_intent_ref)`. That cache is **not** a production `/review` feature. Closing the gap for real would mean either:

- carrying `logical_operation_id` as a signed, non-binding audit annotation on the proof (does not change `decision_ref`, documents the attempt graph), or
- binding it into `decision_ref` (a policy-version bump; a retry would then be a *different* decision even when the intent bytes are identical — probably wrong).

The first is the better fit. Not built here; this is an example, not a production API change.

### 2. `revalidate_if`

Production proofs carry `verified_at`. `/verify-proof` surfaces `age_seconds` and tells the *caller* to decide freshness. There is no issuer-declared list of conditions under which a still-unexpired verdict must be re-checked (`market_moved`, `policy_rotated`, `new_execution_id`, …).

The example gate honors `revalidate_if` when a verdict carries it, and **fails closed** on names it cannot evaluate (so an unknown condition cannot be silently ignored). Our issuer always returns `[]` rather than pretending we have conditions we do not.

`expires_at` is the same class of gap: we can consume it, we do not emit it. Closest production signal is `age_seconds`.

## What this is not

- Not a PR against `ag2ai/ag2`. Whether AG2 adopts the seam is their call; safal207 offered a conformance triple if the direction fits.
- Not a new production endpoint. `/review` and `/verify-proof` are unchanged.
- Not TealTiger. The fast deterministic per-call gate stays outside this example, as the issue asked.
