# DEILS reveal contract, as deployed

`reveal-contract-2026-10-25.json` is a snapshot of the two endpoint descriptions in our live OpenAPI (`POST /prove/{proof_id}/reveal`, `GET /attestations/{proof_id}`) as deployed on 2026-10-25. The deployed code lives in our private repository at commits `6f8c80be` (refusal contract), `95e066cb` (a terminal mismatch no longer serves the withheld content) and `e8149678` (that boundary stated in the endpoint description). This file is the public reference for those commits.

The behaviour it describes was replayed independently by Pavlo on two live fixtures (ledger positions 16 and 17). That replay covers the signed commitment record, the reveal order and refusals, the bind, and the withheld-content boundary. It does not cover production-wide security, OTS/PQ anchoring or external execution.
