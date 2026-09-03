# RVR worked example: a real, signed invinoveritas /review verdict

Built for [tg:tawg:3554] (Pavlo, damon:receiptos) -- follow-through on an offer made in the
eth-magicians RVR thread (https://ethereum-magicians.org/t/recomputable-verification-receipts-rvr/29521/7)
to test our own verdict shape against RVR's six-field model on a real artifact, not in the
abstract.

**CORRECTED 2026-08-28** per @pipavlo82's real, direct catch (post #10 on the same thread) after
he actually checked the committed artifact rather than taking the README's word for it: (1) the
disclosed `policy_commitment_inputs` field was NOT the literal hash preimage -- it omitted
`policy_version` and included `rubric_doc_path` (a pointer, not a hashed input); the true 4-field
preimage is now documented explicitly in `verdict_proof.json` and independently re-verified to
recompute the exact same `policy_commitment` hash. (2) The README claimed the ML-DSA-65 PQ
companion signature was "independently checkable from the committed artifact" but the committed
JSON only had the Nostr/Schnorr material -- the real `pq_pubkey` is now included (the full
signature hex is fetchable live rather than embedded, noted honestly in the json). Both fixed
before re-replying to him -- see the thread for the full exchange.

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
| `verificationProfileDigest` | `policy_commitment` | sha256(JCS({policy_version, rubric_sha256, conformance_suite_repo, conformance_suite_commit})) -- the disclosed `policy_commitment_inputs` field is metadata, not this exact preimage; see the correction note above |
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
4. The Nostr event id + schnorr signature over it -- standard NIP-01, checkable against our
   published `verifier_pubkey` with zero trust required. This is what `verify_proof` actually
   checks. A separate ML-DSA-65 post-quantum companion signature also covers the same event id --
   `pq_pubkey` is included in `verdict_proof.json`, but the full signature hex (~3.3KB) is fetched
   live via `/verify-proof` or the offline verifier rather than embedded in this file.

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

## v17 refresh (2026-09-03) -- the predicted non-reproducibility, confirmed live

Pavlo (eth-magicians RVR thread, now formalized as ERC-8404) asked for a real signed artifact
under our current policy version, since `verdict_proof.json` below is pinned to
`invinoveritas.review.v12` and the live server has since moved to
`invinoveritas.review.v17`. `verdict_proof_v17.json` is the same exact artifact text run through
`/review` again today, independently re-verified via `/verify-proof` before being committed here
(all checks `true`, including a live Bitcoin freshness-beacon check across 3 independent
explorers, `mempool`/`blockstream`/`emzy`, all `ok_match`).

**v12 -> v17, what actually changed (checked against the live code, not asserted):**
`decision_ref_preimage_fields` gained `action_binding_tool_hash`/`action_binding_args_hash`/
`action_binding_agent_id`/`action_binding_nonce` (v13-v15, optional tool-call bindings) and
`freshness_beacon_hash` (v16, closes a backdating gap). v17 itself changes no preimage field at
all -- it bumps because a beacon-present proof now enforces (a provable lie about the beacon
fails the proof, `valid=False`), where v16 only disclosed. Review criteria / rubric bytes
(`rubric_sha256`) are byte-identical all the way back to v12.

**The line 65-66 prediction above, now confirmed on a real second call, not just
argued:** the exact same artifact text that got `approve_with_concerns`/0.91 under v12 got
`reject`/0.93 under v17 today. `artifact_hash` matches byte-for-byte across both files
(`8a2f048f6d269923a91825beae44e397df0fb73cdb0a386ca6908ebb4c5fb19f`) -- same input, genuinely
different judgment. That is exactly the REPRODUCED/VERIFIED split this README already claimed in
the abstract, now demonstrated on the same real artifact rather than merely predicted.

## Verify it yourself

```
pip install invinoveritas-verify   # or: npm i invinoveritas-verify
```
Recompute the Nostr event id from `signed_event`, verify the schnorr signature against
`verifier_pubkey` (`6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7`). Or POST
`signed_event` to `https://api.babyblueviper.com/verify-proof`. No trust in us required for the
deterministic half; the judgment half is exactly where RVR's REPRODUCED/CANNOT_RECOMPUTE split
earns its keep.
