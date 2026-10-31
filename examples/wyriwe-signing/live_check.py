#!/usr/bin/env python3
"""Live checks of the Safe binding against a real chain (standard library only).

1. digest: for an executed Safe transaction, recompute the signing digest from its execTransaction calldata and the Safe's nonce
   just before it, and compare with the digest the Safe itself emitted (ExecutionSuccess txHash: topics[1] on v1.4.x, the first
   data word on v1.3.0). Recovers the signers and checks they are owners with the threshold met.
2. execution: rebuild the block's transaction and receipt tries from eth_getRawTransactionByBlockNumberAndIndex and
   eth_getBlockReceipts, confirm both roots equal the header's (the header itself hashing to the block hash, which a SECOND RPC
   must agree on), and write the authenticated `execution` evidence (header + the two inclusion proofs) for that transaction;
   check.py's execution_proven() is then run on it, and one proof node removed / one header bit flipped must be rejected.
3. owners: prove the Safe's owner set and threshold at a block from eth_getProof (account + storage proofs) against that
   block's header, rebuilt from the RPC's fields and checked to hash to the block hash; a SECOND RPC must report the same block
   hash (the offline checker cannot know canonicity; two independent sources are the live stand-in). Compared with getOwners().

usage: python3 live_check.py digest TX_HASH  [RPC_A RPC_B]
       python3 live_check.py execution TX_HASH [RPC_A RPC_B]   (writes real_execution_proof.json)
       python3 live_check.py owners SAFE BLOCK [RPC_A RPC_B]
RPC_A must serve eth_getProof at past blocks (e.g. https://eth.drpc.org); defaults: drpc + publicnode (Ethereum mainnet).
For `execution` RPC_A must serve eth_getRawTransactionByBlockNumberAndIndex (drpc's free plan does not): its default is
publicnode, with drpc as the second.
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check as C  # noqa: E402
import mpt  # noqa: E402
import wyriwe_encoder as W  # noqa: E402

DEFAULT = ["https://eth.drpc.org", "https://ethereum-rpc.publicnode.com"]


def rpc(u, m, p):
    r = urllib.request.Request(u, json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).encode(),
                               {"Content-Type": "application/json", "User-Agent": "wyriwe-live-check"})
    d = json.loads(urllib.request.urlopen(r, timeout=30).read())
    if "result" not in d:
        raise RuntimeError(f"{m}: {d.get('error')}")
    return d["result"]


def call(u, to, sig, blk):
    return bytes.fromhex(rpc(u, "eth_call", [{"to": to, "data": "0x" + W.keccak256(sig.encode())[:4].hex()}, hex(blk)])[2:])


def owners_via_call(u, safe, blk):
    ob = call(u, safe, "getOwners()", blk); n = int.from_bytes(ob[32:64], "big")
    return ["0x" + ob[64 + 32 * i + 12:64 + 32 * i + 32].hex() for i in range(n)], int.from_bytes(call(u, safe, "getThreshold()", blk), "big")


def header_rlp(b):
    hx = lambda k: bytes.fromhex(b[k][2:]); it = lambda k: int(b[k], 16)
    f = [hx("parentHash"), hx("sha3Uncles"), hx("miner"), hx("stateRoot"), hx("transactionsRoot"), hx("receiptsRoot"), hx("logsBloom"),
         it("difficulty"), it("number"), it("gasLimit"), it("gasUsed"), it("timestamp"), hx("extraData"), hx("mixHash"), hx("nonce")]
    for k, kind in (("baseFeePerGas", "i"), ("withdrawalsRoot", "h"), ("blobGasUsed", "i"), ("excessBlobGas", "i"),
                    ("parentBeaconBlockRoot", "h"), ("requestsHash", "h")):
        if b.get(k) is not None:
            f.append(it(k) if kind == "i" else hx(k))
    return W.rlp_encode(f)


def digest(txh, a, b):
    tx, rc = rpc(a, "eth_getTransactionByHash", [txh]), rpc(a, "eth_getTransactionReceipt", [txh])
    safe, blk = tx["to"].lower(), int(tx["blockNumber"], 16)
    f, sigs = C._decode_exec(bytes.fromhex(tx["input"][2:]))
    nonce = int.from_bytes(call(a, safe, "nonce()", blk - 1), "big")
    dg = "0x" + W.safe_tx_hash(int(tx["chainId"], 16), safe, {**f, "nonce": nonce}).hex()
    ev = [l for l in rc["logs"] if l["address"].lower() == safe and l["topics"][0] in (C.EV_SUCCESS, C.EV_FAILURE)]
    emitted = [(l["topics"][1] if len(l["topics"]) > 1 else "0x" + l["data"][2:66]) for l in ev]
    signers = C._safe_signers(bytes.fromhex(dg[2:]), sigs)
    owners, thr = owners_via_call(a, safe, blk - 1)
    other = rpc(b, "eth_getBlockByNumber", [hex(blk), False])["hash"] == rpc(a, "eth_getBlockByNumber", [hex(blk), False])["hash"]
    out = {"safe": safe, "block": blk, "nonce": nonce, "recomputed_digest": dg, "emitted": emitted, "digest_matches": dg in emitted,
           "signers": signers, "signers_are_owners": all(s in owners for s in signers), "threshold": thr, "threshold_met": len(signers) >= thr,
           "second_rpc_agrees_on_block_hash": other}
    print(json.dumps(out, indent=1))
    return out["digest_matches"] and out["signers_are_owners"] and out["threshold_met"] and other


def receipt_rlp(r):
    """A receipt as the receipts trie stores it, from its JSON: type byte (if typed) || rlp([status, cumulativeGas, bloom, logs])."""
    hx = lambda v: bytes.fromhex(v[2:])
    body = W.rlp_encode([int(r["status"], 16), int(r["cumulativeGasUsed"], 16), hx(r["logsBloom"]),
                         [[hx(l["address"]), [hx(t) for t in l["topics"]], hx(l["data"])] for l in r["logs"]]])
    t = int(r.get("type") or "0x0", 16)
    return (bytes([t]) if t else b"") + body


def execution(txh, a, b):
    tx = rpc(a, "eth_getTransactionByHash", [txh])
    blk, idx = int(tx["blockNumber"], 16), int(tx["transactionIndex"], 16)
    bl = rpc(a, "eth_getBlockByNumber", [hex(blk), False]); hdr = header_rlp(bl)
    raws = []
    for i in range(len(bl["transactions"])):
        raws.append(bytes.fromhex(rpc(a, "eth_getRawTransactionByBlockNumberAndIndex", [hex(blk), hex(i)])[2:])); time.sleep(0.2)
    rcs = [receipt_rlp(r) for r in sorted(rpc(a, "eth_getBlockReceipts", [hex(blk)]), key=lambda r: int(r["transactionIndex"], 16))]
    troot, tproof = mpt.build_trie({W.rlp_encode(i): v for i, v in enumerate(raws)}, secure=False)
    rroot, rproof = mpt.build_trie({W.rlp_encode(i): v for i, v in enumerate(rcs)}, secure=False)
    h = C.rlp_decode(hdr); k = W.rlp_encode(idx)
    ex = {"block": blk, "block_hash": bl["hash"], "header_rlp": "0x" + hdr.hex(), "tx_index": idx,
          "tx_proof": ["0x" + n.hex() for n in tproof(k)], "receipt_proof": ["0x" + n.hex() for n in rproof(k)]}
    txb, status, logs = C.execution_proven(ex)
    # the digest recomputed from the PROVEN calldata and the Safe's prior nonce; the PROVEN receipt must carry its ExecutionSuccess
    safe = tx["to"].lower(); to, inp = C._tx_to_input(txb)
    f, _ = C._decode_exec(inp)
    nonce = int.from_bytes(call(b, safe, "nonce()", blk - 1), "big")
    dg = "0x" + W.safe_tx_hash(int(tx["chainId"], 16), safe, {**f, "nonce": nonce}).hex()
    bad_node = {**ex, "receipt_proof": ex["receipt_proof"][:-1]}
    flip = bytearray(hdr); flip[100] ^= 1
    rejected = []
    for name, e in (("receipt proof node removed", bad_node), ("header bit flipped", {**ex, "header_rlp": "0x" + bytes(flip).hex()})):
        try:
            C.execution_proven(e); rejected.append((name, False))
        except ValueError:
            rejected.append((name, True))
    out = {"tx": txh, "block": blk, "block_hash": bl["hash"], "tx_index": idx, "txs_in_block": len(raws),
           "header_hashes_to_block_hash": "0x" + W.keccak256(hdr).hex() == bl["hash"],
           "second_rpc_block_hash_agrees": rpc(b, "eth_getBlockByNumber", [hex(blk), False])["hash"] == bl["hash"],
           "transactionsRoot_rebuilt_equals_header": troot == h[4], "receiptsRoot_rebuilt_equals_header": rroot == h[5],
           "proven_tx_hash_equals_tx": "0x" + W.keccak256(txb).hex() == txh.lower(), "proven_status": status,
           "proven_logs": len(logs), "recomputed_digest": dg,
           "proven_receipt_has_ExecutionSuccess_for_it": to == safe and C._exec_outcome(status, logs, safe, dg) is None, "controls_rejected": dict(rejected)}
    print(json.dumps(out, indent=1))
    json.dump({"summary": out, "execution": ex}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "real_execution_proof.json"), "w"), indent=1)
    return all(v for k, v in out.items() if isinstance(v, bool)) and all(dict(rejected).values())


def owners(safe, blk, a, b):
    safe = safe.lower(); word = lambda n: n.to_bytes(32, "big")
    bl = rpc(a, "eth_getBlockByNumber", [hex(blk), False]); hdr = header_rlp(bl)
    own, thr = owners_via_call(a, safe, blk)
    chain = [C.SENTINEL] + own + [C.SENTINEL]
    keys = ["0x" + W.keccak256(word(int(x, 16)) + word(C.SAFE_OWNERS_SLOT)).hex() for x in chain[:-1]] + ["0x" + word(C.SAFE_THRESHOLD_SLOT).hex()]
    pr = rpc(a, "eth_getProof", [safe, keys, hex(blk)])
    nodes = []
    for sp in pr["storageProof"]:
        nodes += [n for n in sp["proof"] if n not in nodes]
    tr = {"kind": "owners@block", "block": blk, "block_hash": bl["hash"], "header_rlp": "0x" + hdr.hex(), "account_proof": pr["accountProof"], "storage_proof": nodes}
    got = C.safe_owners_proven(tr, safe)
    out = {"safe": safe, "block": blk, "block_hash": bl["hash"], "header_hashes_to_block_hash": "0x" + W.keccak256(hdr).hex() == bl["hash"],
           "second_rpc_block_hash_agrees": rpc(b, "eth_getBlockByNumber", [hex(blk), False])["hash"] == bl["hash"],
           "proven_owners": got[0], "proven_threshold": got[1], "matches_getOwners_getThreshold": got == (own, thr)}
    print(json.dumps(out, indent=1))
    return out["header_hashes_to_block_hash"] and out["second_rpc_block_hash_agrees"] and out["matches_getOwners_getThreshold"]


if __name__ == "__main__":
    a, b = (sys.argv[-2], sys.argv[-1]) if len(sys.argv) > 4 and sys.argv[-1].startswith("http") else DEFAULT
    if len(sys.argv) >= 3 and sys.argv[1] == "digest":
        sys.exit(0 if digest(sys.argv[2], a, b) else 1)
    if len(sys.argv) >= 3 and sys.argv[1] == "execution":
        sys.exit(0 if execution(sys.argv[2], *((a, b) if len(sys.argv) > 4 else DEFAULT[::-1])) else 1)
    if len(sys.argv) >= 4 and sys.argv[1] == "owners":
        sys.exit(0 if owners(sys.argv[2], int(sys.argv[3]), a, b) else 1)
    print(__doc__); sys.exit(2)
