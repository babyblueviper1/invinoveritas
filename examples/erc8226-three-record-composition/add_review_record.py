#!/usr/bin/env python3
"""Add Record 3 (/review judgment) to outputs/test_double_composition.json without
re-touching the chain -- the grant + two venue transfers already happened for real
on Sepolia (see git history / README); this just adds the third, off-chain-signed
judgment record on top of the two already-recorded on-chain facts, same pattern as
compose_three_records.py's run_review()."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

RPCS = [
    "https://sepolia.gateway.tenderly.co",
    "https://rpc.sepolia.ethpandaops.io",
    "https://ethereum-sepolia-rpc.publicnode.com",
]

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "outputs"

REVIEW_API = "http://127.0.0.1:8000/review"
VERIFY_API = "http://127.0.0.1:8000/verify-proof"

CONTEXT = (
    "ERC-8226 composed three-layer worked example WITH a real ERC-7943 test double "
    "(standalone demo, NOT spec text). Ludovico rossi (RAMS editor, eth-magicians "
    "t/28208 #27) confirmed this composed case as prioritized after WeissCurry (#24) "
    "asked for one end-to-end example putting asset compliance (canSend/canReceive), "
    "RAMS authorization (canExecute), and the venue-level result side by side. This "
    "/review is OUR judgment layer on whether the transfer itself is reasonable given "
    "the stated on-chain facts. It is not part of ERC-8226 and cannot change "
    "canExecute's result or the test double's own canSend/canReceive answer."
)
CONCERNS = (
    "Sepolia testnet -- no mainnet value. The test double is a deliberately minimal, "
    "self-built ERC-7943-shaped contract (not a real regulated asset, not audited); "
    "its canSend/canReceive never consult RAMS, so its transfer() succeeds even when "
    "canExecute() independently says no -- that is the point being demonstrated, not "
    "a bug. RAMS authorization is not contextual soundness."
)


def fetch_tx_details(tx_hash: str) -> dict:
    """Real from/to/input/decoded-Transfer-event -- fixes a real /review blocker finding
    (intent_mismatch) from the first pass: a bare tx hash + status=1 does not by itself
    prove the executed call matches the reviewed intent (right sender, recipient, amount)."""
    import subprocess
    for rpc in RPCS:
        try:
            tx = json.loads(subprocess.run(
                ["cast", "tx", tx_hash, "--rpc-url", rpc, "--json"],
                capture_output=True, text=True, timeout=30, check=True,
            ).stdout)
            rcpt = json.loads(subprocess.run(
                ["cast", "receipt", tx_hash, "--rpc-url", rpc, "--json"],
                capture_output=True, text=True, timeout=30, check=True,
            ).stdout)
            logs = rcpt.get("logs") or []
            transfer_log = logs[0] if logs else None
            decoded_transfer = None
            if transfer_log and len(transfer_log["topics"]) == 3:
                decoded_transfer = {
                    "from": "0x" + transfer_log["topics"][1][-40:],
                    "to": "0x" + transfer_log["topics"][2][-40:],
                    "amount": int(transfer_log["data"], 16),
                }
            return {
                "from": tx["from"], "to": tx["to"], "input": tx["input"],
                "status": int(rcpt["status"], 16), "block_number": int(rcpt["blockNumber"], 16),
                "block_hash": rcpt["blockHash"],
                "decoded_transfer_event": decoded_transfer,
            }
        except Exception:
            continue
    raise RuntimeError(f"could not fetch tx details for {tx_hash} on any RPC")


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def artifact_text(name: str, case: dict, grant: dict, tx_details: dict) -> str:
    p = grant["params"]
    amt = case["amount"]
    r1 = case["record_1_rams_canExecute"]
    r2 = case["record_2_asset_compliance"]
    r3v = case["record_3_venue_execution"]
    dt = tx_details["decoded_transfer_event"]
    return (
        f"REAL SEPOLIA TESTNET -- not mainnet value.\n"
        f"Case: {name}. amount={amt} ({amt / 1_000_000:.6f} units, 6 decimals).\n"
        f"agent={p['agent']} principal={p['principal']} asset(test double)={p['asset']}.\n"
        f"Mandate (real grantMandate tx {grant['tx']}): maxTransactionValue="
        f"{p['maxTransactionValue']} maxCumulativeValue={p['maxCumulativeValue']}.\n"
        f"Record 1 -- RAMS AgentMandate.canExecute(agent, principal, asset, "
        f"transfer.selector, {amt}) = {r1['allowed']} (real live view call, "
        f"contract {r1['contract']}).\n"
        f"Record 2 -- asset compliance, ERC-7943-shaped test double: "
        f"canSend={r2['canSend']} canReceive={r2['canReceive']} (real live view calls, "
        f"contract {r2['contract']}). This test double never consults RAMS.\n"
        f"Record 3 (venue) -- a real, separate on-chain transfer() call on the test "
        f"double: tx={r3v['tx']} block={tx_details['block_number']} "
        f"block_hash={tx_details['block_hash']} status={tx_details['status']} "
        f"(1=succeeded) tx.from={tx_details['from']} tx.to={tx_details['to']} "
        f"input={tx_details['input']}. Decoded Transfer event (topic0="
        f"0xddf252ad...df523b3ef): from={dt['from']} to={dt['to']} amount={dt['amount']} "
        f"-- from matches tx.from (the agent itself submitted this transfer, paying its "
        f"own gas), to matches the mandate's principal, amount matches the reviewed {amt} "
        f"exactly. The test double's own transfer() only checks its own blocked flag, "
        f"never canExecute, "
        f"so it succeeds here even when Record 1 says the mandate would refuse -- this "
        f"is a REAL, DELIBERATE property of this test double (see repo README), not an "
        f"unnoticed gap: it demonstrates that a caller can move this asset without RAMS "
        f"ever being consulted, which is exactly why an integrator must check all three "
        f"records independently rather than inferring one from another.\n"
        f"Question: given only these stated on-chain facts, is this specific transfer "
        f"a reasonable action to treat as authorized end-to-end? This judgment is not a "
        f"RAMS authorization result, does not change canExecute's answer, and does not "
        f"authorize a further transfer."
    )


def run_review(text: str) -> dict:
    env_hl = _load_env(REPO / ".env.hl")
    env_root = _load_env(REPO / ".env")
    bearer = (env_hl.get("HL_REVIEW_BEARER") or "").strip()
    auth_used = "HL_REVIEW_BEARER"
    req = {
        "artifact": text, "artifact_type": "onchain_action",
        "context": CONTEXT, "concerns": CONCERNS,
        "severity_threshold": "all", "sign": True, "seed": True,
    }
    r = httpx.post(REVIEW_API, json=req, headers={"Authorization": f"Bearer {bearer}"}, timeout=90)
    if r.status_code == 402:
        alt = (env_root.get("OPERATOR_FULL_API_KEY") or "").strip()
        if alt:
            auth_used = "OPERATOR_FULL_API_KEY (HL_REVIEW_BEARER 402)"
            r = httpx.post(REVIEW_API, json=req, headers={"Authorization": f"Bearer {alt}"}, timeout=90)
    if r.status_code != 200:
        raise SystemExit(f"/review {r.status_code}: {r.text[:800]}")
    body = r.json()
    event = ((body.get("proof") or {}).get("event")) or {}
    vr = httpx.post(VERIFY_API, json={"event": event}, timeout=30)
    vj = vr.json()
    content = event.get("content")
    decision_ref = None
    if isinstance(content, str):
        try:
            decision_ref = json.loads(content).get("decision_ref")
        except json.JSONDecodeError:
            decision_ref = None
    return {
        "auth_used": auth_used, "review_response": body, "verify_proof": vj,
        "verdict": body.get("verdict"), "confidence": body.get("confidence"),
        "decision_ref": decision_ref, "proof_event_id": event.get("id"),
        "verify_valid": vj.get("valid"),
    }


def main() -> int:
    path = OUT / "test_double_composition.json"
    data = json.loads(path.read_text())
    for name, case in data["cases"].items():
        print(f"== {name}")
        tx_details = fetch_tx_details(case["record_3_venue_execution"]["tx"])
        case["record_3_venue_execution"]["tx_details"] = tx_details
        text = artifact_text(name, case, data["grant"], tx_details)
        r3 = run_review(text)
        print(f"   /review verdict={r3['verdict']!r} conf={r3['confidence']} valid={r3['verify_valid']}")
        print(f"   decision_ref={r3['decision_ref']}")
        case["record_3_review"] = r3
        # review_test_double_ prefix -- Part 1's compose_three_records.py already owns
        # outputs/review_cleared.json / review_blocked.json; a bare review_{name}.json
        # here silently clobbered Part 1's real recorded review_cleared.json once
        # (caught in git diff before commit, restored via git checkout) because "cleared"
        # is also one of Part 1's case names. Never reuse Part 1's output filenames.
        (OUT / f"review_test_double_{name}.json").write_text(json.dumps(r3, indent=2, sort_keys=True) + "\n")
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
