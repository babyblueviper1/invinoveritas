// SPDX-License-Identifier: MIT
pragma solidity ^0.8.29;

/// @notice ERC-7943-shaped test double for the ERC-8226 composed three-layer
/// worked example (eth-magicians t/28208, post #25). NOT a full compliant
/// token, NOT the ERC-7943 canonical interface ID, NOT wired to RAMS at all
/// -- canSend/canReceive answer independently of AgentMandate, exactly as an
/// integrator would query them: a separate source, not a check baked into
/// the mandate registry. `blocked` is the one knob that flips both branches.
interface IERC7943Minimal {
    function canSend(address from, address to, uint256 amount) external view returns (bool);
    function canReceive(address from, address to, uint256 amount) external view returns (bool);
}

contract MinimalERC7943TestDouble is IERC7943Minimal {
    address public immutable owner;
    bool public blocked;
    mapping(address => uint256) public balanceOf;

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event BlockedSet(bool blocked);

    constructor() {
        owner = msg.sender;
        balanceOf[msg.sender] = 1_000_000 * 1e6; // 6 decimals, same shape as the gUSD demo token
    }

    function setBlocked(bool b) external {
        require(msg.sender == owner, "not owner");
        blocked = b;
        emit BlockedSet(b);
    }

    function canSend(address, address, uint256) external view returns (bool) {
        return !blocked;
    }

    function canReceive(address, address, uint256) external view returns (bool) {
        return !blocked;
    }

    /// @notice Real, mutating venue-level action. Gated ONLY by this
    /// contract's own `blocked` flag -- independent of AgentMandate.canExecute,
    /// which is checked separately off-chain by the composing script, not here.
    function transfer(address to, uint256 amount) external returns (bool) {
        require(!blocked, "asset: blocked");
        require(balanceOf[msg.sender] >= amount, "insufficient balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }

    function supportsInterface(bytes4 interfaceId) external pure returns (bool) {
        return interfaceId == type(IERC7943Minimal).interfaceId || interfaceId == 0x01ffc9a7;
    }
}
