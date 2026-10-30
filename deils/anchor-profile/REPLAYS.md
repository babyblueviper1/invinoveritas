# Independent replays

Runs of this profile by parties other than its author, newest first. This file is outside `SHA256SUMS` on purpose, so adding a replay never changes the pinned profile (`babyblueviper1/invinoveritas@1fe5fb29104d deils/anchor-profile`).

## 2026-10-29: review 5 harness fixes reproduced -- HOLD lifted (Pavlo)

- **What:** the harness fixes at `57c91fc629de`, on Windows, plus a separate parallel replay with the updated harness checks.
- **Result:** source hashes match; 58/58 vectors; `pins.py --self-test` 3/3; 40/40 non-equivalent mutants killed, the equivalent mutant survives as expected; 544/544 tamper witnesses caught; 3/3 removal controls pass, including under `python -O`; 0 crashed or unapplied mutations. The two false-green paths are addressed and no new harness failures were seen.
- **Verdict:** the review 5 harness HOLD is lifted at this pinned commit.
- **Scope (as stated by the reviewer):** this is not production approval, and does not establish best-chain membership, complete issuance history or actual record creation time; service implementation is a separate team decision.
- **Source:** trustless-ai Telegram group, topic 5583, message 5932.

## 2026-10-29: review 5 replay (Pavlo)

- **What:** the profile's harness at `1fe5fb29104d`, with negative controls of his own.
- **Result:** reproduced 58/58 vectors, 3/3 pin controls, 40/40 non-equivalent mutants killed, 544/544 tamper witnesses detected, the `re.ASCII` equivalent mutant reported separately. Found two harness-level false-green paths (a crash counted as a kill; any `FAIL` text counted as a caught witness), each shown with a negative control; the 40/544 results held under stricter independent checks. Verdict: ITERATE for the harness, conformance sign-off on HOLD.
- **Fixed:** see PROFILE.md, "Changes after the review 5 replay": crashes are their own outcome, a witness must fail on its own vector, and built-in removal controls fail the run if either guard is taken out.
- **Source:** trustless-ai Telegram group, topic 5583, message 5930.

## 2026-10-29: genesis day, anchored (Echo, Vertice)

- **What:** the production anchor log's genesis day, `2026-10-28.jsonl` (sha256 `7c9757691ef6bb83f0b0bc6963933c2870a7e29db147edcdf745e53a7848d7d4`), with `records.jsonl` and `2026-10-28.ots` as served by `https://api.babyblueviper.com/deils/anchor-log/`.
- **How:** cold, with `check.py` at `1fe5fb29104d`. The block header for 973617 came from mempool.space and blockstream.info (identical, hash `00000000000000000000c825458f1b71fe4fcf76bd8cf32903ab42f1f141b262`).
- **Result:** `anchored` / `confirmed`, height 973617, codes `[]`, `from_genesis: true`, `after_failure: false`, one notice `late_record_beyond_grace` (the pre-genesis backfill). Matches the author's run.
- **Controls, so the clean result is not vacuous:** with no headers it returns `not_anchored` / `pending`; with the header for 973616 it `failed` with `ots_bitcoin_header_mismatch`; with one hex character changed in a record it `failed` with `merkle_root_mismatch` and `record_mismatch`, even with the right header.
- **Source:** trustless-ai Telegram group, topic 5583, message 5919.

## 2026-10-28: conformance replay (Echo, Vertice)

- **What:** this profile's harness on a fresh clone at `1fe5fb29104d`, offline.
- **Result:** `mutants.py` 40/40 mutants killed (the listed equivalent mutant survives as expected); 544/544 tampered expectations caught; `PROFILE.md`, `vectors.json` and `mutants.py` hashes and all 14 `SHA256SUMS` entries match; `check.py --vectors vectors.json` 58/58; `pins.py --self-test` 3/3. Changing one confirmed height (973231 to 973232) drops it to 57/58.
- **Scope:** the author's harness reproduced on a second machine, adding no new attacks.
- **Source:** trustless-ai Telegram group, topic 5583, message 5903.
