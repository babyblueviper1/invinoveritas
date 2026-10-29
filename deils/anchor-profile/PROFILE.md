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
  - `date`: `"YYYY-MM-DD"`: the WHOLE string is four, two and two ASCII digits with hyphens, nothing before or after, so no trailing
    newline either (one spelling per day, so one `log_root` per day).
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
- Record lines are in `ledger_position` order. A record line has six fields. The proposal (TG 5850) listed five; `created_at` was
  added at review, so the leaf hash covers it.
- Types are checked per key: integers are integers, `first_position`/`last_position` are integer or `null`, `prev_root`,
  `merkle_root` and `record_event_id` are exactly 64 lower-case hex characters, the whole string (a trailing newline, upper case or
  63 characters is a second spelling of one id). Anything else is `bad_fields`, never an exception.

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
| a record with `created_at < start`: created on an earlier day but first published here, after that day's log was sealed | `late_record` (a **notice**, see below) |
| ...and `created_at < start - 86400`: more than one day before the day it is published in | `late_record_beyond_grace` (a **notice**) |

The day window is `[start, end)`: 00:00:00 UTC is in, the next day's 00:00:00 UTC is out. `created_at` is in whole seconds, so
the edges are exact. `late_record` and `created_at_after_day` are reported separately on purpose. A record dated after its day is a
timestamp that cannot be true, so it fails the day. A late record is a real record the issuer did not publish on its own day. Its
**recovery path** is to publish it in the next day's log, at the next position. The checker reports it as a notice on that day and
does not fail the day. Positions stay consecutive, and the record's own signed `created_at` shows how late it was.

