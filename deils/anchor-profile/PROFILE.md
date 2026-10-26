# deils-anchor-v1: a daily Bitcoin-anchored log of commitment records (DRAFT for review)

Status: **proposal for review**, posted to the trustless-ai DEILS group (TG topic 5583) on 2026-10-26. Nothing in our service
implements it yet. The service is built only after the review. DEILS core v1 stays frozen at `trustless-ai/deils@28976c8`. This is
an optional, named profile on top of it, and a verifier reports `anchored` or `not_anchored` explicitly.

What it adds to a DEILS commitment record:
- **Time.** The record existed no later than a Bitcoin block. Without this, a record's only time is its signer's own `created_at`.
- **Sequence.** Inside the published log there are no gaps, no duplicates and no reordering, within a day and across days.
- **History.** Each day commits to the previous one, so rewriting a day that is already confirmed breaks every later day.

What it does not establish is stated in "Limits" at the end. Every rule below has a vector in `vectors.json`, and `check.py`
(standard library only) runs them: `python3 check.py --vectors vectors.json`.

## 1. Canonical form
- JSON values in this profile are objects, strings (ASCII), integers in `[0, 2^53)` and `null`. Each object is serialized with
  RFC 8785 (JCS). For these types that is: keys sorted, no whitespace, integers in decimal, strings with JSON escaping.
- `sha256(x)` is SHA-256 over bytes. Hex is lower case.

## 2. Files
One file per UTC day `D`, named `D.jsonl`: UTF-8 JSON lines, each line exactly its JCS bytes, each terminated by `\n`.
- **Line 1, the header**, has exactly these keys:
  - `schema`: `"deils-anchor-v1"`.
  - `date`: `"YYYY-MM-DD"`.
  - `start`: unix seconds of `D` 00:00:00 UTC. `end`: `start + 86400`, which is `D+1` 00:00:00 UTC.
  - `count`: the number of record lines.
  - `first_position` / `last_position`: the first and last `ledger_position` in the file. Both are `null` when `count` is 0.
  - `prev_last_position`: the last `ledger_position` published on any earlier day, carried forward across empty days. It is 0 on
    the first day.
  - `prev_root`: the previous day's `log_root`, or 64 zeros on the first day.
  - `merkle_root`: section 3.
- **Every other line is one record**, with exactly these keys:
  - `ledger_position`, `proof_id`, `commitment_hash` and `profile`: taken from the signed DEILS commitment record.
  - `record_event_id`: the id of the signed record (NIP-01 event id, 64 hex).
  - `created_at`: the signed record's own `created_at` (integer unix seconds).
- Record lines are in `ledger_position` order.

## 3. Merkle root (RFC 9162 section 2.1.1)
- `leaf = sha256(0x00 || line_bytes)`, where `line_bytes` is the record line without its `\n`.
- An interior node is `sha256(0x01 || left || right)`, over the raw 32-byte digests.
- For `n > 1` leaves, split at `k`, the largest power of two smaller than `n`, and hash the two subtree roots. An odd node is
  carried up a level. It is never paired with itself.
- One leaf: the root is that leaf. Zero leaves (an empty day): the root is `sha256("")` =
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- `log_root = sha256(JCS(header))`. This is the digest that gets stamped (`D.ots`).

## 4. Rules for one day (a failure code for each)
| rule | code |
|---|---|
| every line is exactly its JCS bytes, with exactly the keys above | `line_not_canonical`, `bad_fields` |
| `start` is `D` 00:00:00 UTC and `end` is `start + 86400` | `bad_day_edges` |
| `count` equals the number of record lines | `count_mismatch` |
| `merkle_root` recomputes | `merkle_root_mismatch` |
| positions are consecutive: `first_position = prev_last_position + 1`, each next one is +1, and `last_position` is the last | `position_gap`, `position_start`, `position_end` |
| `count` 0: `first_position` and `last_position` are `null` | `empty_day_positions` |
| a record with `created_at >= end` (dated after its day) | `created_at_after_day` |
| a record with `created_at < start`: created on an earlier day but first published here, after that day's log was sealed | `late_record` |

