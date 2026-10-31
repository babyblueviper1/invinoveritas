#!/usr/bin/env python3
"""Independent replay of real_execution_proof.json -- shares NO code with check.py, mpt.py or wyriwe_encoder.py.

Trie, RLP and Keccak come from the Ethereum Foundation's py-trie (HexaryTrie), pyrlp and eth-hash:
  pip install trie==3.1.0 rlp eth-hash[pycryptodome]
1. the captured header hashes to the captured block hash, and every RPC given reports that block hash and the same
   transactionsRoot / receiptsRoot;
2. the captured tx and receipt proofs verify under those roots (HexaryTrie.get_from_proof) at rlp(tx_index), and the
   proven transaction hashes to the transaction;
3. the block's transaction and receipt tries, rebuilt with HexaryTrie from the RPC's raw transactions and receipts, have
   the header's roots.
usage: python3 replay_execution.py [real_execution_proof.json] [RPC ...]   (default RPCs: publicnode, drpc)
"""
import json
import sys
import time
import urllib.request

import rlp
from eth_hash.auto import keccak
from trie import HexaryTrie

RPCS = ["https://ethereum-rpc.publicnode.com", "https://eth.drpc.org"]


def rpc(u, m, p):
    r = urllib.request.Request(u, json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": p}).encode(),
                               {"Content-Type": "application/json", "User-Agent": "wyriwe-replay"})
    d = json.loads(urllib.request.urlopen(r, timeout=30).read())
    if "result" not in d:
        raise RuntimeError(f"{m}: {d.get('error')}")
    return d["result"]


def b(x):
    return bytes.fromhex(x[2:])


def receipt_bytes(r):
    body = rlp.encode([int(r["status"], 16), int(r["cumulativeGasUsed"], 16), b(r["logsBloom"]),
                       [[b(l["address"]), [b(t) for t in l["topics"]], b(l["data"])] for l in r["logs"]]])
    t = int(r.get("type") or "0x0", 16)
    return (bytes([t]) if t else b"") + body


def main():
    args = sys.argv[1:]
    path = args.pop(0) if args and not args[0].startswith("http") else "real_execution_proof.json"
    rpcs = args or RPCS
    cap = json.load(open(path)); ex, txh = cap["execution"], cap["summary"]["tx"]
    hdr = b(ex["header_rlp"]); h = rlp.decode(hdr)
    out = {"header_hashes_to_block_hash": "0x" + keccak(hdr).hex() == ex["block_hash"]}
    blk = ex["block"]
    for u in rpcs:
        j = rpc(u, "eth_getBlockByNumber", [hex(blk), False])
        out[f"{u} agrees (hash, transactionsRoot, receiptsRoot)"] = (j["hash"] == ex["block_hash"] and b(j["transactionsRoot"]) == h[4]
                                                                      and b(j["receiptsRoot"]) == h[5])
    key = rlp.encode(ex["tx_index"])
    txb = HexaryTrie.get_from_proof(h[4], key, [rlp.decode(b(n)) for n in ex["tx_proof"]])
    rcb = HexaryTrie.get_from_proof(h[5], key, [rlp.decode(b(n)) for n in ex["receipt_proof"]])
    out["tx proof verifies, proven tx hashes to the transaction"] = bool(txb) and "0x" + keccak(txb).hex() == txh.lower()
    r = rlp.decode(rcb[1:] if rcb[0] < 0x80 else rcb)
    out["receipt proof verifies, status"] = int.from_bytes(r[0], "big") if rcb else None
    # rebuild both tries from the first RPC (it must serve eth_getRawTransactionByBlockNumberAndIndex)
    n = len(rpc(rpcs[0], "eth_getBlockByNumber", [hex(blk), False])["transactions"])
    tt, rt = HexaryTrie({}), HexaryTrie({})
    for i in range(n):
        tt[rlp.encode(i)] = b(rpc(rpcs[0], "eth_getRawTransactionByBlockNumberAndIndex", [hex(blk), hex(i)])); time.sleep(0.2)
    for rc in rpc(rpcs[0], "eth_getBlockReceipts", [hex(blk)]):
        rt[rlp.encode(int(rc["transactionIndex"], 16))] = receipt_bytes(rc)
    out[f"transactionsRoot rebuilt from {n} txs equals header"] = tt.root_hash == h[4]
    out["receiptsRoot rebuilt equals header"] = rt.root_hash == h[5]
    print(json.dumps(out, indent=1))
    sys.exit(0 if all(v in (True, 1) for v in out.values()) else 1)


if __name__ == "__main__":
    main()
