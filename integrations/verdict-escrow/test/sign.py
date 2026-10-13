#!/usr/bin/env python3
"""Test-only helper for forge ffi. A THROWAWAY key (sha256 of a fixed label), never the production verdict key.
  sign.py pubkey                                  -> 0x<x-only pubkey>
  sign.py sign <digest-hex>                       -> 0x<64-byte BIP-340 signature>
  sign.py relaydigest <chainid> <addr> <id> <sub> <ver> <result> <td> <decisionref>  -> server-side verdict_relay.digest"""
import hashlib, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "examples", "decision-receipt")); sys.path.insert(0, ROOT)
import bip340
SK = hashlib.sha256(b"verdict-escrow test key -- not production").digest()
cmd = sys.argv[1]
if cmd == "pubkey":
    print("0x" + bip340.pubkey(SK).hex())
elif cmd == "sign":
    print("0x" + bip340.sign(SK, bytes.fromhex(sys.argv[2][2:])).hex())
elif cmd == "relaydigest":
    # The verdict-relay v2 digest exactly as the signing server computes it (services/verdict_relay.py `digest` in the
    # invinoveritas API): sha256 over 11 ABI words. Inline so this test runs without the server code; when the server module
    # is importable (our own repo) the two are also compared, so a server-side change cannot drift silently from this copy.
    c, a, i, sub, ver, res, td, dref = sys.argv[2:10]
    ad = bytes(12) + bytes.fromhex(a[2:])
    u = lambda n: int(n).to_bytes(32, "big")
    enc = (hashlib.sha256(b"invinoveritas/verdict-relay/v2").digest() + u(c) + ad + ad + u(i) + u(sub) + u(ver)
           + bytes.fromhex(res[2:]) + bytes.fromhex(td[2:]) + u(1) + bytes.fromhex(dref[2:]))
    d = hashlib.sha256(enc).digest()
    try:
        from services import verdict_relay as V
        f = dict(chain_id=int(c), authority=ad, task_contract=ad, token_id=int(i), submission_id=int(sub), task_version=int(ver),
                 result_hash=bytes.fromhex(res[2:]), td_hash=bytes.fromhex(td[2:]))
        assert V.digest(f, True, bytes.fromhex(dref[2:])) == d, "inline digest drifted from services/verdict_relay.digest"
    except ImportError:
        pass
    print("0x" + d.hex())
