# Profile: invinoveritas.decision_receipt.slot_log.v1

The rules a verifier needs to recompute a decision-receipt slot-log snapshot. This document is content-addressed:
`GET /decision-receipt/slots/log` returns `profile.sha256`, the SHA-256 of these exact bytes, and
`profile.vectors_sha256`, the SHA-256 of `slot_log_vectors.json`. The `url` fields there are retrieval hints only.
The hashes identify the profile, not the URL.

## Canonical form
- JSON is canonicalized with RFC 8785 (JCS). Every value in a snapshot is an object, array, string, integer or null.
- SHA-256 output is lower-case hex. `sha256(s)` for a string means SHA-256 of its UTF-8 bytes.

## File
- JSON lines, UTF-8, each line JCS, each line terminated by `\n`, including the last.
- Line 1 is the header: `{schema, date, cutoff, prev_root, n_slots, merkle_root, rules}`. `schema` is
  `invinoveritas.decision_receipt.slot_log.v1`. `date` is the UTC day `YYYY-MM-DD`. `cutoff` is the unix time of the end of
  that day. `rules` is an informative one-line summary of this profile and carries no rule of its own.
- Every further line is one slot taken before `cutoff` whose receipt was issued, with exactly the keys
  `{slot, scope, event_ids, taken_at, claim_sha256, decider_sig, conflicts}`. `slot` is 64 hex. `scope` is `account` or
  `decider`. `claim_sha256` is `sha256(JCS(decider_claim))`, null for account scope. `conflicts` is
  `[{claim_sha256, decider_sig, received_at}]`, the differing decider-signed claims received before `cutoff`.
- Slot lines are sorted by `slot`, strictly ascending; no slot appears twice. `n_slots` is the number of slot lines.
- Every `taken_at` is less than `cutoff`.

## Roots
- `leaf = sha256(line)` for each slot line, as served.
- A Merkle pair is `sha256(left_hex + right_hex)`. On a level with an odd number of nodes the last node is paired with
  itself. The empty tree is `sha256("invinoveritas.decision_receipt.slot_log.v1|empty")`.
- `merkle_root` is the root over the leaves in file order.
- `log_root = sha256(JCS(header))`. It is the digest stamped with OpenTimestamps (`ots verify -d <log_root> <date>.ots`).
- `prev_root` is the previous day's `log_root`, or 64 zeros for the first day.

## Chain (from one day to the next)
- The previous day's snapshot is for an earlier `date`, and today's `prev_root` equals its `log_root`.
- Every slot of the previous day is present today with the same `scope`, `event_ids`, `taken_at`, `claim_sha256` and
  `decider_sig`. Its `conflicts` list today begins with the previous day's list: conflicts may only be appended.

## Inclusion (one slot)
- `GET /decision-receipt/slot/{slot}` returns `log: {line, leaf, merkle_path, header, log_root}`. `leaf` is
  `sha256(JCS(line))`. Folding `merkle_path` (each step `{side, hash}`; side `R` means the sibling is on the right) from
  `leaf` gives `header.merkle_root`, and `log_root` is `sha256(JCS(header))`.

## Outcomes a verifier reports
- `profile_unavailable`: these bytes or the vector file could not be obtained.
- `profile_mismatch`: they were obtained, but a hash differs from the one the index declares.
- `recompute_mismatch`: the profile verified, and a snapshot fails a rule above.

Only `recompute_mismatch` is evidence about a snapshot. The first two describe the verifier's ability to check. They are
not evidence of tampering.
