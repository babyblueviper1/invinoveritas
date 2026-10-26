# DEILS reveal contract, as deployed

`reveal-contract-2026-10-25.json` is a snapshot of the two endpoint descriptions in our live OpenAPI (`POST /prove/{proof_id}/reveal`, `GET /attestations/{proof_id}`) as deployed on 2026-10-25. The deployed code lives in our private repository at commits `6f8c80be` (refusal contract), `95e066cb` (a terminal mismatch no longer serves the withheld content) and `e8149678` (that boundary stated in the endpoint description). This file is the public reference for those commits.

The behaviour it describes was replayed independently by Pavlo on two live fixtures (ledger positions 16 and 17). That replay covers the signed commitment record, the reveal order and refusals, the bind, and the withheld-content boundary. It does not cover production-wide security, OTS/PQ anchoring or external execution.

## Independent replay evidence

Pavlo's replay is published and pinned at [pipavlo82/deils-v1-independent-replay v1.0.0](https://github.com/pipavlo82/deils-v1-independent-replay/releases/tag/v1.0.0) (commit `58be70b4`). The release ZIP `deils-v1-independent-live-replay-2026-10-25-v1.0.0.zip` is 552,285 bytes, SHA-256 `b3544b46e8fce3c1015150ecd49557c355d37469f358d7fef281cb9c050d7f4e`. It holds the two-fixture replay, the signed-record checks, the withholding regression and 16 adversarial controls. 13 of the controls reproduce from public inputs; the other 3 need private inputs and are marked as such. The record is referenced from [trustless-ai/deils](https://github.com/trustless-ai/deils) at `28976c80` (PRs #1 and #2). Its scope is the one stated above, and OTS/PQ anchoring is not covered.
