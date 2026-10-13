// SPDX-License-Identifier: MIT
pragma solidity ^0.8.23;

import {BIP340} from "./BIP340.sol";

interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

/// @title VerdictGatedEscrow
/// @notice Holds a token payment and releases it to the payee ONLY when an independent verdict approving that
///         exact payment is presented on-chain: a BIP-340 signature by the configured verifier key over the
///         invinoveritas verdict-relay v2 digest. Without an approval the payer can take the funds back after
///         `refundAfter`. The payer cannot pay through this contract without the verdict, and nobody can redirect
///         the payment: payee, amount, the reviewed request and the policy are fixed when the escrow is funded.
///
/// Digest (byte-identical to services/verdict_relay.py `digest`, signed by POST /review with `verdict_relay`):
///   sha256(abi.encode(DOMAIN_TAG, chainid, authority, task_contract, token_id, submission_id, task_version,
///                     result_hash, td_hash, approved, decision_ref))
/// with authority = task_contract = this contract, token_id = the escrow id, approved = 1.
///   result_hash = sha256 of the exact payment request document the verdict reviewed (payee, amount, purpose);
///   td_hash     = sha256 of the policy document it was judged against.
/// The relay only signs a clean `approve` (approve_with_concerns and reject get no signature), so a rejected or
/// qualified review can never move the funds.
///
/// What a release establishes: the configured verifier key approved this exact request under this exact policy,
/// bound to a ledger-recomputable decision_ref. It does not establish that the verdict was right, or anything about
/// what the payee delivers afterwards.
contract VerdictGatedEscrow {
    bytes32 public constant DOMAIN_TAG = sha256("invinoveritas/verdict-relay/v2");

    IERC20 public immutable token;
    bytes32 public immutable verifierPubkey;   // BIP-340 x-only key of the independent verifier

    enum State { None, Funded, Released, Refunded }

    struct Escrow {
        address payer;
        address payee;
        uint256 amount;
        bytes32 resultHash;
        bytes32 tdHash;
        uint64 taskVersion;
        uint64 refundAfter;
        State state;
    }

    mapping(uint256 => Escrow) public escrows;

    event Funded(uint256 indexed id, address indexed payer, address indexed payee, uint256 amount, bytes32 resultHash, bytes32 tdHash, uint64 refundAfter);
    event Released(uint256 indexed id, address indexed payee, uint256 amount, uint256 submissionId, bytes32 decisionRef);
    event Refunded(uint256 indexed id, address indexed payer, uint256 amount);

    error NotFunded();
    error AlreadyExists();
    error BadVerdict();
    error TooEarly();
    error TransferFailed();
    error BadInput();

    constructor(IERC20 token_, bytes32 verifierPubkey_) {
        token = token_;
        verifierPubkey = verifierPubkey_;
    }

    /// @notice The escrow id for a payer and salt. Ids are derived from the payer so nobody can squat on another payer's id.
    function escrowId(address payer, bytes32 salt) public pure returns (uint256) {
        return uint256(keccak256(abi.encode(payer, salt)));
    }

    function fund(bytes32 salt, address payee, uint256 amount, bytes32 resultHash, bytes32 tdHash, uint64 taskVersion, uint64 refundAfter)
        external
        returns (uint256 id)
    {
        if (payee == address(0) || amount == 0 || resultHash == bytes32(0) || tdHash == bytes32(0)) revert BadInput();
        id = escrowId(msg.sender, salt);
        if (escrows[id].state != State.None) revert AlreadyExists();
        escrows[id] = Escrow(msg.sender, payee, amount, resultHash, tdHash, taskVersion, refundAfter, State.Funded);
        if (!token.transferFrom(msg.sender, address(this), amount)) revert TransferFailed();
        emit Funded(id, msg.sender, payee, amount, resultHash, tdHash, refundAfter);
    }

    /// @notice The digest the verifier must have signed for `id` to be released (approved = true).
    function releaseDigest(uint256 id, uint256 submissionId, bytes32 decisionRef) public view returns (bytes32) {
        Escrow storage e = escrows[id];
        return sha256(abi.encode(DOMAIN_TAG, block.chainid, address(this), address(this), id, submissionId,
                                 uint256(e.taskVersion), e.resultHash, e.tdHash, uint256(1), decisionRef));
    }

    /// @notice Anyone may submit the approving verdict; the funds can only go to the payee fixed at funding.
    function release(uint256 id, uint256 submissionId, bytes32 decisionRef, bytes calldata sig) external {
        Escrow storage e = escrows[id];
        if (e.state != State.Funded) revert NotFunded();
        if (sig.length != 64) revert BadVerdict();
        if (!BIP340.verify(verifierPubkey, bytes32(sig[0:32]), bytes32(sig[32:64]), releaseDigest(id, submissionId, decisionRef))) {
            revert BadVerdict();
        }
        e.state = State.Released;
        if (!token.transfer(e.payee, e.amount)) revert TransferFailed();
        emit Released(id, e.payee, e.amount, submissionId, decisionRef);
    }

    /// @notice With no approving verdict, the payer takes the funds back once `refundAfter` has passed.
    function refund(uint256 id) external {
        Escrow storage e = escrows[id];
        if (e.state != State.Funded) revert NotFunded();
        if (block.timestamp < e.refundAfter) revert TooEarly();
        e.state = State.Refunded;
        if (!token.transfer(e.payer, e.amount)) revert TransferFailed();
        emit Refunded(id, e.payer, e.amount);
    }
}
