# Decision record v0.4

v0.2 adds one optional, additive field (`review_issuers_commitment`, below). Every v0 record and the 14 v0 vectors stay valid and
unchanged: a record without the field behaves exactly as in v0.

v0.3 adds one set-level rule and no field: within a revealed set, one decision has one choice (`conflicting_choice`, below). It also
states what a record does **not** guarantee about uniqueness. Every v0 and v0.2 vector keeps its verdict.

v0.4 adds decider-scoped slots: optional fields by which the decider itself signs one claim per `request_id` with its own key, so
uniqueness binds the decider key instead of the paying account (`slot_scope`, below). A record without `slot_scope` behaves exactly
as in v0.3, and every earlier vector keeps its verdict.

A record, made **before** an action, of a decision by a fast bounded-choice decider (OpenAI's Decisions
API, Jev, any classifier that picks one of N fixed answers). It says what the decider was asked, which
options it had, what it chose, and which options the deployer treats as irreversible. It also says
whether the choice may execute.

Reference implementation: `POST https://api.babyblueviper.com/decision-receipt` (invinoveritas). It implements **v0**, account-scoped
slots, and since 2026-10-10 the v0.4 decider-scoped slots and the daily slot log. The v0.2 issuer
policy is in this SPEC, checker and vectors, and the service does not accept it yet. The
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

5. v0.3, for every record in a set, gated or not: no two records in one revealed set have the same `context_sha256`, question and
   options with different choices. Two such records are two answers to one decision, whatever their salts.

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
4. v0.4, a record with `slot_scope: "decider"`:
   - `decider_pubkey`, `request_slot`, `decider_claim` or `decider_sig` missing or malformed: `decider_binding_missing`;
   - `request_slot` is not `sha256("invinoveritas.decision_receipt.slot.decider.v1|" + decider_pubkey + "|" + request_id)` for the
     revealed `request_id`: `slot_mismatch`;
   - `decider_claim` is not exactly `{schema: "invinoveritas.decision_claim.v1", decider_pubkey, request_slot, question_commitment,
     options_commitment, choice_commitment, context_commitment, gate_policy_commitment, claimed_at}` with this record's values and an
     integer `claimed_at`: `claim_mismatch`;
   - `decider_sig` is not a valid BIP-340 signature by `decider_pubkey` over `sha256(JCS(decider_claim))`: `decider_sig_invalid`.
   Any other `slot_scope` than `"decider"` or `"account"`: `slot_scope_unknown`. An account-scoped record has nothing more to check
   offline (its slot is an issuer HMAC).
5. v0.4: two decider-scoped records in a set with the same `decider_pubkey` and `request_slot` and different `decider_claim`:
   `decider_equivocation`. This fires on two claims with the **same** choice too: the rule is one signed claim per `request_id`.
6. v0.3: the record has the same `context_sha256`, question and options as an earlier record in the set, with a different choice:
   `conflicting_choice`.
7. For a gated, executable record:
   - no review: `executable_without_review`;
   - review over other bytes: `review_context_mismatch`;
   - review for another decision: `review_binding_mismatch`;
   - v0.2, review from an issuer outside the committed list, or naming none: `review_issuer_not_permitted`;
   - review not approving: `executable_without_approval`;
   - review already used: `review_reused`.

## Uniqueness: what a record does not show

Found by Toshikatsu Oga (HORIZON SHIELD / NENRIN), 2026-10-10. Every public field is salted with a fresh salt, so two records for
the same tool call, one `approve` and one `deny`, share no public field. A holder can keep both and reveal whichever one helps.
Vectors p7, p8 and n13 are that case, and his own probe is kept unmodified at `probes/two_receipt_probe.py`.

- **What `conflicting_choice` closes:** a revealed set that contains both records rejects.
- **What it does not close:** a holder who reveals only one record. Nothing a checker can compute from the record alone shows that
  it was the only record issued for that decision. The issuer's request slot, below, does.
### Account-scoped slots (`slot_scope: "account"`, live since 2026-10-10)

