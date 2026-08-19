// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

/// @notice Minimal IComplianceProvider test double. Exists ONLY to satisfy
/// AgentMandate.grantMandate's checkPrincipal(principal, identityRef) call
/// for a throwaway demo principal that has no real KYC/AML registration
/// anywhere -- always reports eligible. NOT a compliance system; do not
/// read this as evidence about any real principal's eligibility.
contract MinimalComplianceProvider {
    function checkPrincipal(address, bytes32)
        external
        pure
        returns (bool eligible, uint8 reasonCode, uint48 expiresAt)
    {
        return (true, 0, type(uint48).max);
    }
}
