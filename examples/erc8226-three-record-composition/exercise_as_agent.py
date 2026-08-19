#!/usr/bin/env python3
"""Re-run the venue-level leg of the composed demo with the AGENT as tx.from,
transferring to the PRINCIPAL -- not a deployer self-transfer. Fixes a real
/review finding from the first pass (intent_mismatch, high severity): "The
authorized agent neither submitted the transaction nor transferred the
principal's assets, so the successful self-transfer cannot be treated as..."
Reuses the already-deployed contracts and the already-granted mandate (both
real, both on Sepolia) -- does not re-deploy or re-grant."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
KEYS = HERE / "testnet_keys.json"

RPC = "https://sepolia.gateway.tenderly.co"
AGENT_MANDATE = "0xD68E1bb972cA4EF7F5764FBf6d685a6DfC26778e"
GAS_PRICE = "1150000000"
PRIORITY_PRICE = "50000000"
ACTION_TRANSFER = "0xa9059cbb00000000000000000000000000000000000000000000000000000000"


def _load_key(name: str) -> dict:
    return json.load(open(KEYS))[name]


def cast(*args: str) -> str:
    result = subprocess.run(["cast", *args], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"cast {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def main() -> int:
    deployer = _load_key("deployer")
    principal = _load_key("principal")
    agent = _load_key("agent")

    dep = json.loads((OUT / "test_double_deploy.json").read_text())
    asset_addr = dep["asset"]

    data = json.loads((OUT / "test_double_composition.json").read_text())

    for name, amount in (("cleared", 90_000_000), ("over_cap", 150_000_000)):
        print(f"== {name} amount={amount}, agent -> principal")
        ce = cast("call", AGENT_MANDATE, "canExecute(address,address,address,bytes32,uint256)(bool)",
                   agent["address"], principal["address"], asset_addr, ACTION_TRANSFER, str(amount),
                   "--rpc-url", RPC).strip() == "true"
        cs = cast("call", asset_addr, "canSend(address,address,uint256)(bool)",
                   agent["address"], principal["address"], str(amount), "--rpc-url", RPC).strip() == "true"
        cr = cast("call", asset_addr, "canReceive(address,address,uint256)(bool)",
                   agent["address"], principal["address"], str(amount), "--rpc-url", RPC).strip() == "true"

        calldata = cast("calldata", "transfer(address,uint256)", principal["address"], str(amount))
        out = json.loads(cast("send", asset_addr, calldata, "--rpc-url", RPC,
                               "--private-key", agent["private_key"],
                               "--gas-limit", "70000", "--gas-price", GAS_PRICE,
                               "--priority-gas-price", PRIORITY_PRICE, "--json"))
        tx_hash = out["transactionHash"]
        status = int(out["status"], 16)
        log = (out.get("logs") or [None])[0]
        decoded = None
        if log and len(log["topics"]) == 3:
            decoded = {"from": "0x" + log["topics"][1][-40:], "to": "0x" + log["topics"][2][-40:],
                       "amount": int(log["data"], 16)}
        block_number = int(out["blockNumber"], 16)
        block_hash = out["blockHash"]
        print(f"   canExecute={ce} canSend={cs} canReceive={cr} tx={tx_hash} status={status} "
              f"decoded={decoded}")

        case = data["cases"][name]
        case["record_1_rams_canExecute"] = {"contract": AGENT_MANDATE, "allowed": ce,
                                             "note": "recomputed with principal as recipient (agent->principal), not a self-transfer"}
        case["record_2_asset_compliance"] = {"contract": asset_addr, "canSend": cs, "canReceive": cr}
        case["record_3_venue_execution"] = {
            "tx": tx_hash, "status": status, "block_number": block_number, "block_hash": block_hash,
            "tx_from": agent["address"], "tx_to": asset_addr,
            "decoded_transfer_event": decoded,
            "note": "tx.from is the AGENT itself (not the deployer standing in). "
                    "status=1 means the test double's OWN transfer() succeeded; it does not "
                    "consult RAMS. Compare against record_1 separately.",
        }
        case.pop("record_3_review", None)

    (OUT / "test_double_composition.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("wrote outputs/test_double_composition.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