- **The issuer (`POST /decision-receipt`): one receipt per request slot.** When a request carries
  `decider.request_id` and is paid with an API key, the service computes a slot for (holder, `request_id`) and claims it
  atomically before charging. A second request for a taken slot, with the same or a different choice, is refused with 409 and is
  not charged. The receipt carries the slot unsalted as `request_slot`, the one public field two receipts for that request would
  share. `GET /decision-receipt/slot/{request_slot}` (free, no auth) returns the receipt that holds it:
  `{"slot", "taken", "event_ids"}`. A disputer holding one receipt checks that `event_ids` is exactly that receipt's event id.
- **The slot** is HMAC-SHA256 under an issuer key over `invinoveritas.decision_receipt.slot.v1|holder|request_id`. It links nothing
  across request ids or holders, and only the issuer can compute it, so the guarantee rests on the issuer's record, published at the
  slot endpoint and signed into each receipt.
- **Limits:**
  - The slot binds only the `request_id` the holder declares. A holder can ask twice under two request ids. A relying party must
    require that `request_id` is the decider's own id for the call (for example the decider API's response id) and check it
    against the decider's log.
  - No `request_id`, no slot: the receipt has no `request_slot` and makes no uniqueness claim. The same holds for x402-paid
    requests, which carry no holder key. A relying party that needs uniqueness rejects a receipt without `request_slot`.
  - Receipts issued before 2026-10-10 have no slot.
  - The slot says one receipt was issued for that request id. It does not say the decider chose what the receipt records; the
    decision stays caller-reported.
  - **It binds the paying account, not the decider.** Accounts are free, so a holder with two accounts gets two slots for one
    `request_id`, each with one receipt, and a relying party cannot see which account paid. Vectors p12 and p13 are that case (Oga's
    two-account case): an approve receipt from account A and a deny receipt from account B, each accepted alone, with different
    slots that nothing public links. Use decider-scoped slots when this matters.

### Decider-scoped slots (`slot_scope: "decider"`, v0.4, live since 2026-10-10)

The decider (the runtime or agent that made the decision) holds its own BIP-340 key and signs the decision itself:

1. It picks a random 32-byte `salt` and computes the five commitments above.
2. It signs `decider_claim = {schema: "invinoveritas.decision_claim.v1", decider_pubkey, request_slot, question_commitment,
   options_commitment, choice_commitment, context_commitment, gate_policy_commitment, claimed_at}`, with
   `request_slot = sha256("invinoveritas.decision_receipt.slot.decider.v1|" + decider_pubkey + "|" + request_id)` and
   `claimed_at` a unix time: `decider_sig = BIP-340(sha256(JCS(decider_claim)))`.
3. The request carries `decider.pubkey`, `decider.request_id`, `salt`, `decider_claimed_at` and `decider_sig`. The issuer recomputes the
   claim from the plaintext and the salt, verifies the signature, requires `claimed_at` within 600 s, and only then claims the slot,
   before charging. A bad signature is refused (400) and not charged.
4. The receipt signs `slot_scope`, `decider_pubkey`, `request_slot`, `decider_claim` and `decider_sig` in clear, next to the commitments.

What it gives:
- **One receipt per (decider key, `request_id`), whichever account pays.** The slot does not depend on the paying account, so a
  second account, or an x402 payer with no account, lands on the same slot and is refused (409, not charged). Vector n18 is Oga's
  two-account case under a decider key.
- **No front-running.** Only the holder of the decider key can claim a slot under it. Someone who guesses a `request_id` can claim
  only slots under their own key, which a relying party that pins the decider key ignores.
- **Equivocation is published and self-proving.** If a second, different claim signed by the decider arrives for a taken slot, it
  is refused and listed on the slot: `GET /decision-receipt/slot/{request_slot}` returns `scope`, the holding `event_ids`, the
  holding `decider_claim` and `decider_sig`, and `conflicts` (each a `decider_claim` with its `decider_sig`). Two valid decider
  signatures over two different claims for one `request_slot` prove that the decider key signed twice for one request, and anyone
  can check that from the two signatures alone, without trusting the issuer. The identical claim sent again is a retry and is
  not listed.
- **Offline check.** A relying party with one receipt and its reveal checks the slot derivation, the claim and the signature itself
  (steps 4 and 5 above), then asks the slot endpoint whether `event_ids` is exactly that receipt's event id and whether `conflicts` is
  empty.

