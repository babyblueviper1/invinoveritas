#!/usr/bin/env python3
"""Three independently verifiable records around one real ERC-8226 Sepolia tx.

Record 1 — RAMS mandate: AgentMandate.canExecute(...) at a pinned block.
Record 2 — asset transfer-compliance: whatever GatedUSDRams actually exposes
           (verified Sourcify ABI/source — not assumed ERC-7943 canSend/canReceive).
Record 3 — invinoveritas /review judgment on the same transfer (sign+seed),
           independently confirmed at /verify-proof.

Not ERC-8226 spec text. Not a mock. Historical eth_call is pinned to the
transaction's block hash (EIP-1898) when the answering RPC supports it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx
from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "outputs"

CHAIN_ID = 11155111
AGENT_MANDATE = to_checksum_address("0xD68E1bb972cA4EF7F5764FBf6d685a6DfC26778e")
GATED_USD_RAMS = to_checksum_address("0xd501D68214503Fa03B5179F556029CD15D7f7cAa")
COMPLIANCE_ADAPTER = to_checksum_address("0x7302C8ee3E3f53cD85E0BAF1bDe8479DD19575EB")
DELEGATION_MIRROR = to_checksum_address("0x415e267C3C2B1835667b4aDda731599a4B847A3b")

TX_GRANT = "0xe5dfe2fbf900d41e0122743bf7a36ab7c4b1bfdd4aa82af6ee3a9ebd9b78ec54"
TX_CLEARED = "0x796a690853f9c79b71c6dd52892c9e42da447eac9a08fca7329528236869ec6c"
TX_BLOCKED = "0xdfd1877a8e5fed2c910f9ec0bcab93c8409d015ff38ea2cb80feb40931f51d74"

# Archive-capable first (publicnode has pruned this height). Receipts work on both.
RPCS = [
    "https://sepolia.gateway.tenderly.co",
    "https://rpc.sepolia.ethpandaops.io",
    "https://ethereum-sepolia-rpc.publicnode.com",
]
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; invinoveritas-demo/1.0)",
    "Content-Type": "application/json",
}

# IERC20.transferFrom.selector left-padded to bytes32 — GatedUSDRams.ACTION_TRANSFER_FROM
ACTION_TRANSFER_FROM = bytes.fromhex("23b872dd") + b"\x00" * 28

CP_REASONS = {
    0: "COMPLIANT",
    1: "KYC_EXPIRED",
    2: "AML_FLAG",
    3: "NOT_ACCREDITED",
    4: "NOT_QUALIFIED",
    5: "JURISDICTION_BLOCKED",
    6: "IDENTITY_NOT_FOUND",
    7: "ATTESTATION_REVOKED",
    8: "OTHER",
}

MANDATE_TYPES = [
    "address", "uint48", "uint48", "address", "bool", "address",
    "bytes32", "address", "uint256", "uint256", "uint256", "bytes32",
]
MANDATE_NAMES = [
    "agent", "validFrom", "validUntil", "principal", "revoked",
    "complianceProvider", "identityRef", "asset",
    "maxTransactionValue", "maxCumulativeValue", "cumulativeUsed", "metadata",
]

REVIEW_API = "http://127.0.0.1:8000/review"
VERIFY_API = "http://127.0.0.1:8000/verify-proof"

CONTEXT = (
    "ERC-8226 three-record composition (standalone demo, NOT spec text). "
    "Thamer Dridi (ERC-8226 editor, eth-magicians t/28208 #20) asked for an "
    "implementation demonstrating the mandate check, the asset's "
    "transfer-compliance check, and independently verifiable records around "
    "the same transaction, tested against the current Sepolia deployment. "
    "This /review is OUR judgment layer on whether the transfer itself is "
    "reasonable given the stated on-chain facts. It is not part of ERC-8226 "
    "and cannot change canExecute's result."
)
CONCERNS = (
    "Sepolia testnet — no mainnet value; GatedUSDRams is a demo 6-decimal "
    "token with a faucet, not a production regulated asset; canSend/canReceive "
    "are absent on this deployment so the asset-compliance record is the "
    "functions the token actually exposes (canTransfer + live checkPrincipal), "
    "not the ERC-7943 pair the rationale names; a single successful transferFrom "
    "does not speak to counterparty identity, purpose, or pattern; RAMS "
    "authorization is not contextual soundness."
)


def selector(sig: str) -> bytes:
    return keccak(text=sig)[:4]


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


def canonicalize(obj) -> bytes:
    def _reject(o, path="$"):
        if isinstance(o, float) and not isinstance(o, bool):
            raise ValueError(f"{path}: float not allowed")
        if isinstance(o, dict):
            for k, v in o.items():
                _reject(v, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                _reject(v, f"{path}[{i}]")
    _reject(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fingerprint(obj) -> str:
    return "sha256:" + hashlib.sha256(canonicalize(obj)).hexdigest()


class Rpc:
    def __init__(self, urls: list[str]):
        self.urls = list(urls)
        self.answered_by: str | None = None

    def call(self, method: str, params, timeout: float = 30):
        last = None
        for url in self.urls:
            try:
                r = httpx.post(
                    url, headers=UA,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    timeout=timeout,
                )
                r.raise_for_status()
                body = r.json()
                if "error" in body:
                    last = RuntimeError(f"{url}: {body['error']}")
                    continue
                self.answered_by = url
                # prefer a working archive url next time
                if url != self.urls[0]:
                    self.urls.remove(url)
                    self.urls.insert(0, url)
                return body.get("result")
            except Exception as e:
                last = e
                continue
        raise RuntimeError(f"{method} failed on every RPC: {last}")

    def eth_call(self, to: str, data: str, block_hash: str, block_number: int) -> dict:
        """Prefer EIP-1898 hash pin; fall back to number + hash cross-check."""
        payload = {"to": to, "data": data}
        hash_err = None
        try:
            raw = self.call(
                "eth_call",
                [payload, {"blockHash": block_hash, "requireCanonical": True}],
            )
            return {
                "result": raw,
                "block_param_form": "hash",
                "block_hash": block_hash,
                "block_number": block_number,
                "answered_by": self.answered_by,
            }
        except Exception as e:
            hash_err = str(e)
        raw = self.call("eth_call", [payload, hex(block_number)])
        blk = self.call("eth_getBlockByNumber", [hex(block_number), False])
        got = (blk or {}).get("hash")
        if got and got.lower() != block_hash.lower():
            raise RuntimeError(
                f"block hash mismatch at {block_number}: expected {block_hash} got {got}"
            )
        return {
            "result": raw,
            "block_param_form": "number",
            "block_hash": block_hash,
            "block_number": block_number,
            "answered_by": self.answered_by,
            "hash_form_error": hash_err,
        }


def _addr(word: bytes | str) -> str:
    if isinstance(word, str):
        return to_checksum_address(word)
    return to_checksum_address("0x" + word[-20:].hex() if len(word) > 20 else "0x" + word.hex())


def decode_transfer_from(input_hex: str) -> dict:
    raw = bytes.fromhex(input_hex.removeprefix("0x"))
    if raw[:4] != bytes.fromhex("23b872dd"):
        raise ValueError(f"not transferFrom selector: 0x{raw[:4].hex()}")
    frm, to, amount = decode(["address", "address", "uint256"], raw[4:])
    return {"from": _addr(frm), "to": _addr(to), "amount": int(amount)}


def decode_mandate(data_hex: str) -> dict:
    vals = decode(MANDATE_TYPES, bytes.fromhex(data_hex.removeprefix("0x")))
    out = {}
    for name, val in zip(MANDATE_NAMES, vals):
        if name in ("identityRef", "metadata"):
            out[name] = "0x" + val.hex()
        elif name in ("agent", "principal", "complianceProvider", "asset"):
            out[name] = _addr(val)
        else:
            out[name] = int(val) if not isinstance(val, bool) else bool(val)
    return out


def b32_reason(raw: bytes) -> str:
    return raw.rstrip(b"\x00").decode("ascii", errors="replace")


def fetch_tx(rpc: Rpc, tx_hash: str) -> dict:
    tx = rpc.call("eth_getTransactionByHash", [tx_hash])
    rcpt = rpc.call("eth_getTransactionReceipt", [tx_hash])
    if not tx or not rcpt:
        raise RuntimeError(f"missing tx/receipt for {tx_hash}")
    block_number = int(rcpt["blockNumber"], 16)
    block_hash = rcpt["blockHash"]
    block = rpc.call("eth_getBlockByHash", [block_hash, False])
    parent_hash = block["parentHash"]
    parent = rpc.call("eth_getBlockByHash", [parent_hash, False])
    parent_number = int(parent["number"], 16)
    decoded = None
    if (tx.get("input") or "").startswith("0x23b872dd"):
        decoded = decode_transfer_from(tx["input"])
    return {
        "hash": tx_hash,
        "from": _addr(tx["from"]),
        "to": _addr(tx["to"]) if tx.get("to") else None,
        "block_number": block_number,
        "block_hash": block_hash,
        "parent_number": parent_number,
        "parent_hash": parent_hash,
        "status": int(rcpt["status"], 16),
        "gas_used": int(rcpt["gasUsed"], 16),
        "input": tx["input"],
        "logs": [
            {
                "address": _addr(lg["address"]),
                "topics": lg.get("topics") or [],
                "data": lg.get("data"),
            }
            for lg in (rcpt.get("logs") or [])
        ],
        "transferFrom": decoded,
        "answered_by": rpc.answered_by,
    }


def view_call(rpc: Rpc, to: str, sig: str, types: list[str], args: list, outs: list[str],
              block_hash: str, block_number: int) -> dict:
    data = "0x" + selector(sig).hex() + (encode(types, args).hex() if types else "")
    raw = rpc.eth_call(to, data, block_hash, block_number)
    decoded = None
    if raw.get("result") and raw["result"] != "0x":
        decoded = decode(outs, bytes.fromhex(raw["result"].removeprefix("0x")))
        if len(decoded) == 1:
            decoded = decoded[0]
    return {**raw, "signature": sig, "to": to, "calldata": data, "decoded": decoded}


def jsonable(v):
    if isinstance(v, bytes):
        return "0x" + v.hex()
    if isinstance(v, tuple):
        return [jsonable(x) for x in v]
    return v


def collect_onchain(rpc: Rpc, case: dict, amount: int) -> dict:
    """Pinned reads. Pre-state = parent block (authorization for THIS action).
    At-tx-block = post-state of the transaction's block (eth_call-at-N)."""
    agent = case["from"]
    decoded = case["transferFrom"]
    principal = decoded["from"]
    dest = decoded["to"]
    pins = {
        "pre": (case["parent_hash"], case["parent_number"]),
        "at_tx_block": (case["block_hash"], case["block_number"]),
    }
    out: dict = {"pins": {}, "mandate": {}, "asset": {}, "diagnostic": {}}
    for label, (bh, bn) in pins.items():
        gm = view_call(
            rpc, AGENT_MANDATE, "getMandate(address,address)",
            ["address", "address"], [agent, principal],
            MANDATE_TYPES, bh, bn,
        )
        mandate = decode_mandate(gm["result"]) if gm.get("result") and gm["result"] != "0x" else None
        ce = view_call(
            rpc, AGENT_MANDATE, "canExecute(address,address,address,bytes32,uint256)",
            ["address", "address", "address", "bytes32", "uint256"],
            [agent, principal, GATED_USD_RAMS, ACTION_TRANSFER_FROM, amount],
            ["bool"], bh, bn,
        )
        ct = view_call(
            rpc, GATED_USD_RAMS, "canTransfer(address,address,uint256)",
            ["address", "address", "uint256"], [principal, dest, amount],
            ["bool"], bh, bn,
        )
        identity_ref = bytes.fromhex(mandate["identityRef"][2:]) if mandate else b"\x00" * 32
        provider = mandate["complianceProvider"] if mandate else COMPLIANCE_ADAPTER
        cp = view_call(
            rpc, provider, "checkPrincipal(address,bytes32)",
            ["address", "bytes32"], [principal, identity_ref],
            ["bool", "uint8", "uint48"], bh, bn,
        )
        ctb = view_call(
            rpc, GATED_USD_RAMS, "canTransferBy(address,address,uint256)",
            ["address", "address", "uint256"], [agent, principal, amount],
            ["bool", "bytes32"], bh, bn,
        )
        diag = view_call(
            rpc, GATED_USD_RAMS, "ramsDiagnose(address,address,uint256)",
            ["address", "address", "uint256"], [agent, principal, amount],
            ["bytes32"], bh, bn,
        )
        registered = view_call(
            rpc, DELEGATION_MIRROR, "isRegistered(address)",
            ["address"], [principal], ["bool"], bh, bn,
        )
        out["pins"][label] = {
            "block_hash": bh, "block_number": bn,
            "block_param_form": ce["block_param_form"],
            "answered_by": ce["answered_by"],
        }
        out["mandate"][label] = {
            "function": "canExecute(address,address,address,bytes32,uint256)",
            "contract": AGENT_MANDATE,
            "args": {
                "agent": agent, "principal": principal, "asset": GATED_USD_RAMS,
                "action": "0x" + ACTION_TRANSFER_FROM.hex(),
                "amount": amount,
            },
            "allowed": bool(ce["decoded"]),
            "returns": "bool  # still the pre-PR bare bool; ExecutionReason not deployed",
            "calldata": ce["calldata"],
            "raw": ce["result"],
            "getMandate": mandate,
        }
        cp_dec = cp["decoded"]
        out["asset"][label] = {
            "note": (
                "GatedUSDRams does NOT implement ERC-7943 canSend()/canReceive() "
                "(verified Sourcify source, supportsInterface deliberately omits "
                "IERC7943Fungible). Transfer-compliance as actually implemented:"
            ),
            "canSend_exists": False,
            "canReceive_exists": False,
            "canTransfer": {
                "function": "canTransfer(address,address,uint256)",
                "contract": GATED_USD_RAMS,
                "meaning": (
                    "Inherited from GatedUSD. Thin wrapper over DelegationMirror."
                    "checkTransfer for a registered sender; `to` is unused. "
                    "This is the VAR sender leash, not ERC-7943 canSend/canReceive."
                ),
                "allowed": bool(ct["decoded"]),
                "calldata": ct["calldata"],
                "raw": ct["result"],
                "from_is_registered_in_mirror": bool(registered["decoded"]),
            },
            "checkPrincipal": {
                "function": "checkPrincipal(address,bytes32)",
                "contract": provider,
                "meaning": (
                    "Live eligibility re-check the token runs on transferFrom "
                    "when a mandate exists (closes the grant-time-only gap). "
                    "This is the closest on-chain analogue of 'the asset's own "
                    "transfer-level compliance' on this deployment."
                ),
                "eligible": bool(cp_dec[0]) if cp_dec else None,
                "reason_code": int(cp_dec[1]) if cp_dec else None,
                "reason": CP_REASONS.get(int(cp_dec[1])) if cp_dec else None,
                "expiresAt": int(cp_dec[2]) if cp_dec else None,
                "calldata": cp["calldata"],
                "raw": cp["result"],
            },
        }
        ctb_dec = ctb["decoded"]
        out["diagnostic"][label] = {
            "note": (
                "canTransferBy mixes RAMS + checkPrincipal + VAR. Useful as a "
                "pre-flight; not used as Record 2 because it collapses the "
                "separation this demo exists to show. ramsDiagnose is the "
                "token's off-chain-readable why for the bare canExecute bool "
                "(not the future ExecutionReason return)."
            ),
            "canTransferBy_ok": bool(ctb_dec[0]) if ctb_dec else None,
            "canTransferBy_reason": b32_reason(ctb_dec[1]) if ctb_dec else None,
            "ramsDiagnose": b32_reason(diag["decoded"]) if diag.get("decoded") is not None else None,
            "canTransferBy_calldata": ctb["calldata"],
            "ramsDiagnose_calldata": diag["calldata"],
        }
    return out


