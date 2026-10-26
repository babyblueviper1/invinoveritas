# deils-anchor-v1 (draft for review)

An optional DEILS v1.x profile: a daily, Bitcoin-anchored log of commitment records. It is posted for review in the trustless-ai
DEILS group before anything is built. DEILS core v1 stays frozen at `trustless-ai/deils@28976c8`.

- `PROFILE.md`: the rules (file format, RFC 9162 Merkle root, rules for one day and across days, signed-record checks, the three
  anchor states, and what the log does not prove).
- `check.py`: the checker, standard library only. Run `python3 check.py --vectors vectors.json`. On real files:
  `python3 check.py D1.jsonl D2.jsonl ... --records records.jsonl --issuer <pubkey> --ots D=D.ots --headers headers.json`.
- `ots_verify.py`: an OpenTimestamps proof walker, standard library only. A Bitcoin attestation counts only against a block
  header you supply. The walker checks the header's proof of work and its merkle root.
- `gen_vectors.py` and `vectors.json`: 32 vectors. There are 6 valid cases (chains with an empty day; days of 3, 5 and 7 records)
  and one failing vector per rule. Records are signed with a TEST key derived from a public string.
- `ots/`: real data. `real.json` holds our 2026-10-09 decision-receipt slot-log stamp, confirmed at Bitcoin block 970761, with
  headers that mempool.space and blockstream.info both return. `base_day3.*` is a fresh stamp of the vector chain's day 3
  `log_root`.

The vectors were mutation-tested. Disabling any of 12 rules in the checker, including the RFC 9162 split, the leaf prefix, the
day edge, proof of work and the "pending claimed confirmed" rule, makes at least one vector fail.

Not in this draft yet: the end-to-end **anchored** vector. Day 3's stamp was submitted to 4 calendars on 2026-10-26 and is still
pending. When it confirms in a Bitcoin block, we add it along with its header, and the vector should report `anchored`. Until
then, the pending case is covered end to end, both honestly reported and falsely claimed as confirmed.
