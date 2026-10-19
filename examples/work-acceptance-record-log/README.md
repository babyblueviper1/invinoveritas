# Work-acceptance record log: cold checker

`record_log_check.py` checks the enumerable record log at `https://api.babyblueviper.com/work-acceptance/records/log`. It uses the Python 3 standard library only and needs nothing from us beyond the published files.

```
python3 record_log_check.py                         # the live index and every day file
python3 record_log_check.py --dir ./copy            # a local copy (index.json + <date>.jsonl)
python3 record_log_check.py --key did:key:z6Mk...   # one producer's state
```

## What it proves from the files alone

For each day, it checks:
- the file hash
- the header line, by recomputing `log_root = sha256(JCS(header))`
- the `prev_root` chain from 64 zeros
- that the days are consecutive
- the Merkle root over the body
- the header counts
- every enrollment's Ed25519 signature over `invinoveritas work-acceptance enrollment v1 <key>`, using an embedded RFC 8032 verifier

Across days, it checks that every line listed on one day appears unchanged on the next. Only `producer_signature` may change, and only from `absent` to `present` or `declined`. `present` and `declined` are final, so a co-signature added after the 72 h grace never turns a listed decline into a pass.

For each producer key, it reports present, absent and declined counts. The decline rate covers closed records only (`present` + `declined`).
- With no closed records, the rate is `NOT_MEASURED`, never `0`.
- A key with no enrollment line is `NOT_MEASURED (not enrolled)`.

An empty set and a set with no declines are different facts, so they never print the same thing.

## What it does not prove

- **OpenTimestamps proofs:** not checked here. Tie each `log_root` to its Bitcoin block with `ots verify <date>.ots`, where the digest is `log_root`.
- **Completeness:** rests on the issuer listing every covered record. What the files make provable is narrower: nothing listed is later dropped, rewritten or re-dated. Two different files for one date also show up against their anchors.
- **Identity across keys:** the set is enumerable per key, not per party. Tying two keys to one producer is outside the log.

## Tested against

- **The live log (2 days, 2026-10-17 and 2026-10-18):** all checks pass, and no producer is enrolled.
- **A generated 3-day log** with one enrollment, one co-signed record and one declined record: it passes.
- **Six tampered copies of that log:** each one fails. The tampering was:
  - present changed to declined
  - declined changed to present
  - a record dropped
  - a record re-dated
  - a bad enrollment signature
  - an edited file