def artifact_text(case: dict, onchain: dict, label: str) -> str:
    tf = case["transferFrom"]
    pre = onchain["mandate"]["pre"]
    m = pre["getMandate"] or {}
    asset_pre = onchain["asset"]["pre"]
    amt = tf["amount"]
    return (
        f"REAL SEPOLIA TESTNET TRANSFER — not mainnet value.\n"
        f"underlying_tx={case['hash']}\n"
        f"chain_id={CHAIN_ID} block={case['block_number']} "
        f"block_hash={case['block_hash']} status={case['status']} "
        f"(1=success, 0=reverted).\n"
        f"GatedUSDRams.transferFrom from={tf['from']} to={tf['to']} "
        f"amount={amt} ({amt / 1_000_000:.6f} gUSD, 6 decimals).\n"
        f"initiator/agent (tx.from)={case['from']}.\n"
        f"RAMS registry={AGENT_MANDATE}. "
        f"canExecute(agent, principal=from, asset=GatedUSDRams, "
        f"action=bytes32(transferFrom.selector), amount) at parent block "
        f"{case['parent_number']} (pre-state of this tx) = {pre['allowed']}. "
        f"Still a bare bool (ExecutionReason PR not deployed).\n"
        f"Mandate maxTransactionValue={m.get('maxTransactionValue')} "
        f"maxCumulativeValue={m.get('maxCumulativeValue')} "
        f"cumulativeUsed_pre={m.get('cumulativeUsed')} "
        f"revoked={m.get('revoked')} "
        f"validFrom={m.get('validFrom')} validUntil={m.get('validUntil')}.\n"
        f"Asset compliance as actually implemented (no canSend/canReceive): "
        f"canTransfer(from,to,amount)={asset_pre['canTransfer']['allowed']}; "
        f"checkPrincipal(principal, identityRef) eligible="
        f"{asset_pre['checkPrincipal']['eligible']} "
        f"reason={asset_pre['checkPrincipal']['reason']}.\n"
        f"Question: given only these stated on-chain facts, is this specific "
        f"transfer a reasonable action? This judgment is not a RAMS "
        f"authorization result and does not authorize a further transfer."
    )


