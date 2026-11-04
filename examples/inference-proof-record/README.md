# Independent check of a FlashProve inference proof

`flashprove_accepted_proof_check.json` records one check of FlashProve's stored example proof
(`anthropics/FlashProve` @ `9e2bdd8ff5bf9c62f18263d7dac189b0400b260c`, `examples/accepted-proof`, synthetic weights):
what was checked, the exact commands and digests, the result lines, two negative controls, and what the
check does **not** cover (real or served models, input provenance, decision authorisation, execution binding,
the full-size proof).

`signed_verdict.json` is a signed verdict bound to the record's sha256
(`11a274c6cb2929b7724b6cf0e930e5a8b06107d0f7a773355ec3d798932ba8b7`). Check it without trusting us:
`POST https://api.babyblueviper.com/verify-proof` with its `event` object, or verify the BIP-340 signature yourself (NIP-01).

`transcript_*.txt` are the raw verifier outputs, including the exit codes.

## Benchmark rows (for comparisons across verifiable-inference systems)

`benchmark_row_template.json` (schema `invinoveritas.inference_benchmark_row.v0`) is one row per (system, run): the request shape
(request length, the output positions the proof covers, next token, decoding, proved after vs during generation), the prove and verify
hardware, the numbers, the system's own UNMODIFIED verifier as referee (commit, source digest, verbatim result line), the negative
controls, the gates (what a YES covers and does not), and the checker's relation to the producer.

`benchmark_row_flashprove_small.json` is the row for the check above; it matches the signed record field for field.

`check_row.py` (Python standard library) validates a row: `python3 check_row.py benchmark_row_*.json`. It checks the row is complete
and self-consistent; it does not check the proof -- re-run the referee verifier for that.