The day window is `[start, end)`: 00:00:00 UTC is in, the next day's 00:00:00 UTC is out. `created_at` is in whole seconds, so
the edges are exact. `late_record` and `created_at_after_day` are reported separately on purpose. A late record is a real record
the issuer did not publish on its own day. A record dated after its day is a timestamp that cannot be true.

## 5. Rules between consecutive days
| rule | code |
|---|---|
| dates strictly increase, with no missing day: an issuer with nothing to publish still publishes an empty day | `date_gap` |
| `prev_root` equals the previous day's `log_root` | `prev_root_mismatch` |
| `prev_last_position` equals the previous day's `last_position`, or its `prev_last_position` if that day was empty | `prev_last_mismatch` |

An empty day therefore cannot hide a gap. If day 2 is empty, it must carry day 1's last position. Day 3 must then start one after
it.

## 6. Against the signed records (when the verifier has them)
Each line must match a signed DEILS commitment record. The record must have:
- an event id that recomputes (NIP-01);
- a valid BIP-340 signature by the issuer key the verifier pins;
- the same `proof_id`, `ledger_position`, `commitment_hash` and `profile` in its signed content, and the same `created_at`.

The codes are `record_missing`, `record_id_mismatch`, `record_signature_invalid`, `record_mismatch` and
`record_created_at_mismatch`. Without the signed records, `created_at` is only what the log asserts. With them, it is what the
issuer signed. Neither one is independent evidence of when the record was made. That is what the anchor adds, as an upper bound.

## 7. Anchor states
A day is in one of three states. A verifier never reports a stronger state than it checked:
- **published**: the file exists and passes sections 4 to 6, but has no stamp.
- **pending**: `D.ots` is an OpenTimestamps proof for `log_root` whose only attestations are calendar promises, or whose Bitcoin
  attestation could not be checked against a header.
- **confirmed**: the proof reaches a Bitcoin block-header attestation at height `H`. The verifier holds a block header for `H`
  from a source it chose, with valid proof of work. That header's merkle root equals the message the proof computes. The
  calendar's word is never enough.

A day is reported `anchored` only when it is confirmed **and** every earlier day in the chain passes sections 4 and 5. A
day with a valid chain but no confirmed stamp is `not_anchored`, with its state (`published` or `pending`). That is not a failure.
A proof for a different digest (`ots_digest_mismatch`), a header that does not match (`ots_bitcoin_header_mismatch`) or has
bad proof of work (`ots_header_invalid_pow`), and a day the issuer says is confirmed when it is only pending
(`pending_claimed_confirmed`) are failures.

Until a day is confirmed, its chained root alone does not rule out an alternative history. An issuer could publish a different
file for an unconfirmed day to different viewers. Confirmation fixes the day's root in a block. Two viewers who saw different
roots for the same confirmed day hold proof of equivocation.

## 8. Outcomes
`check.py` prints one result per day: `{date, status, state, height, codes}`. `status` is one of:
- `failed`: any code in sections 4 to 7 (except the not-confirmed reasons).
- `anchored`: confirmed and the chain passes.
- `not_anchored`: the chain passes but the day is not confirmed. `state` says `published` or `pending`.

## Limits
- **Completeness.** Consecutive positions prove there are no gaps inside the published sequence. They do not prove the issuer
  published every record it issued. A record that was never logged is invisible here. It shows up only if someone holds that
  signed record and finds its position missing or filled by a different record. That is a `record_mismatch` for whoever holds
  it. Both kinds of evidence are needed.
- **Time.** The anchor is an upper bound: the record existed before the block. It is not a lower bound, and it says nothing about
  when the underlying work was done.
- **Granularity.** One day. A record can sit up to a day, plus the stamp's confirmation time, before it is anchored.
- **The stamp dates the root but does not sign it.** Who published the root rests on the issuer's key and on where the file was
  obtained.
