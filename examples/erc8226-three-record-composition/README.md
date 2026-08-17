# ERC-8226 three-record composition

**This is not ERC-8226 spec text.** Thamer Dridi (spec editor) asked for a
worked example against the live Sepolia deployment. Thread:
[ERC-8226: Regulated Agent Mandate](https://ethereum-magicians.org/t/erc-8226-regulated-agent-mandate/28208),
posts #13–#20. His ask, in his words (post #20):

> In the token-hook integration, RAMS assumes that the regulated asset
> continues enforcing its own transfer-level compliance through mechanisms
> such as ERC-7943’s `canSend()` and `canReceive()` or ERC-3643’s compliance
> hook. RAMS independently answers whether the agent is authorized under
> the mandate.
>
> An implementation demonstrating the mandate check, the asset’s
> transfer-compliance check and the independently verifiable records around
> the same transaction would make that separation concrete. We would be
> glad to see it implemented and tested against the current Sepolia
> deployment; the reason-code interface can be updated once the PR lands.

Three records, one real transaction. Neither record can move the others.

| Record | Question | Who answers | Where |
|---|---|---|---|
| 1 | Was the agent authorized under the mandate for this action? | `AgentMandate.canExecute` | on-chain, pinned block |
| 2 | Did the *asset* treat the transfer as compliant? | whatever this token actually exposes (see investigation) | on-chain, same pin |
| 3 | Was the transfer itself reasonable given the stated facts? | invinoveritas `/review` | signed proof, `/verify-proof` |

Record 3 is **our** judgment layer. It is not part of ERC-8226. Thamer
already drew that boundary in post #18: `canExecute()` answers whether an
action is authorized under the mandate, not whether that action is
contextually sound; any optional judgment layer should compose separately
without changing RAMS authorization.

## Investigation (before the script was written)

Verified Sourcify exact-match source + ABI
(`11155111 / 0xd501…7cAa`, `11155111 / 0xD68E…778e`), not assumed from
the ERC-7943 interface.

**`AgentMandate.canExecute` is still the pre-PR bare bool.**

```
canExecute(address agent, address principal, address asset, bytes32 action, uint256 amount)
    external view returns (bool)
```

The agreed `ExecutionReason` enum (post #18) is **not deployed**. Do not
call `canExecuteWithReason`. The token’s `ramsDiagnose(agent, holder, value) -> bytes32`
re-derives the failing check in spec order — that is an integrator
workaround, not the future registry return.

**`GatedUSDRams` does not expose `canSend()` or `canReceive()`.**

The verified source says so in so many words (`supportsInterface`
deliberately does **not** advertise `IERC7943Fungible`: the contract
implements 1 of that interface’s 6 functions and none of
`forcedTransfer` / `setFrozenTokens` / `canSend` / `canReceive` /
`getFrozenTokens`). Claiming the ERC-165 id would lie.

What it *does* expose:

| function | returns | what it actually is |
|---|---|---|
| `canTransfer(address from, address to, uint256 amount)` | `bool` | Inherited from `GatedUSD`. Thin wrapper over `DelegationMirror.checkTransfer` for a **registered sender**. `to` is unused. VAR sender leash, not ERC-7943 `canSend`/`canReceive`. |
| `canTransferBy(address operator, address from, uint256 value)` | `(bool, bytes32)` | **Mixes** RAMS `ramsDiagnose` + live `checkPrincipal` + VAR. A pre-flight, not a clean asset-only surface. |
| (internal) `checkPrincipal` on the mandate’s `complianceProvider` | `(bool, ReasonCode, uint48)` | Live eligibility re-check on every mandated `transferFrom`. Closest analogue of “the asset’s own transfer-level compliance” on this deployment. Public on `VARComplianceProviderAdapter`. |

That gap — rationale names `canSend`/`canReceive`; this live token does
not have them — is a real finding, not a demo inconvenience. Record 2
therefore calls the functions that exist, and labels them.

**Update (2026-08-17, thamerdridi, t/28208#22):** confirmed this is a live-deployment-scope
gap, not a spec gap — ERC-7943 is not deployed on this Sepolia setup, but the RAMS↔ERC-7943
composition has been implemented and tested separately on the RAMS side, just not part of
what this repo's script talks to. The blocked case above still demonstrates the intended
separation cleanly: asset-side compliance would pass, RAMS independently rejects on the
mandate-specific cap.

## The two transactions

Same agent, same principal, same sink, same mandate (`maxTransactionValue
= 100_000_000` = 100 gUSD, 6 decimals).

| | cleared (primary) | blocked (refusal) |
|---|---|---|
| tx | `0x796a690853f9c79b71c6dd52892c9e42da447eac9a08fca7329528236869ec6c` | `0xdfd1877a8e5fed2c910f9ec0bcab93c8409d015ff38ea2cb80feb40931f51d74` |
| block | 11411044 / `0x187d41ea…b8fa` | 11411052 / `0x99da6ff8…0e0b` |
| status | 1 | 0 (reverted, 0 logs) |
| amount | 90_000_000 (90 gUSD) | 101_000_000 (101 gUSD) |
| which layer refused | — | **RAMS mandate** (`RAMS_OVER_TX_CAP`). Asset `canTransfer` and `checkPrincipal` both still passed. |

The blocked case is the more informative one for the separation: the
asset would have allowed the transfer; the mandate would not. They are
not the same bit.

`grantMandate` (context only): `0xe5dfe2fb…ec54` at block 11411043.

## Reproduce

Need a Sepolia RPC that still has **historical state** at block 11411043.
`https://ethereum-sepolia-rpc.publicnode.com` has pruned this height
(`state at block #11411044 is pruned`). This run used
`https://sepolia.gateway.tenderly.co` and
`https://rpc.sepolia.ethpandaops.io` (EIP-1898 `blockHash` +
`requireCanonical: true` succeeded on both). Local API on
`127.0.0.1:8000`, `HL_REVIEW_BEARER` in `../../.env.hl` (same 402 →
`OPERATOR_FULL_API_KEY` fallback as the Article 12 demo).

```bash
cd examples/erc8226-three-record-composition
../../venv/bin/python compose_three_records.py
```

Independent recompute of Record 1 / 2, no Python required — pin the
**parent** block (pre-state of the transfer) so `cumulativeUsed` is the
value the transfer actually saw. `eth_call` at the transfer’s own block
number is the *post*-state of that block.

Cleared, parent block 11411043 / `0xf6dfd58e…05bf`:

```text
# Record 1 — mandate (bare bool)
# canExecute(agent, principal, GatedUSDRams, bytes32(transferFrom.selector), 90000000)
cast call 0xD68E1bb972cA4EF7F5764FBf6d685a6DfC26778e \
  "canExecute(address,address,address,bytes32,uint256)(bool)" \
  0x0358da4d5d9324556b3fCA2c5e7fcDeb5612CF29 \
  0x6aB89F85cA075595d94BB0Be545ff54eE796c8fC \
  0xd501D68214503Fa03B5179F556029CD15D7f7cAa \
  0x23b872dd00000000000000000000000000000000000000000000000000000000 \
  90000000 \
  --rpc-url https://sepolia.gateway.tenderly.co \
  --block 0xf6dfd58e62b5b639525f4aff8f2702f36e18dcc990a8d6224ebb688f843a05bf

# Record 2a — GatedUSD.canTransfer (VAR sender leash; to unused)
cast call 0xd501D68214503Fa03B5179F556029CD15D7f7cAa \
  "canTransfer(address,address,uint256)(bool)" \
  0x6aB89F85cA075595d94BB0Be545ff54eE796c8fC \
  0x651e2Cb8CC62334D46b8378534f0AE0F1A2eD3Ae \
  90000000 \
  --rpc-url https://sepolia.gateway.tenderly.co \
  --block 0xf6dfd58e62b5b639525f4aff8f2702f36e18dcc990a8d6224ebb688f843a05bf

# Record 2b — live checkPrincipal on the mandate's provider
# identityRef from getMandate (see outputs/three_records.json)
cast call 0x7302C8ee3E3f53cD85E0BAF1bDe8479DD19575EB \
  "checkPrincipal(address,bytes32)(bool,uint8,uint48)" \
  0x6aB89F85cA075595d94BB0Be545ff54eE796c8fC \
  0xa4a4b711aca61f7c78ab2d0137dcdaf6d209f653d755e09225bdb0b8bd809b4d \
  --rpc-url https://sepolia.gateway.tenderly.co \
  --block 0xf6dfd58e62b5b639525f4aff8f2702f36e18dcc990a8d6224ebb688f843a05bf
```

Record 3: `POST /verify-proof` with `outputs/review_cleared.json` →
`review_response.proof.event` (free, no auth). Do not trust the
self-report in the review body.

Blocked-case amounts / block hash are in `outputs/three_records.json`.

## What actually happened (2026-08-15, live)

Not mocked. Historical `eth_call` via EIP-1898 hash pin.
`/review` `sign=true` `seed=true` `artifact_type=onchain_action`.

### Cleared — everything agrees (primary)

| | |
|---|---|
| tx | `0x796a6908…ec6c` status 1, 90 gUSD |
| Record 1 `canExecute` (parent 11411043) | **true** |
| Record 2 `canTransfer` | **true** (principal is *not* registered in DelegationMirror, so this path is the ungated fall-through) |
| Record 2 `checkPrincipal` | **eligible=true, COMPLIANT (0)** |
| `ramsDiagnose` (diagnostic) | `RAMS_OK` |
| `/review` | **approve_with_concerns** (0.94) |
| `decision_ref` | `sha256:a49215273572fa4d35e7f69e3d43982c7ce3aef04f12aedfeeab6775dd4fc663` |
| proof event id | `9d1cd369546b8eb36a65e54988df8bc5f7abd90a643405789fa32bae1efdae85` |
| `/verify-proof` | `valid: true` (id_integrity, signature_valid, issued_by_invinoveritas, decision_ref_recomputes, vantage_limitation_recomputes) |

`/review` summary: the 90 gUSD transfer fits the 100 gUSD tx cap and 500
gUSD cumulative cap and the pre-state checks; reasonable as a
no-mainnet-value demonstration only — the facts do not establish that
this recipient or purpose was contextually intended.

### Blocked — layers disagree (the useful refusal)

| | |
|---|---|
| tx | `0xdfd1877a…1d74` status 0, 101 gUSD, block 11411052 |
| Record 1 `canExecute` (parent 11411051) | **false** |
| Record 2 `canTransfer` | **true** |
| Record 2 `checkPrincipal` | **eligible=true, COMPLIANT (0)** |
| `ramsDiagnose` (diagnostic) | **`RAMS_OVER_TX_CAP`** |
| `/review` | **reject** (0.99) |
| `decision_ref` | `sha256:668ed696f62bedd7ebe73198b72fa97bc71203c016f17a1140d6829692e70eb8` |
| proof event id | `9ff6badc216fa95416a980b0a7b929ae49cc59845a8ec1236a621cd0214e881a` |
| `/verify-proof` | `valid: true` (same checks) |

101 > 100. The asset’s own checks would have allowed it. The mandate
refused it. The receipt has zero logs; `cumulativeUsed` stays at
90_000_000. That is the three-record separation in one reverted
`transferFrom`.

Mandate snapshot (cleared pre-state / grant block 11411043):
`maxTransactionValue=100000000`, `maxCumulativeValue=500000000`,
`cumulativeUsed=0`, `revoked=false`. After the cleared transfer, the
blocked pre-state shows `cumulativeUsed=90000000`.

Auth: `HL_REVIEW_BEARER` 402 both times; retried
`OPERATOR_FULL_API_KEY`. `seed=true` → `proofs_seeded`.

## What's real vs this folder's construction

| Real | This folder |
|---|---|
| Deployed Sepolia contracts and the three published tx hashes (a-laz #14, independently re-checked here) | The composition script and this README |
| `canExecute` / `canTransfer` / `checkPrincipal` bytes at the pinned block hashes | Calling them and laying the answers side by side |
| `/review` verdict and the schnorr proof (independently `/verify-proof` valid) | Treating that verdict as if it were an ERC-8226 output — it is not |
| Sourcify exact-match source | A claim that this token implements ERC-7943 `canSend`/`canReceive` — it does not |

`canTransferBy` is recorded under `diagnostic_mixed_preflight` only. It
mixes layers; using it as Record 2 would hide the disagreement the
blocked tx exists to show.

## Files

| file | role |
|---|---|
| `compose_three_records.py` | fetch txs, pinned eth_call, live `/review` + `/verify-proof` |
| `outputs/three_records.json` | both cases, all three records, calldata so you can recast |
| `outputs/review_cleared.json` / `review_blocked.json` | full `/review` request + body |
| `outputs/verify_proof_cleared.json` / `verify_proof_blocked.json` | independent `/verify-proof` |