A late record's `created_at` is **the issuer's claim and nothing more**. The anchor proves when the record was *published* (no later
than the block that confirms its day), never when it was *created*. A consumer must not treat a late record's `created_at` as
evidence of creation time: a record backdated by a year passes with only a notice (review 4, Echo's probe). The grace window is one
day: `late_record` covers the normal recovery path (the next day's log), and anything older is `late_record_beyond_grace`, reported
separately so a consumer can refuse it. Neither is a failure, on purpose: a failed day is terminal for every later day (section 7),
so failing a late record would turn one honest delayed publish into a permanently broken chain. The issuer's signed `created_at` and
the independently anchored publication time stay two separate facts.

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
- an event id that recomputes (NIP-01 serialization exactly: in strings, escape only `\n \" \\ \r \t \b \f`; every other character, including other control characters, verbatim);
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
- **confirmed**: the proof reaches a Bitcoin block-header attestation at height `H`, and the verifier holds a block header for
  `H`. The header is **trusted input**: get it from your own node, or from explorers you choose (two that agree is the minimum we
  suggest). The checker requires the header to carry the **pinned** difficulty for its retarget epoch (`H // 2016`, table
  `PINNED_BITS` in `ots_verify.py`, or a pins file: `pins.py` derives an epoch's bits from its first block's header as two sources you choose return it byte-identically, checks its proof of work, and writes `pins.json` for `check.py --pins`. Run it against your own node to drop the explorers from your trust set. pins.py's proof-of-work check only tests a header against its OWN bits, so it cannot catch a forged easy-bits header: the guard is that two independent sources agree, or your own node), to meet that target, and to have a merkle root equal to the
  message the proof computes. A header's self-declared difficulty is never trusted: with regtest bits a forged header passes proof
  of work at nonce 0 (review 2). A height whose epoch is not pinned is `ots_bits_unpinned`, which means not confirmed and is not a
  failure. The calendar's word is never enough. Even a valid proof of work only shows real work on that header, not that the block
  is in the best chain. That protection comes from where you got the header.

A day is reported `anchored` only when all three hold:
- it is confirmed;
- the chain was checked from **genesis**, meaning the first file supplied has `prev_root` of 64 zeros and `prev_last_position` 0. A
  chain checked from a later day cannot see omissions before it, so its days are at most `not_anchored`, with `checked_from` set
  (review 2);
- no earlier day in the chain failed. A failed day is permanent evidence that the history is broken. Every later day stays
  `not_anchored` (`after_failure`), even if it is clean and confirmed. This is **terminal by design**: a later stamp cannot repair
  an earlier break. Late records are the one recoverable case (section 4).

A day with a valid chain but no confirmed stamp is `not_anchored`, with its state (`published` or `pending`). That is not a failure.
A proof for a different digest (`ots_digest_mismatch`), a header that does not match (`ots_bitcoin_header_mismatch`) or has
bad proof of work (`ots_header_invalid_pow`), and a day the issuer says is confirmed when it is only pending
(`pending_claimed_confirmed`), and a header with the wrong difficulty for its epoch (`ots_header_bits_mismatch`) are failures.

Until a day is confirmed, its chained root alone does not rule out an alternative history. An issuer could publish a different
file for an unconfirmed day to different viewers. Confirmation fixes the day's root in a block. Two viewers who saw different
roots for the same confirmed day hold proof of equivocation.

## 8. Outcomes
`check.py` prints one result per day: `{date, status, state, height, codes, notices, checked_from, from_genesis, after_failure}`.
The vectors pin every one of these fields: since review 5, `date` and `height` too (review 4 said "every" but compared only
`status, state, codes, notices, checked_from, from_genesis, after_failure`; Pavlo, TG 5889). `notices` is `late_record` and/or `late_record_beyond_grace`. `checked_from` is
the date of the first readable header; `from_genesis` needs BOTH `prev_root` of 64 zeros and `prev_last_position` 0 in that header
(either alone would let a first file hide earlier records); `after_failure` is true on a day that passes its own rules but comes
after a failed day.
`status` is one of:
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

## Changes after review 2 (Echo, TG 5859-5860, 2026-10-26)
1. Forged headers: proof of work now uses the pinned difficulty per retarget epoch, not the header's own bits. There is a vector
   with Echo's attack (regtest bits, never-stamped digest) and one with an unpinned epoch.
2. `anchored` requires a chain checked from genesis. Results carry `checked_from` and `from_genesis`.
3. A failed day is terminal for anchoring, and this is now stated. `late_record` is a notice with a recovery path, so it is no longer
   a day failure.
4. New vectors for each mutant that survived: the empty-day carry, the day start edge, the issuer pin, a confirmed day after a failed
   day, OTS trailing bytes, and the difficulty check. The end-to-end **anchored** vector is in, because day 3 confirmed at block
   973231.
5. Type checks per key (`bad_fields`, never an exception), plus vectors for a string `created_at`, a null position and a missing
   `sig`.
6. Dates pinned to `^\d{4}-\d{2}-\d{2}$`. Event ids use exact NIP-01 serialization, with a vector that puts a control character
   in a tag.

## Changes after review 3 (Echo TG 5863, Pavlo 5864, 2026-10-26)
- Pin-update process: `pins.py` (epochs by number or `--for-height`). The two embedded pins (481 `0x17021ef0`, 482 `0x17020093`)
  re-derived independently from each epoch's first block; mempool.space and blockstream.info agree on both (epoch 481 was previously
  checked against one explorer only). Pins, like headers, are trusted input; an unpinned epoch stays `ots_bits_unpinned`.
- Anchor layers (Echo 5867): this profile is the free, independent Bitcoin backstop (`published` / `pending` / `confirmed`). An
  on-chain anchor that contracts can read (an L2 tree head, or the ERC-8274 verifier for zkIE) is a separate, programmable layer; a
  consumer reports each layer as its own result and never collapses them.

## Changes after review 4 (Echo TG 5880, Pavlo 5881, 2026-10-26/27)
1. **Late records (decision for the Tuesday review).** Section 4 now says a late record's `created_at` is the issuer's claim only and
   is never evidence of creation time; the anchor bounds publication. Proposed: a one-day grace, `late_record` within it and
   `late_record_beyond_grace` beyond it, both notices. Failing was considered and rejected because a failed day is terminal for every
   later day. Vectors at the exact edge (start - 86400: within) and one second beyond, plus Echo's year-old backdate.
2. **Mutants that survived review 3**, each with a vector now: genesis needs both conditions (a zeros root with
   `prev_last_position` 3, and the mirror); an unpinned epoch end to end on the chain (day 3's own `log_root` attested in epoch 483,
   which starts in about two weeks: `not_anchored`, pending, not failed); the runner compares `checked_from`, `from_genesis` and
   `after_failure` on every chain vector.
3. **Anchored regexes.** `date` and the 64-hex fields are whole-string, ASCII-only matches (`$` also matched before a trailing
   newline). Vectors: an id with `\n` appended, upper-case hex, 63 characters, a date with a trailing newline, and a string in an
   `int?` field.
4. **`pins.py --self-test`** runs offline: canned sources agree, disagree, or serve a header with bad proof of work.
5. Mutation check on the new rules: 12 mutants (Echo's 7 survivors plus the grace boundary, upper case, both regexes and the `int?`
   check), 12 killed. 58 vectors pass.

## Changes after review 5 (Pavlo TG 5889, Echo TG 5890, 2026-10-27)
1. **Every result field is pinned.** Each chain vector now also pins each day's `date` and its confirmed Bitcoin `height` (973231 on
   the four confirmed chains, `null` on every other day; a day whose header cannot be read reports `date: null`), and the runner
   compares them. Section 8 said "every" field at review 4 while comparing seven of nine; corrected above.
2. **Negative witnesses.** `mutants.py` part 2 tampers each pinned field of every chain vector one at a time (`date`, `height` +1 and
   `null`, `checked_from`, `from_genesis`, `after_failure`): 544/544 tampers make the runner fail.
3. **The mutation run is in the repo** (`python3 mutants.py`, offline, standard library). 40 mutants: the earlier controls replayed (both
   genesis halves, terminal failure, the grace edge both ways, collapsing the two late notices, whole-string and lower-case
   regexes, `int?`, the unpinned epoch, the OpenTimestamps and pins checks, the section-8 output fields) and 5 new ones on
   `date`/`height`. It covers the cases Echo listed for his 20; it is our own list, not a copy of his. 40/40 killed. One equivalent mutant is listed and expected
   to survive: removing `re.ASCII` from the date regex, since a non-ASCII date is rejected at canonicalisation first; `re.ASCII` stays
   as defense in depth.
4. **Epoch pins.** When the end-to-end vector's epoch rolls over (483, from about block 973728), the new pin is added with `pins.py`
   (two agreeing sources or your own node) and recorded in this changelog with the block and both sources. 58 vectors pass.

## Changes after the review 5 replay (Pavlo TG 5930, 2026-10-29)
The replay at `1fe5fb29104d` reproduced every count (58/58, 3/3, 40/40, 544/544) and found two places where the harness could report a
pass without a check having caught anything. Both are in `mutants.py`'s accounting, not in `check.py`; the 40 and 544 also held under
Pavlo's stricter independent checks.
1. **A crash is not a kill.** `mutants.py:91` counted any nonzero exit as KILLED, an unrelated crash included. A run now counts only when
   it finished normally: exit 0 or 1, a final `N/M` summary line whose counts match the PASS/FAIL lines, and exit 1 exactly when a line
   failed. Anything else (a traceback, another exit code, a hang past 300 s) is CRASHED, reported as a problem, never a kill.
2. **A witness is caught only by its own vector.** `mutants.py:145` counted any stdout containing `FAIL` as caught. A tamper now counts
   only when the run finished normally and the one failing line names the tampered vector.
3. **Removal controls.** Part 3 runs first: a mutant that crashes the runner must be classed crashed; a runner that prints a `FAIL` line
   without running any check must not count as a caught witness, and neither may a failure on another vector. Put either old
   accounting back and the run fails (checked both ways). Result: controls 3/3, 40/40 killed, 0 crashed, 544/544 caught.

