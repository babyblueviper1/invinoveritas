# ERC-8299 signing-input profile: independent checker and v0 encoder (Safe)

The outside recompute of [trustless-ai/wyriwe-signing](https://github.com/trustless-ai/wyriwe-signing) PROFILE.md §9, draft 2:
four separate verdicts, never one combined pass. Python standard library only: verifying never needs us, a package or a
hosted service. CC0.

| file | what |
|---|---|
| `ENCODER.md` | the v0 encoder specification (Safe binding); its CIDv1 is the profile's `encoder_spec_cid` |
| `wyriwe_encoder.py` | reference encoder + shared primitives (keccak-256, RFC 8785 JCS, ABI, EIP-712, secp256k1 recovery, RLP) |
| `check.py` | the checker: `python3 check.py FIXTURE.json`, or `python3 check.py --vectors vectors.json` |
| `vectors.json` | 55 vectors: 5 positive, 50 negative (every test case in PROFILE.md, plus one per check) |
| `mutants.py` | mutation (removal) controls: deletes each check in turn; every deletion must change a verdict; a crash is a crash, not a kill |
| `gen_vectors.py` | builds the vectors (needs `eth_account`, `eth_abi`, `rlp`; the checker does not) |
| `live_check.py` | the Safe binding against a real chain, through two RPCs |
| `mpt.py` | a Merkle-Patricia trie builder for making proofs (generator and live check only; the checker only verifies) |
| `real_owners_proof.json` | a real owners@block proof (Ethereum mainnet) as captured |
| `replay_execution.py` | an independent replay of the mainnet execution capture, sharing no code with the checker: py-trie, pyrlp and eth-hash verify the header, both proofs, the Safe's `ExecutionSuccess` for the digest in the proven receipt, and rebuild both tries from the RPC |
| `real_execution_proof.json` | a real authenticated execution (transaction + receipt inclusion, Ethereum mainnet) as captured |

## Run it cold
```
git clone --depth 1 --filter=blob:none --sparse https://github.com/babyblueviper1/invinoveritas && cd invinoveritas
git sparse-checkout set examples/wyriwe-signing && cd examples/wyriwe-signing
sha256sum -c SHA256SUMS                    # every file as published
python3 check.py --vectors vectors.json    # exit 0 only if every vector matches AND the encoder pins check
python3 mutants.py                         # exit 0 only if every check is killed and none crashed
pip install trie==3.1.0 rlp eth-hash[pycryptodome] && python3 replay_execution.py   # optional: the mainnet capture, replayed
```
`check.py` needs `ENCODER.md` and `wyriwe_encoder.py` beside it: fetched alone, it reports the pins as NOT CHECKED and exits 1.

## Results at this commit
- `check.py --vectors vectors.json`: **55/55**. `mutants.py`: **27/27 killed, 0 survived, 0 crashed**.
- Every stdlib primitive agrees with an independent implementation (`eth_utils`, `eth_abi`, `eth_account`, `rlp`), and a second
  encoder built on `eth_abi` from ENCODER.md produces byte-identical payloads for every positive vector (test case 10). The
  reviewer-list pin, the Safe message hash and both storage-slot formulas (`signedMessages`, `approvedHashes`) are checked the same
  way against `eth_abi` / `eth_utils` before the vectors are written.
- **Real chain (Ethereum mainnet, Safe v1.4.1 `0x86f6…c49c`):** the signing digest recomputed from the `execTransaction`
  calldata and the Safe's prior nonce equals the digest the Safe emitted (tx `0xfd32578f…6b40`, block 26308347); the signer
  recovers to its owner. The owner set and threshold read from `eth_getProof` at block 26308387 (header rebuilt and hashed to the
  block hash; a second RPC reports the same hash) equal `getOwners()` / `getThreshold()`. One proof node removed, or one header
  bit flipped: rejected.
- **Real chain, authenticated execution:** for the same transaction, `live_check.py execution` rebuilt block 26308347's
  transaction and receipt tries from its 170 raw transactions and receipts; both roots equal the header's, the header hashes
  to the block hash (a second RPC agrees), and `execution_proven()` reads the transaction (its hash equals the tx hash) and a
  status-1 receipt from the proofs. That receipt carries the Safe's `ExecutionSuccess` for the digest recomputed from the proven
  calldata. One receipt-proof node removed, or one header bit flipped: rejected. `replay_execution.py`, built on the Ethereum
  Foundation's py-trie / pyrlp / eth-hash instead of our code, agrees: header hash, both proofs, both rebuilt roots, and both
  RPCs report the same hash and roots, and the proven receipt carries the Safe's `ExecutionSuccess` for the digest (a copy with
  one digest nibble changed: rejected, exit 1). Echo (Tiago Merlini) replayed the capture himself, in a fresh environment, with
  four RPCs of his own choosing: all agree, exit 0; and checked the `ExecutionSuccess` event with his own script (PR #1 review 2026-10-31).

## The four verdicts
| verdict | PASS needs | without its evidence |
|---|---|---|
| `encoded` | intent hash, encoder pipeline hash and payload hash recompute, and the pinned encoder rebuilds the payload byte for byte | encoder not available: `NOT_ESTABLISHED` |
| `reviewed` | approvals (EIP-712 `WyriweSigningInput`, ERC-8299 §4 domain) by distinct keys of an **authenticated** trust root meet its threshold; reported with the trust-root kind and the reviewer/signer overlap | `NOT_ESTABLISHED` |
| `signed` | the digest derived from the payload equals the claimed one; the transaction is `execTransaction` to the account with the payload's fields and nonce; signatures recover to strictly ascending owners meeting the threshold | no transaction: `NOT_ESTABLISHED` |
| `executed` | **authenticated** (Echo, Pavlo): the transaction bytes and its receipt proven at the same index under the transactionsRoot and receiptsRoot of a header the checker hashes (it must hash to `block_hash` and carry `block`); the proven transaction is the one `signed` judged (its hash equals the supplied `tx.hash` and `receipt.transactionHash`, its `to` and calldata equal the supplied ones); the PROVEN receipt has status 1 and the Safe's `ExecutionSuccess` for this digest (topics[1] on v1.4.x, data on v1.3.0) | receipt without proofs: `NOT_ESTABLISHED` (`rpc_data_consistent_unauthenticated`); no transaction, a hash mismatch, or a proof of another transaction: `NOT_ESTABLISHED`; `FAIL` only on a proven revert, `ExecutionFailure` or missing event |

## Trust roots (authority, not only integrity)
- **owners@block** is accepted only when **proven**: the header must hash to `block_hash` and carry `block`; the Safe's account
  proof and the storage proofs of its owners linked list (slot 2) and threshold (slot 4) must verify against it. The owners and
  threshold are **read from the proofs**; a supplied list is never trusted. Reported as fidelity, not independent review, because
  the reviewers are the signers.
- **reviewer-list@commitment** is accepted only when its pin is **recorded on-chain before the execution block**, and the checker
  proves that record itself (Echo, PR #1 review 2026-10-31, option a). `reviewerListPin = keccak256(abi.encode(keccak256("WyriweReviewerList(uint256
  chainId,address account,bytes32 listHash)"), chainId, account, listHash))`, `listHash = keccak256(JCS(list))`. The state is
  block E-1: account and storage proofs against a header the checker hashes, whose hash equals the **authenticated execution
  header's `parentHash`** (so it needs no canonicity check beyond block E's). Either record counts:
  - **Safe message:** `signedMessages[getMessageHash(abi.encode(pin))] == 1` (slot `keccak256(msgHash . 7)`), set by a Safe
    transaction delegatecalling `SignMessageLib.signMessage`; only if the same proof shows **no module enabled** (an enabled module
    can execute without owner signatures), else `reviewer_list_pin_module_possible`.
  - **Owner approvals:** `approvedHashes[owner][pin] == 1` (slot `keccak256(pin . keccak256(owner . 8))`) for at least `threshold`
    of the owners proven in the same state.

  Signatures over a message that *states* a block do not count as a prior pin, because the signers choose that number:
  `reviewer_list_prior_binding_unproven`. Safe v1.4.1 slots (`SafeStorage.sol`): 1 modules, 2 owners, 3 ownerCount, 4 threshold,
  5 nonce, 7 signedMessages, 8 approvedHashes. A content hash alone proves the list is unchanged, not that anyone with authority
  chose it.

## Limits, stated
- Offline, chain data are supplied as an RPC returns them. The checker proves owners and execution from a header but cannot know
  that the header's block is canonical: it reports `block_hash` for the consumer to confirm (`live_check.py` uses a second RPC).
- The reviewer-list pin is proven in the state of the authenticated execution header's parent, never at a supplied block number.
  Not checked here: `getMessageHash` against a live mainnet message's bytes, and the Safe v1.3.0 layout.
- `signed` takes the Safe's owners at execution as supplied (the Safe enforced them on-chain if `executed` passes); proving them
  uses the same `safe_owners_proven`.
- v0: Safe only; no arrays, tuples or batches in intents; contract (v=0) and approved-hash (v=1) Safe signatures are not counted.
- This proves fidelity (what was reviewed is what was signed and what ran), not judgment: a faithfully executed bad intent passes.