Limits, stated plainly:
- **It binds the decider key, not a person or a model.** Key management is the decider's. A stolen key can sign claims; a decider
  that uses a fresh key per request gets a fresh slot per request. A relying party must pin the decider key it trusts, out of band,
  just as it already decides which decider it trusts.
- **One claim per `request_id`.** A decider that re-decides under the same `request_id` with a different input, choice or salt
  produces a conflict. Retry by resending the identical signed claim, or use a new `request_id` for a new decision.
- **It still binds only the declared `request_id`.** A decider can sign two claims under two request ids. Requiring `request_id` to be
  the decider's own id for the call (and checking that against the decider's log) remains the relying party's job.
- **The issuer is still trusted for refusal and listing.** The decider signature makes a conflict provable by anyone, but whether a
  second claim reached the issuer, and whether the slot endpoint shows every receipt, rests on the issuer's record. The slot log,
  below, makes a hidden slot or a second version of the record provable, at a one-day granularity.
- **Privacy.** `request_slot` is an unsalted hash of `decider_pubkey` and `request_id`. With a guessable `request_id`, anyone holding
  the key's public key can confirm a guess. Use high-entropy request ids (decider API response ids usually are).
- The decision is still caller-reported, now reported by the decider's key: the receipt shows the decider signed this choice, not
  that the choice was correct.

### Slot log (daily, Bitcoin-stamped, live since 2026-10-10)

Once per UTC day the issuer publishes a snapshot of every slot and stamps it to Bitcoin with OpenTimestamps, the same mechanism
that anchors its `/ledger` verdicts: a 32-byte digest submitted to the public OTS calendars, checked with the standard client.

- **File** (`GET /decision-receipt/slots/log/<date>`, free): JSON lines, each line JCS. Line 1 is the header
  `{schema: "invinoveritas.decision_receipt.slot_log.v1", date, cutoff, prev_root, n_slots, merkle_root, rules}`. Then one line per
  slot taken before `cutoff` (the end of that UTC day) whose receipt was issued, sorted by slot:
  `{slot, scope, event_ids, taken_at, claim_sha256, decider_sig, conflicts}`, with `claim_sha256 = sha256(JCS(decider_claim))`
  (null for account scope) and `conflicts` = `[{claim_sha256, decider_sig, received_at}]` received before the cutoff.
- **Roots.** `leaf = sha256(line)`. Merkle pairs are `sha256((left_hex + right_hex) as UTF-8)`, an odd last node is paired with
  itself (the rule of the issuer's admission-chain checkpoints), and an empty tree is `sha256("invinoveritas.decision_receipt.slot_log.v1|empty")`.
  `log_root = sha256(JCS(header))` is the digest stamped. `prev_root` is the previous day's `log_root` (64 zeros for the first day),
  so each day commits to all earlier days.
- **Proof** (`GET /decision-receipt/slots/log/<date>.ots`, free): `ots verify -d <log_root> <date>.ots` against Bitcoin.
  The index of days with their roots and stamp status is at `GET /decision-receipt/slots/log`.
- **Per slot.** `GET /decision-receipt/slot/{slot}` for a taken slot adds `log`: the slot's `line`, `leaf`, `merkle_path` (side R
  means the sibling is on the right), the `header` and `log_root` of the latest snapshot that contains it, or
  `{"status": "not_yet_in_a_snapshot"}` before the next daily snapshot.
- **Append-only.** A snapshot is written once and never rebuilt. From one day to the next, every slot stays, with the same scope,
  event ids, claim hash and signature; only new conflicts may be appended.
- **Outside copy.** NENRIN (Toshikatsu Oga, HORIZON SHIELD) keeps every day file and its `.ots` exactly as this server served
  them, from 2026-10-09: index at `https://ledger.horizonshield.dev/evidence/slot-log`, files at `/evidence/slot-log/<date>` and
  `<date>.ots`. It copies each new day at 00:30 UTC, keyed by `log_root`, stamps each copy record in its own Bitcoin-anchored
  ledger, and keeps a second file for an already-held date beside the first, marked divergent. `slot_log_check.py` runs on those
  files unchanged, so `--prev` and `--inclusion` can be run against either copy.

