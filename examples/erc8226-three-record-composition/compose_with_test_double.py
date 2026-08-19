#!/usr/bin/env python3
"""ERC-8226 composed three-layer worked example WITH a real ERC-7943 test double.

Real gap this closes: compose_three_records.py's live deployment (GatedUSDRams)
does not implement ERC-7943 canSend()/canReceive() at all (verified, documented
there). WeissCurry (eth-magicians t/28208 #24) asked for one end-to-end example
that puts asset compliance (canSend/canReceive), RAMS authorization (canExecute),
and the venue-level result side by side. Ludovico rossi (RAMS editor, #27)
confirmed: "yes, treat the composed case as prioritized."

This script deploys a small, deliberately minimal, configurable ERC-7943 test
double (contracts/MinimalERC7943TestDouble.sol) and a minimal IComplianceProvider
test double (contracts/MinimalComplianceProvider.sol, needed only to satisfy
grantMandate's checkPrincipal requirement for a throwaway demo principal with no
real KYC/AML registration anywhere), grants a REAL mandate on the REAL, live,
already-deployed AgentMandate registry (permissionless -- grantMandate just needs
an EIP-712 signature from the named principal, verified against source pulled
from Sourcify), and runs two real on-chain scenarios.

IMPORTANT design note, stated plainly because it changes what "blocked" means
here vs the original compose_three_records.py: the test double does NOT call
out to AgentMandate at all -- canSend/canReceive answer independently, and its
transfer() only checks its own `blocked` flag, never RAMS. This is the more
demonstrative case, not a weaker one: it shows what actually happens in an
architecture where the asset has ZERO RAMS awareness, which is a real,
common case an integrator must handle -- the venue-level transfer SUCCEEDS on
this test double even when RAMS's canExecute() independently says no, because
nothing here makes the asset consult the mandate. "Blocked" therefore means
"RAMS refuses to authorize this," not "the transaction reverted." Do not read
a status=1 receipt on the over-cap case as RAMS approval.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_checksum_address

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "outputs"
KEYS = HERE / "testnet_keys.json"
FORGE_PROJECT = HERE / "contracts"

CHAIN_ID = 11155111
AGENT_MANDATE = to_checksum_address("0xD68E1bb972cA4EF7F5764FBf6d685a6DfC26778e")

RPCS = [
    "https://sepolia.gateway.tenderly.co",
    "https://rpc.sepolia.ethpandaops.io",
    "https://ethereum-sepolia-rpc.publicnode.com",
]

REVIEW_API = "http://127.0.0.1:8000/review"
VERIFY_API = "http://127.0.0.1:8000/verify-proof"

# Explicit, deliberately modest gas price -- forge's own auto-estimate defaults to a
# ~2x-base-fee safety multiplier, which repeatedly failed the pre-flight balance check
# against a thinly-funded throwaway testnet deployer even though the ACTUAL charge
# (base+priority actually used) would have been lower. Sepolia gas is stable; a small
# explicit buffer over the observed ~1.08 gwei base fee is enough and keeps faucet
# rounds to a minimum.
GAS_PRICE = "1150000000"       # 1.15 gwei
PRIORITY_PRICE = "50000000"    # 0.05 gwei

# transfer(address,uint256) selector, left-padded to bytes32 -- same convention
# ACTION_TRANSFER_FROM used in compose_three_records.py for transferFrom.selector.
ACTION_TRANSFER = keccak(text="transfer(address,uint256)")[:4] + b"\x00" * 28

MAX_TX_VALUE = 100_000_000     # 100 units, 6 decimals -- same shape as the gUSD demo
MAX_CUM_VALUE = 500_000_000

CANEXEC_ABI = {
    "name": "canExecute",
    "types": ["address", "address", "address", "bytes32", "uint256"],
    "out": ["bool"],
}


def _load_key(name: str) -> dict:
    return json.load(open(KEYS))[name]


def _rpc_call(method: str, params: list, timeout: float = 30):
    last = None
    for url in RPCS:
        try:
            r = httpx.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=timeout)
            r.raise_for_status()
            body = r.json()
            if "error" in body:
                last = RuntimeError(f"{url}: {body['error']}")
                continue
            return body.get("result"), url
        except Exception as e:
            last = e
    raise RuntimeError(f"{method} failed on every RPC: {last}")


def cast(*args: str) -> str:
    result = subprocess.run(["cast", *args], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"cast {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def deploy(contract_path: str, contract_name: str, pk: str, gas_limit: int) -> str:
    result = subprocess.run(
        ["forge", "create", f"{contract_path}:{contract_name}",
         "--rpc-url", RPCS[0], "--private-key", pk, "--broadcast",
         "--gas-limit", str(gas_limit), "--gas-price", GAS_PRICE, "--priority-gas-price", PRIORITY_PRICE],
        cwd=FORGE_PROJECT, capture_output=True, text=True, timeout=120,
    )
    out = result.stdout + result.stderr
    print(out)
    if result.returncode != 0:
        raise RuntimeError(f"deploy {contract_name} failed")
    for line in out.splitlines():
        if line.startswith("Deployed to:"):
            return to_checksum_address(line.split(":", 1)[1].strip())
    raise RuntimeError(f"could not parse deployed address from:\n{out}")


def eip712_sign_grant(principal_pk: str, params: dict, nonce: int) -> bytes:
    domain = {"name": "RAMS", "version": "1", "chainId": CHAIN_ID, "verifyingContract": AGENT_MANDATE}
    types = {
        "GrantMandate": [
            {"name": "agent", "type": "address"},
            {"name": "validFrom", "type": "uint48"},
            {"name": "validUntil", "type": "uint48"},
            {"name": "principal", "type": "address"},
            {"name": "complianceProvider", "type": "address"},
            {"name": "identityRef", "type": "bytes32"},
            {"name": "asset", "type": "address"},
            {"name": "maxTransactionValue", "type": "uint256"},
            {"name": "maxCumulativeValue", "type": "uint256"},
            {"name": "metadata", "type": "bytes32"},
            {"name": "actions", "type": "bytes32[]"},
            {"name": "nonce", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
        ],
    }
    message = {**params, "nonce": nonce}
    signable = encode_typed_data(domain_data=domain, message_types=types, message_data=message)
    acct = Account.from_key(principal_pk)
    signed = acct.sign_message(signable)
    return signed.signature


def grant_mandate(deployer_pk: str, params: dict, signature: bytes) -> str:
    # cast calldata wants a tuple parameter as ONE parenthesized literal, not N
    # positional args spread across the call (confirmed empirically -- passing 13
    # separate args for a (12-field-tuple, bytes) signature raises "expected 2
    # types, got 13").
    actions_arg = "[" + ",".join("0x" + a.hex() for a in params["actions"]) + "]"
    tuple_arg = (
        f"({params['agent']},{params['validFrom']},{params['validUntil']},{params['principal']},"
        f"{params['complianceProvider']},0x{params['identityRef'].hex()},{params['asset']},"
        f"{params['maxTransactionValue']},{params['maxCumulativeValue']},"
        f"0x{params['metadata'].hex()},{actions_arg},{params['deadline']})"
    )
    calldata = cast(
        "calldata",
        "grantMandate((address,uint48,uint48,address,address,bytes32,address,uint256,uint256,bytes32,bytes32[],uint256),bytes)",
        tuple_arg, "0x" + signature.hex(),
    )
    txh = cast("send", AGENT_MANDATE, calldata, "--rpc-url", RPCS[0], "--private-key", deployer_pk,
               "--gas-limit", "400000", "--gas-price", GAS_PRICE, "--priority-gas-price", PRIORITY_PRICE,
               "--json")
    return json.loads(txh)["transactionHash"]


def send_raw(to: str, calldata: str, pk: str, gas_limit: str = "200000") -> dict:
    out = cast("send", to, calldata, "--rpc-url", RPCS[0], "--private-key", pk,
               "--gas-limit", gas_limit, "--gas-price", GAS_PRICE, "--priority-gas-price", PRIORITY_PRICE,
               "--json")
    return json.loads(out)


def call_view(to: str, sig: str, args: list[str]) -> str:
    return cast("call", to, sig, *args, "--rpc-url", RPCS[0])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-deploy", action="store_true", help="reuse addresses in outputs/test_double_deploy.json")
    ap.add_argument("--skip-review", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    deployer = _load_key("deployer")
    principal = _load_key("principal")
    agent = _load_key("agent")
    print(f"deployer={deployer['address']} principal={principal['address']} agent={agent['address']}")

    deploy_path = OUT / "test_double_deploy.json"
    if args.skip_deploy and deploy_path.exists():
        dep = json.loads(deploy_path.read_text())
        asset_addr = dep["asset"]
        cp_addr = dep["compliance_provider"]
    else:
        print("== deploying MinimalERC7943TestDouble")
        asset_addr = deploy("MinimalERC7943TestDouble.sol", "MinimalERC7943TestDouble",
                             deployer["private_key"], 700_000)
        print(f"   asset={asset_addr}")
        print("== deploying MinimalComplianceProvider")
        cp_addr = deploy("MinimalComplianceProvider.sol", "MinimalComplianceProvider",
                          deployer["private_key"], 300_000)
        print(f"   compliance_provider={cp_addr}")
        deploy_path.write_text(json.dumps({"asset": asset_addr, "compliance_provider": cp_addr}, indent=2))

    nonce_raw, _ = _rpc_call("eth_call", [
        {"to": AGENT_MANDATE, "data": "0x7ecebe00" + principal["address"][2:].rjust(64, "0")},
        "latest",
    ])
    principal_nonce = int(nonce_raw, 16)
    print(f"principal nonce on AgentMandate = {principal_nonce}")

    now = int(time.time())
    grant_params = {
        "agent": to_checksum_address(agent["address"]),
        "validFrom": now - 60,
        "validUntil": now + 7 * 24 * 3600,
        "principal": to_checksum_address(principal["address"]),
        "complianceProvider": cp_addr,
        "identityRef": b"\x00" * 32,
        "asset": asset_addr,
        "maxTransactionValue": MAX_TX_VALUE,
        "maxCumulativeValue": MAX_CUM_VALUE,
        "metadata": b"\x00" * 32,
        "actions": [ACTION_TRANSFER],
        "deadline": now + 3600,
    }
    print("== signing GrantMandate (EIP-712, principal key, no gas needed)")
    sig = eip712_sign_grant(principal["private_key"], grant_params, principal_nonce)
    print(f"   sig={sig.hex()[:20]}...")

    print("== submitting grantMandate (deployer pays gas, relaying principal's signature)")
    grant_tx = grant_mandate(deployer["private_key"], grant_params, sig)
    print(f"   tx={grant_tx}")

    results = {"deploy": {"asset": asset_addr, "compliance_provider": cp_addr},
               "grant": {"tx": grant_tx, "params": {k: (v.hex() if isinstance(v, bytes) else
                         [x.hex() for x in v] if isinstance(v, list) else v)
                         for k, v in grant_params.items()}},
               "cases": {}}

    for name, amount in (("cleared", 90_000_000), ("over_cap", 150_000_000)):
        print(f"== case {name} amount={amount}")
        # Record 1: RAMS canExecute, real live view call against the real registry
        ce_out = call_view(AGENT_MANDATE,
                            "canExecute(address,address,address,bytes32,uint256)(bool)",
                            [grant_params["agent"], grant_params["principal"], asset_addr,
                             "0x" + ACTION_TRANSFER.hex(), str(amount)])
        can_execute = ce_out.strip() == "true"
        # Record 2: asset compliance, real live view calls against the test double
        cs_out = call_view(asset_addr, "canSend(address,address,uint256)(bool)",
                            [deployer["address"], deployer["address"], str(amount)])
        cr_out = call_view(asset_addr, "canReceive(address,address,uint256)(bool)",
                            [deployer["address"], deployer["address"], str(amount)])
        can_send = cs_out.strip() == "true"
        can_receive = cr_out.strip() == "true"
        # Record 3 (venue): real mutating transfer on the test double. Deployer holds
        # the full initial supply and pays its own gas -- see module docstring for why
        # this is NOT gated by canExecute (the test double never calls RAMS).
        calldata = cast("calldata", "transfer(address,uint256)", deployer["address"], str(amount))
        tx = send_raw(asset_addr, calldata, deployer["private_key"])
        receipt_status, _ = _rpc_call("eth_getTransactionReceipt", [tx["transactionHash"]])
        status = int(receipt_status["status"], 16) if receipt_status else None
        print(f"   canExecute={can_execute} canSend={can_send} canReceive={can_receive} "
              f"venue_tx={tx['transactionHash']} status={status}")
        results["cases"][name] = {
            "amount": amount,
            "record_1_rams_canExecute": {"contract": AGENT_MANDATE, "allowed": can_execute},
            "record_2_asset_compliance": {"contract": asset_addr, "canSend": can_send, "canReceive": can_receive},
            "record_3_venue_execution": {"tx": tx["transactionHash"], "status": status,
                                          "note": "status=1 means the test double's OWN transfer() succeeded; "
                                                   "it does not consult RAMS. Compare against record_1 separately."},
        }

    path = OUT / "test_double_composition.json"
    path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
