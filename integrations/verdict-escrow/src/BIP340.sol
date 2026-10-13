// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.24;

/// @title BIP340 — on-chain BIP-340 (secp256k1 Schnorr) signature verification via the `ecrecover` trick.
/// @notice Verifies a BIP-340 signature `(rx, s)` over a 32-byte message `m` under an x-only public key
///         `px`, using only the native `ecrecover` precompile + the `modexp` precompile — no bespoke
///         secp256k1 EC library. This is the `valid` (signature) leg of the recovery-escrow gate; it lets
///         the contract confirm a kind-30078 invinoveritas receipt is genuinely signed WITHOUT trusting
///         any oracle (option A in IReceiptVerifier — "verify trusting no one").
///
/// HOW THE ecrecover TRICK WORKS
/// ----------------------------
/// BIP-340 verification is: `s·G = R + e·P`, i.e. `R = s·G − e·P`, where `e = H(rx‖px‖m) mod n`.
/// Ethereum's `ecrecover(h, v, r, s_ec)` recovers `Q = r⁻¹·(s_ec·R_pt − h·G)` where `R_pt` is the curve
/// point at x-coordinate `r` with Y-parity from `v`. Setting `r = px`, `v = 27` (BIP-340 keys have even Y,
/// so `R_pt = P`), `s_ec = (−e·px) mod n`, and `h = (−s·px) mod n` gives:
///     Q = px⁻¹·((−e·px)·P − (−s·px)·G) = px⁻¹·px·(s·G − e·P) = s·G − e·P = R.
/// So `ecrecover(...) == address(R)`. We then independently derive `address(R)` from the signature's `rx`
/// (lift to the even-Y point, secp256k1: y = √(x³+7) mod p, p ≡ 3 mod 4 ⇒ y = (x³+7)^((p+1)/4)) and
/// compare. Equality ⟺ the signature is valid.
///
/// LIMITATION (documented, negligible): `ecrecover` requires its `r` (here `px`) in (0, n). secp256k1 has
/// p > n, so an x-only key with x ∈ [n, p) (~2⁻¹²⁸ of keys) cannot be used as `px`; pin a normal key.
/// `rx` is NOT used as an `ecrecover` `r` (only inside keccak), so it carries no such constraint.
///
/// AUDIT STATUS: written to be auditable and tested against real noble-signed vectors (see
/// test/BIP340.t.sol). Have it independently reviewed before mainnet value flows through it.
///
/// @dev Verbatim copy from TMerlini/hack-ens-recovery contracts/src/BIP340.sol (Apache-2.0), the same
///      library already live on Sepolia (BIP340Verifier 0x7c99c52Ed86EcedD65e60482243aa882a50F3b70) and
///      end-to-end demo-verified there. Copied rather than cross-repo-imported to keep this integration
///      dependency-light (same posture as the ERC-7579 module); credit stays in this header, not erased.
library BIP340 {
    uint256 internal constant N   = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
    uint256 internal constant P   = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F;
    // (P + 1) / 4 — the sqrt exponent (valid because P ≡ 3 mod 4).
    uint256 internal constant P14 = 0x3FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFBFFFFF0C;
    // sha256("BIP0340/challenge") — the tagged-hash midstate, hashed twice as the tag prefix.
    bytes32 internal constant CHALLENGE_TAG_HASH =
        0x7bb52d7a9fef58323eb1bf7a407db382d2f3f2d81bb1224f49fe518f6d48d37c;

    /// @notice Verify BIP-340 signature `(rx, s)` over message `m` under x-only pubkey `px`. Never reverts
    ///         for malformed inputs — returns false instead. View (uses ecrecover + modexp precompiles).
    function verify(bytes32 px, bytes32 rx, bytes32 s, bytes32 m) internal view returns (bool) {
        uint256 pxu = uint256(px);
        uint256 rxu = uint256(rx);
        uint256 su  = uint256(s);

        // Domain checks. px must be a usable ecrecover `r` (in (0,N)); s in (0,N); rx a field element.
        if (pxu == 0 || pxu >= N) return false;
        if (su  == 0 || su  >= N) return false;
        if (rxu == 0 || rxu >= P) return false;

        // e = int(tagged_hash("BIP0340/challenge", rx ‖ px ‖ m)) mod N
        uint256 e = uint256(
            sha256(abi.encodePacked(CHALLENGE_TAG_HASH, CHALLENGE_TAG_HASH, rx, px, m))
        ) % N;
        if (e == 0) return false;

        // ecrecover(h = -s·px mod N, v = 27, r = px, s_ec = -e·px mod N) == address(R)
        uint256 sp = N - mulmod(su, pxu, N); // -s·px mod N  (both < N ⇒ product != 0 ⇒ sp in (0,N))
        uint256 ep = N - mulmod(e,  pxu, N); // -e·px mod N
        if (ep == 0) return false;           // ecrecover requires s_ec in (0,N)

        address recovered = ecrecover(bytes32(sp), 27, px, bytes32(ep));
        if (recovered == address(0)) return false;

        // Expected address of R = the even-Y point at x = rx.
        uint256 y2 = addmod(mulmod(mulmod(rxu, rxu, P), rxu, P), 7, P); // rx³ + 7
        uint256 ry = _modexp(y2, P14, P);                              // candidate √
        if (mulmod(ry, ry, P) != y2) return false;                    // rx is not a curve x-coord
        if (ry & 1 == 1) ry = P - ry;                                 // BIP-340: lift to even Y

        address expected = address(uint160(uint256(keccak256(abi.encodePacked(rx, bytes32(ry))))));
        return recovered == expected;
    }

    /// @dev base^power mod m via the 0x05 modexp precompile (all operands 32 bytes).
    function _modexp(uint256 base, uint256 power, uint256 m) private view returns (uint256 result) {
        assembly {
            let ptr := mload(0x40)
            mstore(ptr, 0x20)           // len(base)
            mstore(add(ptr, 0x20), 0x20) // len(exp)
            mstore(add(ptr, 0x40), 0x20) // len(mod)
            mstore(add(ptr, 0x60), base)
            mstore(add(ptr, 0x80), power)
            mstore(add(ptr, 0xa0), m)
            if iszero(staticcall(gas(), 0x05, ptr, 0xc0, ptr, 0x20)) { revert(0, 0) }
            result := mload(ptr)
        }
    }
}
