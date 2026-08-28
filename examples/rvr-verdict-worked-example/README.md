# RVR worked example: a real, signed invinoveritas /review verdict

Built for [tg:tawg:3554] (Pavlo, damon:receiptos) -- follow-through on an offer made in the
eth-magicians RVR thread (https://ethereum-magicians.org/t/recomputable-verification-receipts-rvr/29521/7)
to test our own verdict shape against RVR's six-field model on a real artifact, not in the
abstract.

## What this is

A real `/review` call (artifact_type=trade, sign=true, confidentiality_tier=full_disclosure) on a
sanitized worked example (a small mean-reversion BTC-PERP trade). The full raw artifact, verdict,
and signed proof are in `verdict_proof.json`. Independently re-verified via our own
`verify_proof` tool before this file was committed -- not just trusted from the `/review`
response (`independent_verification_before_publishing` in the json, all checks true).

## RVR six-field mapping

| RVR field | invinoveritas equivalent | Notes |
|---|---|---|
| `claimDigest` | `artifact_hash` | sha256 of the raw submitted artifact text |
| `evidenceSetDigest` | *(no exact analog)* | `context`/`concerns` are passed in but not separately hashed today -- a real, named gap, not glossed over |
| `verificationProfileDigest` | `policy_commitment` | sha256(JCS(`policy_commitment_inputs`)) -- already a real content-addressed digest over `policy_version`/`rubric_sha256`/`conformance_suite_repo`/`conformance_suite_commit` |
| `outcome` | `verdict` | `approve` / `approve_with_concerns` / `reject` |
| `reasonCode` | `issues[].category` + `.severity` | structured list, not a single closed enum |
| `resultDigest` | `decision_ref` | sha256(JCS(the full preimage object listed in `decision_ref_preimage_fields`)) -- covers artifact_hash, policy_commitment, verdict, and more in one binding |

## The REPRODUCED / VERIFIED boundary (the actual question this exchange is testing)

RVR's own two-axis model (Verification: VERIFIED/REFUTED/UNVERIFIABLE; Recomputation:
REPRODUCED/DIVERGED/CANNOT_RECOMPUTE) maps cleanly onto a real split in this artifact -- and the
split is NOT the same for every field.

**Deterministically REPRODUCED (any independent party can recompute from public data alone, zero
trust in us required):**
1. `artifact_hash` -- sha256 of the raw artifact bytes.
2. `policy_commitment` -- sha256(JCS(policy_commitment_inputs)); the rubric doc and conformance
   suite repo+commit are both public and fetchable (`conformance_suite_repo` +
   `conformance_suite_commit` in the json).
3. `decision_ref` -- sha256(JCS(the disclosed preimage object)); recomputable straight from the
   proof's own fields.
4. The Nostr event id + schnorr signature over it (and the ML-DSA-65 post-quantum companion
   signature over the same event id) -- standard NIP-01, checkable against our published
   `verifier_pubkey` with zero trust required. This is what `verify_proof` actually checks.

**Only honestly VERIFIED, not REPRODUCED (the LLM judgment call itself):**
The `verdict`/`confidence`/`issues` content is a judgment, not a deterministic procedure. A third
party can confirm the *signature* is authentic and covers this *exact* `artifact_hash` (non-
repudiable, tamper-evident) -- but cannot independently re-derive the same verdict the way they'd
recompute a hash. The proof discloses `review_model_hash`/`review_prompt_template_hash`/
`engine_generation` precisely so a re-run's divergence from a judgment change (not tampering) is
detectable -- but detectable divergence is not the same as recomputability. Re-running this exact
artifact through `/review` today might not even reproduce `approve_with_concerns` at 0.91
confidence, and that's honest, not a defect: RVR's own REPRODUCED status genuinely cannot be
claimed for this half of the artifact.

**One more honest limit, named in the proof itself (`vantage_limitation`):** `source_class:
agent_reported` means nothing external confirms this call happened, or could not have been
bypassed, before the action it would have governed. That's a real, disclosed gap between
"authentic signed record" and "proof this ran pre-action" -- closeable only with an independent
mediation-point integration, which doesn't exist yet for trade-type verdicts.

## Verify it yourself

```
pip install invinoveritas-verify   # or: npm i invinoveritas-verify
```
Recompute the Nostr event id from `signed_event`, verify the schnorr signature against
`verifier_pubkey` (`6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7`). Or POST
`signed_event` to `https://api.babyblueviper.com/verify-proof`. No trust in us required for the
deterministic half; the judgment half is exactly where RVR's REPRODUCED/CANNOT_RECOMPUTE split
earns its keep.