def run_review(text: str) -> dict:
    env_hl = _load_env(REPO / ".env.hl")
    env_root = _load_env(REPO / ".env")
    bearer = (env_hl.get("HL_REVIEW_BEARER") or "").strip()
    auth_used = "HL_REVIEW_BEARER"
    if not bearer or bearer.startswith("ivv_SIMULATED"):
        raise SystemExit("no HL_REVIEW_BEARER")
    req = {
        "artifact": text,
        "artifact_type": "onchain_action",
        "context": CONTEXT,
        "concerns": CONCERNS,
        "severity_threshold": "all",
        "sign": True,
        "seed": True,
    }
    print(f"POST {REVIEW_API}")
    r = httpx.post(REVIEW_API, json=req, headers={"Authorization": f"Bearer {bearer}"}, timeout=90)
    if r.status_code == 402:
        alt = (env_root.get("OPERATOR_FULL_API_KEY") or "").strip()
        if alt:
            print("HL_REVIEW_BEARER 402; retrying OPERATOR_FULL_API_KEY")
            auth_used = "OPERATOR_FULL_API_KEY (HL_REVIEW_BEARER 402)"
            r = httpx.post(REVIEW_API, json=req, headers={"Authorization": f"Bearer {alt}"}, timeout=90)
    if r.status_code != 200:
        raise SystemExit(f"/review {r.status_code}: {r.text[:800]}")
    body = r.json()
    event = ((body.get("proof") or {}).get("event")) or {}
    print(f"POST {VERIFY_API}")
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
        "auth_used": auth_used,
        "review_request": req,
        "review_response": body,
        "verify_proof": vj,
        "verdict": body.get("verdict"),
        "confidence": body.get("confidence"),
        "decision_ref": decision_ref,
        "proof_event_id": event.get("id"),
        "verify_valid": vj.get("valid"),
    }


