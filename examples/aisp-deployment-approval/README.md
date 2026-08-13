# AISP deployment-approval evidence profile — worked example

Answers [google/agents-cli#48](https://github.com/google/agents-cli/issues/48)'s request for a
real, cross-recomputable example of a skill-specific structured human-approval-response profile
riding inside `sys.io.confirm`.

Run it directly:

```bash
pip install coincurve
python3 deployment_approval_example.py
```

Demonstrates, all real and executed (not asserted):

1. **`compute_plan_digest()`** — a resolved deployment plan's load-bearing fields (deployment
   target, region, service, revision, etc.) get JCS-canonicalized and sha256'd. Presentational
   fields (comments) never enter the digest.
2. **`build_approval_response()`** — a human-approval envelope matching the exact shape from the
   issue thread (`decision` / `approver` / `approved_scope` / `plan_sha256` / `key_id` /
   `expires_at`), signed with a real BIP-340 schnorr signature (same primitive as Nostr/Bitcoin
   Taproot — `pip install coincurve`, no custom crypto).
3. **`verify_approval()`** — deterministic re-verification: recomputes the plan digest, checks
   expiry, verifies the signature. Returns a structured per-check result, never a bare boolean.
4. **A tamper test that must fail** — changes one load-bearing field (`region`) after signing and
   confirms verification correctly rejects it, naming the exact reason
   (`plan_digest_matches: false`). A verifier with no failing case is a stamp, not a check.
5. **A presentational-only edit that must NOT invalidate approval** — editing `comment` after
   signing still verifies clean, since it was never part of the signed digest.
