# ERC-8226 three-record composition

**Update (2026-08-19) — Part 2 added below: a composed demo WITH a real ERC-7943
test double.** Part 1 (original, unchanged) found that the live `GatedUSDRams`
deployment does not implement ERC-7943 `canSend()`/`canReceive()` at all — a real
gap, not a demo inconvenience (see "Investigation" below). WeissCurry
([post #24](https://ethereum-magicians.org/t/erc-8226-regulated-agent-mandate/28208/24))
asked whether the reference material should include one end-to-end example
putting asset compliance, RAMS authorization, and the venue-level result side
by side, "so an integrator can see which layer produced each decision without
having to reconstruct it across separate examples." Ludovico rossi (RAMS
editor, [post #27](https://ethereum-magicians.org/t/erc-8226-regulated-agent-mandate/28208/27))
confirmed: "yes, treat the composed case as prioritized." Part 2 is that
example — jump to [Part 2](#part-2--composed-with-a-real-erc-7943-test-double)
if that's what you're here for; Part 1 below is preserved as originally written.

---

## Part 1 — original (Thamer Dridi's ask, posts #13–#20)

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

---

## Part 2 — composed with a real ERC-7943 test double

Part 1 above found a real gap: the live `GatedUSDRams` deployment does not
implement ERC-7943 `canSend()`/`canReceive()` at all, so the original demo's
Record 2 was necessarily the token's actual (non-ERC-7943) surface, not the
canonical pair WeissCurry and Ludovico were asking about. This part closes
that gap with a real, minimal, deliberately non-enforcing ERC-7943-shaped
test double, deployed fresh, and a real mandate self-granted on the same
already-live, already-deployed `AgentMandate` registry — no cooperation from
the RAMS team needed. `grantMandate` is permissionless by design (it just
verifies an EIP-712 signature from the named principal); the domain separator
computed locally (`ae6058ab...`) was checked byte-for-byte against the real
on-chain `AgentMandate.DOMAIN_SEPARATOR()` before signing anything for real.

### What's new here vs Part 1

| | Part 1 (`GatedUSDRams`) | Part 2 (`MinimalERC7943TestDouble`) |
|---|---|---|
| `canSend()`/`canReceive()` | Not implemented | Implemented, real, queryable |
| Asset knows about RAMS | Yes — live `checkPrincipal` re-check on every `transferFrom` | **No** — `transfer()` only checks its own `blocked` flag |
| What "blocked" means | The token's own transfer reverts (status 0) | `canExecute()` independently says no; the asset's `transfer()` still **succeeds** (status 1) — read that as the venue executing an action RAMS would refuse to authorize, not as a reverted transaction |

That second row is the actual finding, not a shortcoming of the test double.
An integrator who assumes "the asset would have caught it" is wrong for any
asset shaped like this one — which is a real, plausible shape (a token that
predates RAMS, or one whose team hasn't wired in a live mandate check). The
whole reason to check all three records independently, not infer one from
another, is exactly this case.

### Contracts

`contracts/MinimalERC7943TestDouble.sol` — `canSend`/`canReceive` return
`!blocked`; `transfer(address,uint256)` moves its own internal balance,
gated only by `blocked`, never by RAMS. Not a full compliant token by design
(see [post #25](https://ethereum-magicians.org/t/erc-8226-regulated-agent-mandate/28208/25),
"even a minimal test double").

`contracts/MinimalComplianceProvider.sol` — always reports `eligible=true`.
Exists only because `grantMandate` requires a working `IComplianceProvider`
whose `checkPrincipal` clears for the named principal; a fresh throwaway
demo address has no real KYC/AML registration anywhere to check against.

Both deployed fresh on Sepolia, verifiable read-only via the addresses below
(bytecode/source in this repo, not independently Sourcify-verified — these
are throwaway demo contracts, not published for reuse):

| contract | address |
|---|---|
| `MinimalERC7943TestDouble` | `0x3dd1Fc46c3FAf44B46733689bAb47157b530783f` |
| `MinimalComplianceProvider` | `0x35c1adC4f68BEC4Bb042612dC9D50aef5A675eF5` |

### The real mandate

Granted via a real `grantMandate` tx on the live registry
(`0xD68E1bb972cA4EF7F5764FBf6d685a6DfC26778e`):
`0x946f4a9e721264bf22a76cf905f920b926a6845f707db0054413074321b2fb28`.

`agent=0x3a260e797339f4Bc822ee67A1d52cfd04719EB07`
`principal=0xc5eC2960Ad560AFE09602605CBCEa060244C4178`
`maxTransactionValue=100000000` `maxCumulativeValue=500000000` (same shape
as Part 1's 100/500 gUSD caps). Signed off-chain by the principal key
(EIP-712, `nonces(principal)=0` at grant time) — the principal never pays
gas; the deployer relays the signed grant. All three throwaway keys are
published in `testnet_keys.json` in this directory — Sepolia only, zero real
value, published for full reproducibility (same "not mocked" ethos as the
rest of this repo).

### The two cases — real transactions, agent as `tx.from`

Both venue-level transfers were submitted by the **agent itself** (not a
deployer stand-in — an earlier draft used a deployer self-transfer and
`/review` correctly flagged that as a real gap, `intent_mismatch`: "the
authorized agent neither submitted the transaction nor transferred the
principal's assets" — fixed in `exercise_as_agent.py`), sending to the
**principal**.

| | cleared | over_cap |
|---|---|---|
| amount | 90,000,000 (90 units) | 150,000,000 (150 units) |
| Record 1 — `canExecute` (real live view call, pinned at the tx's own parent block) | **true** | **false** — 150 > 100 cap |
| Record 2 — `canSend`/`canReceive` (real live view calls, same pin) | **true / true** | **true / true** — the asset has no opinion either way |
| Record 3 — venue `transfer()` tx | `0x12e7fc69ae7660f534e6d460155b69aac3d45299f84fbe5087a28e2033968947` status **1** | `0xdb832e96dfc595407a76771d9e745a0d9be3fefa8e13d116be270b78665834a8` status **1** |
| Record 3 decoded Transfer event | from=agent to=principal amount=90000000 | from=agent to=principal amount=150000000 |
| Record 3 (`/review`, sign+seed) | **approve_with_concerns** (0.87) | **reject** (0.99) |

Pinned pre-state blocks (parent of each venue tx, matching Part 1's own
EIP-1898 convention): cleared at block 11522248
(`0xb2ebe89dfb75e1ff3052b13f9dd672ef5d8a41c30fe208c86fa6f074200d9b85`),
over_cap at block 11522249
(`0x8328b61e1d586a8b87de7ddc87301ef30cc7ddbed0e10b4f9c55d7ba8a6cbd36`) — both
independently re-checked against `--block <hash>` and matched the unpinned
reads exactly (recorded in `outputs/test_double_composition.json`'s
`pinned_reproduce` field per case).

Both cases' venue transaction **succeeded** (status 1) — including
over_cap, where RAMS's own `canExecute()` independently said no. This is the
whole point: the test double never asked RAMS, so it had no way to refuse.
`/review`'s own verdicts on the two cases land where they should:
`approve_with_concerns` on cleared (everything agrees, but RAMS is
advisory, not an execution control — a real, disclosed concern, not a
false positive), flat `reject` on over_cap (RAMS denies, the asset let it
through anyway — treating the completed transfer as authorized would
directly contradict the governing authorization layer). Full verdict bodies:
`outputs/review_test_double_cleared.json` / `outputs/review_test_double_over_cap.json`
(named with a `test_double_` prefix so they never collide with Part 1's own
`review_cleared.json`/`review_blocked.json` — an earlier draft here used the
bare names and silently overwrote Part 1's real recorded output; caught in
`git diff` before commit, restored via `git checkout`, filenames fixed).

### A real methodology mistake, caught and fixed mid-build

An earlier pass here (worth stating plainly rather than editing out of the
history) had the **deployer** submit both venue transfers to itself, as a
placeholder — `/review` correctly rejected with a `blocker`-severity
`intent_mismatch` finding ("the authorized agent neither submitted the
transaction nor transferred the principal's assets"). A second, sloppier
pass fixed the sender but left a stale sentence in the reviewed artifact
text claiming `from==to==deployer` while the actual decoded event already
showed `from=agent to=principal` — `/review` caught that internal
inconsistency too (`blocker`, `correctness`: "the stated transaction facts
conflict"). Both are logged in this directory's git history/outputs rather
than quietly cleaned up, in the same spirit as Part 1's own honesty about
what `GatedUSDRams` does and doesn't implement — the review tool doing its
job on our own work, twice, is itself part of the record.

### Reproduce

```bash
cd examples/erc8226-three-record-composition
# Deploys are already live (see addresses above); to redeploy fresh:
../../venv/bin/python compose_with_test_double.py --skip-review
# Re-exercise with the agent as sender (already the recorded state):
../../venv/bin/python exercise_as_agent.py
# Add/refresh Record 3 (/review + /verify-proof) on top of the recorded facts:
../../venv/bin/python add_review_record.py
```

Independent recompute of Records 1/2 without Python, pinned at the cleared
case's parent block:

```bash
cast call 0xD68E1bb972cA4EF7F5764FBf6d685a6DfC26778e \
  "canExecute(address,address,address,bytes32,uint256)(bool)" \
  0x3a260e797339f4Bc822ee67A1d52cfd04719EB07 \
  0xc5eC2960Ad560AFE09602605CBCEa060244C4178 \
  0x3dd1Fc46c3FAf44B46733689bAb47157b530783f \
  0xa9059cbb00000000000000000000000000000000000000000000000000000000 \
  90000000 \
  --rpc-url https://sepolia.gateway.tenderly.co \
  --block 0xb2ebe89dfb75e1ff3052b13f9dd672ef5d8a41c30fe208c86fa6f074200d9b85

cast call 0x3dd1Fc46c3FAf44B46733689bAb47157b530783f \
  "canSend(address,address,uint256)(bool)" \
  0x3a260e797339f4Bc822ee67A1d52cfd04719EB07 \
  0xc5eC2960Ad560AFE09602605CBCEa060244C4178 \
  90000000 \
  --rpc-url https://sepolia.gateway.tenderly.co \
  --block 0xb2ebe89dfb75e1ff3052b13f9dd672ef5d8a41c30fe208c86fa6f074200d9b85
```

Record 3 (`/review`): `POST /verify-proof` with `outputs/review_test_double_cleared.json`
/ `outputs/review_test_double_over_cap.json` → `review_response.proof.event`
(free, no auth) — do not trust the self-report in the review body.

### Files (Part 2)

| file | role |
|---|---|
| `contracts/MinimalERC7943TestDouble.sol` | ERC-7943-shaped test double, `blocked` flag, real `transfer()` |
| `contracts/MinimalComplianceProvider.sol` | always-eligible `IComplianceProvider` test double |
| `contracts/foundry.toml` | scoped forge project (src=".") so `forge build`/`create` don't pick up unrelated repo files |
| `testnet_keys.json` | throwaway deployer/principal/agent keys, Sepolia only, published for reproducibility |
| `compose_with_test_double.py` | deploy, EIP-712 sign+submit grantMandate, exercise both cases |
| `exercise_as_agent.py` | re-run the venue leg with the agent (not deployer) as `tx.from` |
| `add_review_record.py` | fetch real tx details, add Record 3 (`/review` + `/verify-proof`) on top |
| `outputs/test_double_deploy.json` | deployed contract addresses |
| `outputs/test_double_composition.json` | both cases, all three records, pinned-reproduce block hashes |
| `outputs/review_test_double_cleared.json` / `review_test_double_over_cap.json` | full `/review` request + body |