def compose_case(rpc: Rpc, name: str, tx_hash: str, do_review: bool) -> dict:
    print(f"== {name} {tx_hash}")
    case = fetch_tx(rpc, tx_hash)
    tf = case["transferFrom"]
    print(f"   block={case['block_number']} status={case['status']} "
          f"from={tf['from']} to={tf['to']} amount={tf['amount']}")
    onchain = collect_onchain(rpc, case, tf["amount"])
    print(f"   canExecute pre={onchain['mandate']['pre']['allowed']} "
          f"at_tx={onchain['mandate']['at_tx_block']['allowed']}")
    print(f"   canTransfer pre={onchain['asset']['pre']['canTransfer']['allowed']} "
          f"checkPrincipal={onchain['asset']['pre']['checkPrincipal']['reason']}")
    print(f"   ramsDiagnose pre={onchain['diagnostic']['pre']['ramsDiagnose']}")
    facts = {
        "case": name,
        "tx": {
            "hash": case["hash"],
            "from": case["from"],
            "to": case["to"],
            "block_number": case["block_number"],
            "block_hash": case["block_hash"],
            "parent_number": case["parent_number"],
            "parent_hash": case["parent_hash"],
            "status": case["status"],
            "transferFrom": tf,
        },
        "record_1_rams_mandate": onchain["mandate"],
        "record_2_asset_compliance": onchain["asset"],
        "diagnostic_mixed_preflight": onchain["diagnostic"],
        "pins": onchain["pins"],
    }
    facts["facts_fingerprint"] = fingerprint({
        k: facts[k] for k in (
            "case", "tx", "record_1_rams_mandate", "record_2_asset_compliance",
        )
    })
    record3 = None
    if do_review:
        text = artifact_text(case, onchain, name)
        record3 = run_review(text)
        print(f"   /review verdict={record3['verdict']!r} "
              f"conf={record3['confidence']} valid={record3['verify_valid']}")
        print(f"   decision_ref={record3['decision_ref']}")
    return {
        "investigation": {
            "canExecute_signature_on_chain":
                "canExecute(address,address,address,bytes32,uint256) -> (bool)",
            "canExecute_is_bare_bool": True,
            "canSend_on_GatedUSDRams": False,
            "canReceive_on_GatedUSDRams": False,
            "canTransfer_on_GatedUSDRams":
                "canTransfer(address,address,uint256) -> (bool)  # inherited, VAR mirror",
            "canTransferBy_on_GatedUSDRams":
                "canTransferBy(address,address,uint256) -> (bool,bytes32)  # mixed layers",
            "checkPrincipal_on_adapter":
                "checkPrincipal(address,bytes32) -> (bool,uint8,uint48)",
            "sourcify": {
                "AgentMandate": f"https://sourcify.dev/server/v2/contract/{CHAIN_ID}/{AGENT_MANDATE}",
                "GatedUSDRams": f"https://sourcify.dev/server/v2/contract/{CHAIN_ID}/{GATED_USD_RAMS}",
            },
        },
        "facts": facts,
        "record_3_review": record3,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-review", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rpc = Rpc(RPCS)
    head = int(rpc.call("eth_blockNumber", []), 16)
    print(f"sepolia head={head} via {rpc.answered_by}")

    cleared = compose_case(rpc, "cleared", TX_CLEARED, do_review=not args.skip_review)
    blocked = compose_case(rpc, "blocked", TX_BLOCKED, do_review=not args.skip_review)

    package = {
        "title": "ERC-8226 three-record composition",
        "chain_id": CHAIN_ID,
        "contracts": {
            "AgentMandate": AGENT_MANDATE,
            "GatedUSDRams": GATED_USD_RAMS,
            "VARComplianceProviderAdapter": COMPLIANCE_ADAPTER,
            "DelegationMirror": DELEGATION_MIRROR,
        },
        "transactions": {
            "grantMandate": TX_GRANT,
            "cleared_transferFrom": TX_CLEARED,
            "blocked_transferFrom": TX_BLOCKED,
        },
        "cleared": cleared,
        "blocked": blocked,
    }
    path = OUT / "three_records.json"
    # jsonable pass for any leftover bytes
    path.write_text(json.dumps(package, indent=2, sort_keys=True, default=jsonable) + "\n")
    print(f"wrote {path}")
    if not args.skip_review:
        for name, blob in (("cleared", cleared), ("blocked", blocked)):
            r3 = blob.get("record_3_review") or {}
            if r3.get("review_response"):
                (OUT / f"review_{name}.json").write_text(
                    json.dumps(r3, indent=2, sort_keys=True) + "\n"
                )
            if r3.get("verify_proof"):
                (OUT / f"verify_proof_{name}.json").write_text(
                    json.dumps(r3["verify_proof"], indent=2, sort_keys=True) + "\n"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
