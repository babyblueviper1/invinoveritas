# Decision record v0

A record, made **before** an action, of a decision by a fast bounded-choice decider (OpenAI's Decisions
API, Jev, any classifier that picks one of N fixed answers). It says what the decider was asked, which
options it had, what it chose, and which options the deployer treats as irreversible. It also says
whether the choice may execute.

Reference implementation: `POST https://api.babyblueviper.com/decision-receipt` (invinoveritas). The
record is the signed payload's public fields. The signature is a BIP-340 Nostr event that anyone checks
with the free `POST /verify-proof`, or offline. This suite covers the commitments and the gate, not the
signature.

## Commitments

Every public field is a salted commitment, `c(v) = sha256(salt + "|" + v)`, with one random salt per
record. The salt goes only to whoever holds the decision. An unsalted hash of a short question or option
list can be recovered by guessing, and it links two records of the same decision. A salted one does
neither.

| field | v |
|---|---|
| `question_commitment` | the question |
| `options_commitment` | JCS(options), in the decider's order |
| `choice_commitment` | the chosen option |
| `context_commitment` | sha256(context) as lower-case hex, where context is the input decided on |
| `gate_policy_commitment` | JCS(sorted irreversible_options), the deployer's policy |

`gated` is true iff the choice is in `irreversible_options`.

## Gate

A gated record may be `executable: true` only with an **approving review** (`approve` or
`approve_with_concerns`) that meets all three conditions:
1. The review is over the same input: `artifact_hash == sha256(context)`.
2. The review names this exact decision. `action_binding_tool_hash == "sha256:" + sha256("decision_receipt")`
   and `action_binding_args_hash == "sha256:" + sha256(JCS(args))`, where args is
   `{context_sha256, question_sha256 = sha256(question), options_sha256 = sha256(JCS(options)), choice}`.
   A review of the same input for a different choice or option set does not clear.
3. The review is single use. Within a set of records, no two executable gated records share a review
   `decision_ref`.

A gated record with `executable: false` is always valid: recording a refused or unreviewed decision is
the point. An ungated record may be executable. The gate is only as strict as the committed policy, so a
principal checks `gate_policy_commitment` against its own list.

## Check order and reject reasons

The first failure wins:
1. Any commitment does not open to the reveal: `commitment_mismatch`.
2. The choice is not in the options: `choice_not_in_options`.
3. `gated` disagrees with the policy: `gated_flag_mismatch`.
4. For a gated, executable record:
   - no review: `executable_without_review`;
   - review over other bytes: `review_context_mismatch`;
   - review for another decision: `review_binding_mismatch`;
   - review not approving: `executable_without_approval`;
   - review already used: `review_reused`.

## Run

```sh
python3 gen_vectors.py > vectors.json   # deterministic; regenerates byte-identical
python3 check.py vectors.json           # 14/14
```

The vectors use ASCII strings only, where RFC 8785 JCS equals compact sorted-key JSON. The invinoveritas
service's own test suite checks that the live code produces these vectors' commitments and review binding.
