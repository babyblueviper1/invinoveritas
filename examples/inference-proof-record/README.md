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
