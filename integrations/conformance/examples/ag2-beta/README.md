# AG2 Beta — external-attestation contract triple

Framework-shaped instances of the suite's `verdict_binding_failed` invariant, mapped to the
AG2 Beta governance-middleware field names (`proposed_action` / `gate_decision` /
`external_attestation` / `release_record`), per the discussion in
[ag2ai/ag2#2967](https://github.com/ag2ai/ag2/issues/2967).

The **smallest stable contract** is a triple — allow / deny-on-mismatch / deny-on-missing — that
keeps **signature validity** and **action binding** as independent verdict dimensions: *a
cryptographically valid artifact is not authority for a different action.*

| Fixture | Case | `release_record.outcome` | `reason_code` |
|---|---|---|---|
| `external_attestation_matches_intent_ref.json` | valid sig **and** `artifact_hash == intent_ref` | `released` | `attestation_bound_and_verified` |
| `external_attestation_intent_ref_mismatch.json` | valid sig but **different** bound hash | `blocked` | `attestation_intent_ref_mismatch` |
| `external_attestation_missing_where_required.json` | policy requires one, **none present** | `blocked` | `required_attestation_missing` |

The two `blocked` cases are **distinct terminal outcomes** — a binding mismatch (real but wrong-bound
evidence) is not the same fact as missing evidence, and an operator needs to tell them apart.

The rules:

```
sig valid AND external_attestation.artifact_hash == proposed_action.intent_ref  =>  released (subject to gate_decision)
            external_attestation.artifact_hash != proposed_action.intent_ref    =>  blocked  (independent of signature validity)
policy.requires_attestation AND external_attestation absent                     =>  blocked  (missing-evidence reason, != mismatch)
```

**Recompute-real**, not asserted — every case is checkable from the bytes:

- `sha256(utf8(proposed_action.canonical_input.canonical_bytes_utf8)) == proposed_action.intent_ref`
- where an `external_attestation` is present, `signed_event` is a valid NIP-01 schnorr event
  (recompute `id = sha256([0,pubkey,created_at,kind,tags,content])`, schnorr-verify `sig` against
  `pubkey`). In the matching case it binds `intent_ref` → released; in the mismatch case it is
  **equally valid** but binds a different hash → blocked. Validity ≠ bound-to-this-action.

Run the triple offline (zero-dep):

```bash
python3 check_triple.py
```

The verifier should also *derive* the evidence mode from what it can recompute rather than trust a
producer-asserted label, which is what prevents green-by-assertion.

## Portable mapping (framework-local names may differ; the invariant stays portable)

| portable role | meaning |
|---|---|
| `proposed_action.intent_ref` | frozen action / binding identity |
| `gate_decision` | pre-execution authorization record |
| `external_attestation` | independently checkable evidence input |
| `release_record` | observed executed / blocked outcome |
