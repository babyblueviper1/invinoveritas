# ERC-8299 signing-input profile: encoder specification v0 (Safe)

**Status:** reference encoder for the profile's v0 scope (PROFILE.md §3-§4, trustless-ai/wyriwe-signing draft 2). CC0.
Pinned by the CIDv1 (raw, sha2-256) of this file's exact bytes; that `ipfs://` string is the profile's `encoder_spec_cid`.

## 1. Scope
One account binding: the **Safe** (v1.3.0 and later: `getTransactionHash` over the EIP-712 `SafeTx` struct, executed with
`execTransaction`). ERC-4337 and EIP-7702 are out of scope for v0. Arrays, tuples and batched calls (MultiSend) are out of
scope; an intent that needs them is refused, never encoded approximately.

## 2. Input
The intent of PROFILE.md §2, exactly these members: `chainId` (positive JSON integer), `account` (lowercase 0x address of the
Safe), `target` (lowercase 0x address), `value` (decimal string, wei), `function` (canonical signature, or `""` for a plain value
transfer), `args` (array of `{type, value}`), `operation` (`"call"` or `"delegatecall"`), `nonce` (decimal string; REQUIRED for
the Safe, the Safe's nonce the action is pinned to). Any other member, a missing member, or a malformed value is refused.

## 3. Intent to SafeTx fields
| SafeTx field | value |
|---|---|
| `to` | `target` |
| `value` | `value` as an integer |
| `data` | `""` (empty) if `function` is `""`; otherwise `keccak256(function)[0:4] ‖ abi.encode(args types, args values)` |
| `operation` | `0` for `call`, `1` for `delegatecall` |
| `safeTxGas`, `baseGas`, `gasPrice` | `0` |
| `gasToken`, `refundReceiver` | the zero address |
| `nonce` | `nonce` as an integer |

`function` MUST be `name(type1,type2,...)` with no spaces, and its types MUST equal the `args` types in order. v0 argument
types: `address`, `bool`, `uint8`..`uint256`, `int8`..`int256` (multiples of 8), `bytes1`..`bytes32`, `bytes`, `string`.
Canonical JSON values: integers as decimal strings, addresses and bytes as lowercase `0x` hex (fixed-size bytes of exactly the
stated length), `bool` as a JSON boolean, `string` as a JSON string (UTF-8). The ABI encoding is standard Solidity head/tail.

Gas refunds are fixed at zero so the signed call carries no refund path an attacker could redirect; a flow that needs them is
outside v0.

## 4. Hashes
- `intent_hash = keccak256(JCS(intent))`, JCS = RFC 8785.
- `encoder_pipeline_hash = keccak256(utf8(encoder_spec_cid) ‖ intent_hash)`, the `ipfs://` prefix included.
- `payload_hash = keccak256(payload)`.

## 5. Payload
`payload = abi.encode(address to, uint256 value, bytes data, uint8 operation, uint256 safeTxGas, uint256 baseGas,
uint256 gasPrice, address gasToken, address refundReceiver, uint256 nonce)`: the SafeTx fields in the Safe's own order.

## 6. Signing digest (Safe binding)
`signing_digest = keccak256(0x19 ‖ 0x01 ‖ domainSeparator ‖ keccak256(SAFE_TX_TYPEHASH ‖ to ‖ value ‖ keccak256(data) ‖
operation ‖ safeTxGas ‖ baseGas ‖ gasPrice ‖ gasToken ‖ refundReceiver ‖ nonce))`, each value as a 32-byte ABI word, with
`domainSeparator = keccak256(keccak256("EIP712Domain(uint256 chainId,address verifyingContract)") ‖ chainId ‖ account)` and
`SAFE_TX_TYPEHASH = keccak256("SafeTx(address to,uint256 value,bytes data,uint8 operation,uint256 safeTxGas,uint256 baseGas,
uint256 gasPrice,address gasToken,address refundReceiver,uint256 nonce)")`: what Safe v1.3.0+ `getTransactionHash` returns.

## 7. Reference implementation
`wyriwe_encoder.py` (Python standard library only), `encode(intent) -> (payload, info)`.
sha256 of the reference implementation: **`b2a5a32f780fdff4467d26149037249fcdd69856489fc4ef880221c06299baee`**

Every primitive in it (keccak-256, ABI encoding, both EIP-712 digests, secp256k1 recovery) is cross-checked against
`eth_utils`, `eth_abi` and `eth_account` by `gen_vectors.py`, and vector set 10 requires a second, independent encoder
(built on `eth_abi`) to produce identical payloads for every positive vector.
