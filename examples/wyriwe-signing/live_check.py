#!/usr/bin/env python3
"""Live checks of the Safe binding against a real chain (standard library only).

1. digest: for an executed Safe transaction, recompute the signing digest from its execTransaction calldata and the Safe's nonce
   just before it, and compare with the digest the Safe itself emitted (ExecutionSuccess txHash: topics[1] on v1.4.x, the first
   data word on v1.3.0). Recovers the signers and checks they are owners with the threshold met.
2. owners: prove the Safe's owner set and threshold at a block from eth_getProof (account + storage proofs) against that
   block's header, rebuilt from the RPC's fields and checked to hash to the block hash; a SECOND RPC must report the same block
   hash (the offline checker cannot know canonicity; two independent sources are the live stand-in). Compared with getOwners().

usage: python3 live_check.py digest TX_HASH  [RPC_A RPC_B]
       python3 live_check.py owners SAFE BLOCK [RPC_A RPC_B]
RPC_A must serve eth_getProof at past blocks (e.g. https://eth.drpc.org); defaults: drpc + publicnode (Ethereum mainnet).
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check as C  # noqa: E402
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
    if len(sys.argv) >= 4 and sys.argv[1] == "owners":
        sys.exit(0 if owners(sys.argv[2], int(sys.argv[3]), a, b) else 1)
    print(__doc__); sys.exit(2)
