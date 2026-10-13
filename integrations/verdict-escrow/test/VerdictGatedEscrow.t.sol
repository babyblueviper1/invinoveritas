// SPDX-License-Identifier: MIT
pragma solidity ^0.8.23;

import "forge-std/Test.sol";
import {VerdictGatedEscrow, IERC20} from "../src/VerdictGatedEscrow.sol";

contract MockUSDC {
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    function mint(address to, uint256 a) external { balanceOf[to] += a; }
    function approve(address s, uint256 a) external returns (bool) { allowance[msg.sender][s] = a; return true; }
    function transfer(address to, uint256 a) external returns (bool) {
        require(balanceOf[msg.sender] >= a, "bal"); balanceOf[msg.sender] -= a; balanceOf[to] += a; return true;
    }
    function transferFrom(address f, address to, uint256 a) external returns (bool) {
        require(allowance[f][msg.sender] >= a && balanceOf[f] >= a, "allow"); allowance[f][msg.sender] -= a;
        balanceOf[f] -= a; balanceOf[to] += a; return true;
    }
}

contract VerdictGatedEscrowTest is Test {
    MockUSDC usdc;
    VerdictGatedEscrow esc;
    address payer = address(0xA11CE);
    address payee = address(0xB0B);
    bytes32 constant RESULT = sha256("pay 1.00 USDC to 0xB0B for: market data feed, October");
    bytes32 constant TD = sha256("policy: payments <= 5 USDC to allow-listed data vendors only");
    bytes32 constant DREF = keccak256("decision_ref");
    uint256 id;

    function _py(string[] memory a) internal returns (bytes memory) {
        string[] memory c = new string[](a.length + 2);
        c[0] = "python3"; c[1] = "test/sign.py";
        for (uint256 i = 0; i < a.length; i++) c[i + 2] = a[i];
        return vm.ffi(c);
    }

    function _pub() internal returns (bytes32) {
        string[] memory a = new string[](1); a[0] = "pubkey";
        return bytes32(_py(a));
    }

    function _sign(bytes32 digest) internal returns (bytes memory) {
        string[] memory a = new string[](2); a[0] = "sign"; a[1] = vm.toString(digest);
        return _py(a);
    }

    function setUp() public {
        usdc = new MockUSDC();
        esc = new VerdictGatedEscrow(IERC20(address(usdc)), _pub());
        usdc.mint(payer, 10e6);
        vm.startPrank(payer);
        usdc.approve(address(esc), 1e6);
        id = esc.fund(bytes32("s1"), payee, 1e6, RESULT, TD, 1, uint64(block.timestamp + 1 days));
        vm.stopPrank();
    }

    function test_digest_matches_the_server_signer_byte_for_byte() public {
        string[] memory a = new string[](9);
        a[0] = "relaydigest"; a[1] = vm.toString(block.chainid); a[2] = vm.toString(address(esc)); a[3] = vm.toString(id);
        a[4] = "7"; a[5] = "1"; a[6] = vm.toString(RESULT); a[7] = vm.toString(TD); a[8] = vm.toString(DREF);
        assertEq(bytes32(_py(a)), esc.releaseDigest(id, 7, DREF), "contract digest != services/verdict_relay.digest");
    }

    function test_approving_verdict_releases_to_the_payee_once() public {
        bytes memory sig = _sign(esc.releaseDigest(id, 7, DREF));
        vm.prank(address(0xCAFE));                       // anyone may submit it
        esc.release(id, 7, DREF, sig);
        assertEq(usdc.balanceOf(payee), 1e6);
        assertEq(usdc.balanceOf(address(esc)), 0);
        vm.expectRevert(VerdictGatedEscrow.NotFunded.selector);
        esc.release(id, 7, DREF, sig);                   // single use
    }

    function test_no_verdict_no_release_and_funds_stay_held() public {
        vm.expectRevert(VerdictGatedEscrow.BadVerdict.selector);
        esc.release(id, 7, DREF, new bytes(64));
        assertEq(usdc.balanceOf(address(esc)), 1e6);
    }

    function test_a_reject_ruling_cannot_release() public {
        // the relay signs reject as approved=false; that digest differs in the approved word, so it never verifies here
        bytes32 rejectDigest = sha256(abi.encode(esc.DOMAIN_TAG(), block.chainid, address(esc), address(esc), id, uint256(7),
            uint256(1), RESULT, TD, uint256(0), DREF));
        bytes memory sig = _sign(rejectDigest);
        vm.expectRevert(VerdictGatedEscrow.BadVerdict.selector);
        esc.release(id, 7, DREF, sig);
    }

    function test_an_approval_for_another_request_policy_or_escrow_cannot_release() public {
        // different decision_ref, submission or escrow id -> a different digest
        bytes memory other = _sign(esc.releaseDigest(id, 8, DREF));
        vm.expectRevert(VerdictGatedEscrow.BadVerdict.selector);
        esc.release(id, 7, DREF, other);
        bytes memory otherRef = _sign(esc.releaseDigest(id, 7, keccak256("another decision")));
        vm.expectRevert(VerdictGatedEscrow.BadVerdict.selector);
        esc.release(id, 7, DREF, otherRef);
        // a second escrow with a different request: the first escrow's approval does not move it
        vm.startPrank(payer);
        usdc.approve(address(esc), 1e6);
        uint256 id2 = esc.fund(bytes32("s2"), payee, 1e6, sha256("pay 1.00 USDC for something else"), TD, 1, uint64(block.timestamp + 1 days));
        vm.stopPrank();
        bytes memory sig1 = _sign(esc.releaseDigest(id, 7, DREF));
        vm.expectRevert(VerdictGatedEscrow.BadVerdict.selector);
        esc.release(id2, 7, DREF, sig1);
    }

    function test_refund_only_after_the_deadline_and_never_after_release() public {
        vm.expectRevert(VerdictGatedEscrow.TooEarly.selector);
        esc.refund(id);
        vm.warp(block.timestamp + 1 days);
        esc.refund(id);
        assertEq(usdc.balanceOf(payer), 10e6);
        bytes memory sig = _sign(esc.releaseDigest(id, 7, DREF));
        vm.expectRevert(VerdictGatedEscrow.NotFunded.selector);
        esc.release(id, 7, DREF, sig);
    }

    function test_ids_are_per_payer_so_nobody_can_squat() public {
        assertTrue(esc.escrowId(payer, bytes32("s1")) != esc.escrowId(address(0xBAD), bytes32("s1")));
        vm.prank(payer);
        usdc.approve(address(esc), 1e6);
        uint64 ra = uint64(block.timestamp + 1 days);
        bytes32 r = RESULT; bytes32 t = TD;      // computed via the sha256 precompile: do it BEFORE prank (a precompile call consumes it)
        bytes memory data = abi.encodeCall(esc.fund, (bytes32("s1"), payee, 1e6, r, t, 1, ra));
        vm.prank(payer);
        (bool ok, bytes memory ret) = address(esc).call(data);
        assertFalse(ok, "re-funding an existing id must revert");
        assertEq(bytes4(ret), VerdictGatedEscrow.AlreadyExists.selector);
    }
}
