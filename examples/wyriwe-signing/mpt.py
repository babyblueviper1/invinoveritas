#!/usr/bin/env python3
"""A minimal Merkle-Patricia trie BUILDER (standard library only), for making proofs: gen_vectors.py (synthetic state, transaction
and receipt tries) and live_check.py (a real block's transaction and receipt tries, rebuilt and checked against its header).
The checker never needs it: check.py only VERIFIES proofs (mpt_get).

secure=True hashes keys with keccak-256 (Ethereum's state and storage tries); secure=False uses the key as is (the transaction
and receipt tries, keyed by rlp(index)).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wyriwe_encoder as W  # noqa: E402


def _nib(b: bytes):
    return [x for c in b for x in (c >> 4, c & 15)]


def _hp(nibs, leaf):
    f = (2 if leaf else 0) + (len(nibs) % 2)
    ns = [f] + ([] if len(nibs) % 2 else [0]) + list(nibs)
    return bytes(ns[i] * 16 + ns[i + 1] for i in range(0, len(ns), 2))


def _decode(b: bytes):
    import check as C  # the checker's own RLP decoder
    return C.rlp_decode(b)


def build_trie(kv: dict, secure: bool = True):
    """Returns (root, proof(key) -> list of node bytes from the root down)."""
    db = {}
    items = sorted(((W.keccak256(k) if secure else k), v) for k, v in kv.items())
    items = [(_nib(k), v) for k, v in items]

    def ref(node):
        enc = W.rlp_encode(node)
        if len(enc) < 32:
            return node
        h = W.keccak256(enc); db[h] = enc
        return h

    def build(its, d):
        if len(its) == 1:
            return [_hp(its[0][0][d:], True), its[0][1]]
        cp = 0
        while all(len(p) > d + cp for p, _ in its) and len({p[d + cp] for p, _ in its}) == 1:
            cp += 1
        if cp:
            return [_hp(its[0][0][d:d + cp], False), ref(build(its, d + cp))]
        br = [b""] * 17
        for p, v in its:
            if len(p) == d:   # a key that ends at this branch (not used by fixed-length or index keys, kept for completeness)
                br[16] = v
        for i in range(16):
            sub = [x for x in its if len(x[0]) > d and x[0][d] == i]
            if sub:
                br[i] = ref(build(sub, d + 1))
        return br

    root_node = build(items, 0)
    enc = W.rlp_encode(root_node); root = W.keccak256(enc); db[root] = enc

    def proof(key):
        path = _nib(W.keccak256(key) if secure else key)
        out, node = [db[root]], root_node
        while True:
            if len(node) == 17:
                if not path:
                    return out
                nxt, path = node[path[0]], path[1:]
            else:
                hp = _nib(node[0])
                part = hp[2:] if hp[0] in (0, 2) else hp[1:]
                if hp[0] in (2, 3):
                    return out
                nxt, path = node[1], path[len(part):]
            if isinstance(nxt, list):
                node = nxt
            elif len(nxt) == 32:
                out.append(db[nxt]); node = _decode(db[nxt])
            else:
                return out
    return root, proof
