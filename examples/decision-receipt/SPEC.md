# Decision record v0.2

v0.2 adds one optional, additive field (`review_issuers_commitment`, below). Every v0 record and the 14 v0 vectors stay valid and
unchanged: a record without the field behaves exactly as in v0.

A record, made **before** an action, of a decision by a fast bounded-choice decider (OpenAI's Decisions
API, Jev, any classifier that picks one of N fixed answers). It says what the decider was asked, which
options it had, what it chose, and which options the deployer treats as irreversible. It also says
whether the choice may execute.

Reference implementation: `POST https://api.babyblueviper.com/decision-receipt` (invinoveritas). It implements **v0**; the v0.2
issuer policy below is in this SPEC, checker and vectors, and the service does not accept it yet. The
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
| `review_issuers_commitment` | v0.2, optional: JCS(sorted accepted_review_issuers), the review issuers the deployer accepts (BIP-340 x-only public keys, lower-case hex) |

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

4. v0.2, only when the record carries `review_issuers_commitment`: the review's `issuer_pubkey` is one of the revealed
   `accepted_review_issuers`. A review that names no issuer does not clear. A record without the field has no issuer policy, as in v0,
   and any approving review satisfies the gate.

What this condition is and is not: it pins **who may give the approving review**, as part of the deployer's committed policy, so a
review from a party the deployer never listed cannot clear the gate. It is not an independence test. Whether a listed issuer is a
party to the transaction is a different question (the evidence-record suite's n7, n13 and n30 ask it of an attestor), and this SPEC
does not decide it.

A gated record with `executable: false` is always valid: recording a refused or unreviewed decision is
the point. An ungated record may be executable. The gate is only as strict as the committed policy, so a
principal checks `gate_policy_commitment`, and in v0.2 `review_issuers_commitment`, against its own lists. A principal that requires an
issuer policy rejects a record that lacks the field: omitting it is how a record opts out.

## Check order and reject reasons

The first failure wins:
1. Any commitment does not open to the reveal: `commitment_mismatch`. In v0.2 this includes `review_issuers_commitment` when present,
   and a record that carries it without a revealed `accepted_review_issuers`.
2. The choice is not in the options: `choice_not_in_options`.
3. `gated` disagrees with the policy: `gated_flag_mismatch`.
4. For a gated, executable record:
   - no review: `executable_without_review`;
   - review over other bytes: `review_context_mismatch`;
   - review for another decision: `review_binding_mismatch`;
   - v0.2, review from an issuer outside the committed list, or naming none: `review_issuer_not_permitted`;
   - review not approving: `executable_without_approval`;
   - review already used: `review_reused`.

## Run

```sh
python3 gen_vectors.py > vectors.json                 # v0, deterministic; regenerates byte-identical
python3 check.py vectors.json                         # 14/14
python3 gen_vectors.py --v02 > vectors-v0.2.json      # the 14 v0 vectors plus p6, n10, n11, n12
python3 check.py vectors-v0.2.json                    # 18/18
```

The vectors use ASCII strings only, where RFC 8785 JCS equals compact sorted-key JSON. The invinoveritas
service's own test suite checks that the live code produces these vectors' commitments and review binding.

The four v0.2 vectors kill three broken checkers that the v0 vectors cannot: one that ignores the issuer list (n10, n12), one that
does not open `review_issuers_commitment` (n11), and one that lets a review with no issuer through (n12).
