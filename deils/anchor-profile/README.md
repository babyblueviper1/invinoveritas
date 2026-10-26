# deils-anchor-v1 (draft for review)

An optional DEILS v1.x profile: a daily, Bitcoin-anchored log of commitment records. It is posted for review in the trustless-ai
DEILS group before anything is built. DEILS core v1 stays frozen at `trustless-ai/deils@28976c8`.

- `PROFILE.md`: the rules (file format, RFC 9162 Merkle root, rules for one day and across days, signed-record checks, the three
  anchor states, and what the log does not prove).
- `check.py`: the checker, standard library only. Run `python3 check.py --vectors vectors.json`. On real files:
  `python3 check.py D1.jsonl D2.jsonl ... --records records.jsonl --issuer <pubkey> --ots D=D.ots --headers headers.json`.
- `ots_verify.py`: an OpenTimestamps proof walker, standard library only. A Bitcoin attestation counts only against a block
  header you supply. The walker checks the header's proof of work and its merkle root.
- `gen_vectors.py` and `vectors.json`: 47 vectors, including the end-to-end anchored chain (day 3 confirmed at block 973231),
  valid cases (empty day, days of 3, 5 and 7 records, a control character in a tag) and one failing or notice vector per rule. Records are signed with a TEST key derived from a public string.
- `ots/`: real data. `real.json` holds our 2026-10-09 decision-receipt slot-log stamp, confirmed at Bitcoin block 970761, with
  headers that mempool.space and blockstream.info both return. `base_day3.*` stamps the vector chain's day 3 `log_root`:
  pending (4 calendars) and confirmed at block 973231 (`base_day3.confirmed.ots`, header in `base_day3.json`).

Review 2 (Echo) fixes are listed at the end of PROFILE.md. Each of the 18 mutations in the mutation run (Echo's six survivors included) makes at least one vector fail.
