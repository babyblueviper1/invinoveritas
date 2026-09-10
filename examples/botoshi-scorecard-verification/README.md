# Botoshi BotcoinScorecard signature verification — evidence bundle

Retrieved and computed 2026-09-10, in support of an ERC-8004 `thirdPartyVerdict` tag1 proposal
(eth-magicians t/25098, collaborator yaojin0609). Every file here is a raw, unedited fetch/output —
nothing paraphrased. sha256 of each file below; the git commit that adds these files is itself the
durable, checkable reference (an immutable commit hash, not a mutable live-endpoint claim).

| file | what it is |
| --- | --- |
| `botcoin-8004-agent-card_raw.json` | Raw fetch of `https://agentmoney.net/.well-known/botcoin-8004.json` |
| `coordinator_agent.md` | Raw fetch of `https://coordinator.agentmoney.net/agent.md` (EIP-712 domain/type schema) |
| `scorecard_0x39484e5f_raw.json` | Raw fetch of `https://coordinator.agentmoney.net/v1/miner/0x39484e5fdeedaf0916c53d9c3bf380d3f307eb5d/scorecard` |
| `eth_getlogs_request_meta.json` | The exact `eth_getLogs` request sent to `mainnet.base.org`, block range, retrieval timestamp |
| `eth_getlogs_raw_response.json` | The raw, unedited RPC response to that request |
| `verify_botoshi_scorecard.py` | The exact script used to recompute the EIP-712 signature (rfc8785 JCS + keccak256 + eth_account) |

## How to independently reproduce this

```
python3 -c "import sys; sys.path.insert(0,'.'); exec(open('verify_botoshi_scorecard.py').read())" < scorecard_0x39484e5f_raw.json
```

Expected: `recovered signer: 0x69747C4Ce6185d21A33b3BcdBa980d659600aC7b`, matching the `attesterWallet`
field in `botcoin-8004-agent-card_raw.json`'s `reputation` object and the `scorecardSigner` named in
`coordinator_agent.md`.

## What this establishes, and no more

- The signature on the captured scorecard bytes recovers to the address BOTH of Botoshi's own
  published materials (agent card + schema doc) self-declare as the signer. This is a self-declared
  attribution, not an independently-bound identity claim — no source outside the coordinator's own
  materials was used to bind that key to Botoshi/agentId 25975.
- The miner address (0x39484e5fdEedaf0916c53d9C3Bf380d3F307eB5d) is independently confirmed to be a
  genuinely active on-chain address (32 real submission logs to the V3 rig contract in a single
  ~66-minute window, per `eth_getlogs_raw_response.json`) — this establishes activity, not ownership,
  independence from the coordinator, or that the scorecard's own lifetime totals are independently
  re-derived from a full historical count.
- The separate ERC-8004 on-chain reputation-attestation mechanism (`tag1="botcoin-skill"`) was
  searched for in several recent 2000-block windows on the reputation registry and not found in the
  windows checked — not asserted as verified anywhere in this bundle.