Check with `slot_log_check.py` (standard library): the file against its header and roots, `--prev` for the chain and slot
continuity to the day before, `--inclusion` for a slot GET response, `--slot` for one slot in a file. Then run `ots verify`.

What it adds, honestly:
- **It addresses "the issuer shows different answers to different viewers", to the degree a daily stamped snapshot can.** A slot
  missing from a stamped snapshot dated after its receipt's `issued_at`, a slot whose line changed or disappeared between days, a
  conflict the slot endpoint showed but the log omits, or two different snapshots for one date (two OTS-anchored roots, or a day
  whose `prev_root` is not the stamped root of the day before): each becomes provable from the files and their Bitcoin anchors.
- **Granularity is one day.** Within the day before its snapshot, a slot is only as good as the slot endpoint. A relying party that
  needs more waits for the next snapshot and checks inclusion.
- **It proves existence and consistency, not completeness against what the issuer never wrote.** If the issuer refused to store a
  claim at all, no log shows it; a decider-signed claim the decider kept is still the evidence there.
- **OTS dates the root, it does not sign it.** Two divergent logs are attributable to the issuer through where they were served
  (this domain) and through outside witnesses that keep copies (for example a daily slot witness). Signing the header with the
  issuer key is a later, additive step.
- **Privacy.** The log lists every slot, its event ids and its time, so the number and timing of receipts is public. It carries no
  decider public key (a decider's activity is not grouped), and no commitment that is not already in the signed receipt.

## Run

```sh
python3 gen_vectors.py > vectors.json                 # v0, deterministic; regenerates byte-identical
python3 check.py vectors.json                         # 14/14
python3 gen_vectors.py --v02 > vectors-v0.2.json      # the 14 v0 vectors plus p6, n10, n11, n12
python3 check.py vectors-v0.2.json                    # 18/18
python3 gen_vectors.py --v03 > vectors-v0.3.json      # the 18 v0.2 vectors plus p7, p8, p9, n13, n14
python3 check.py vectors-v0.3.json                    # 23/23
python3 gen_vectors.py --v04 > vectors-v0.4.json      # the 23 v0.3 vectors plus p10-p13, n15-n21 (decider-scoped slots)
python3 check.py vectors-v0.4.json                    # 34/34
python3 -I probes/two_receipt_probe.py .              # Oga's probe: accept, accept, reject conflicting_choice
python3 slot_log_check.py <date>.jsonl --prev <previous>.jsonl && ots verify -d <log_root> <date>.ots   # the slot log
```

`probes/two_receipt_probe.py` is Toshikatsu Oga's (HORIZON SHIELD / NENRIN) probe, added byte for byte under its MIT header. Against the
v0.2 checker (c39feb6) it prints accept, accept, accept; from v0.3 (deda27ff) the set of both records rejects with `conflicting_choice`.

`bip340.py` is a standard-library BIP-340 implementation (the BIP's reference code) used to verify decider signatures and, in
`gen_vectors.py`, to sign the vectors deterministically. The service's test suite checks it against the BIP's test vector 0 and
against libsecp256k1 (coincurve) in both directions.

n15 to n21 kill checkers that skip the signature (n15), the slot derivation (n16), the claim-to-record match (n17), the
equivocation rule (n18 is also caught by `conflicting_choice`, n19 only by `decider_equivocation`), or that accept unknown scopes
(n20) or a decider scope without a signature (n21). p11 kills a checker that keys equivocation on the decider key alone.

The vectors use ASCII strings only, where RFC 8785 JCS equals compact sorted-key JSON. The invinoveritas
service's own test suite checks that the live code produces these vectors' commitments and review binding.

n13 and n14 kill a checker without the v0.3 rule (a v0.2 checker accepts both); p9 kills one that keys the rule on context alone, which
would reject two different questions asked about the same input.

The four v0.2 vectors kill three broken checkers that the v0 vectors cannot: one that ignores the issuer list (n10, n12), one that
does not open `review_issuers_commitment` (n11), and one that lets a review with no issuer through (n12).
