"""Test-only helpers: a BOLT11 encoder/signer and a synthetic verdict issuer. Deterministic, not constant time, never for real keys."""
import hashlib
import json

from l402_verdict_gate import bip340
from l402_verdict_gate.bip340 import G, N, _mul
from l402_verdict_gate.bolt11 import CHARSET, _hrp_expand, _polymod
from l402_verdict_gate.jcs import canonicalize
from l402_verdict_gate.proof import nostr_event_id

NODE_KEY = 0x1111111111111111111111111111111111111111111111111111111111111111
ISSUER_SK = bytes.fromhex("22" * 32)
ISSUER_PK = bip340.pubkey(ISSUER_SK).hex()


def _words(b: bytes):
    acc = bits = 0
    out = []
    for x in b:
        acc = (acc << 8) | x
        bits += 8
        while bits >= 5:
            bits -= 5
            out.append((acc >> bits) & 31)
    if bits:
        out.append((acc << (5 - bits)) & 31)
    return out


def _int_words(n, length):
    return [(n >> (5 * (length - 1 - i))) & 31 for i in range(length)]


def _tag(t, words):
    return [CHARSET.index(t)] + _int_words(len(words), 2) + words


def _bytes(words):
    acc = bits = 0
    out = bytearray()
    for w in words:
        acc = (acc << 5) | w
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    if bits:
        out.append((acc << (8 - bits)) & 0xFF)
    return bytes(out)


def bech32(hrp, words):
    poly = _polymod(_hrp_expand(hrp) + words + [0] * 6) ^ 1
    return hrp + "1" + "".join(CHARSET[d] for d in words + [(poly >> 5 * (5 - i)) & 31 for i in range(6)])


def node_pubkey(key=NODE_KEY):
    Q = _mul(G, key)
    return ("02" if Q[1] % 2 == 0 else "03") + Q[0].to_bytes(32, "big").hex()


def make_invoice(payment_hash: str, amount="100n", timestamp=1791657998, expiry=600, description="test", key=NODE_KEY,
                 net="bc"):
    data = _int_words(timestamp, 7)
    data += _tag("p", _words(bytes.fromhex(payment_hash)))
    data += _tag("d", _words(description.encode()))
    data += _tag("x", _int_words(expiry, max(1, (expiry.bit_length() + 4) // 5)))
    hrp = f"ln{net}{amount}"
    msg = hashlib.sha256(hrp.encode() + _bytes(data)).digest()
    z = int.from_bytes(msg, "big")
    k = int.from_bytes(hashlib.sha256(key.to_bytes(32, "big") + msg).digest(), "big") % N
    R = _mul(G, k)
    r = R[0] % N
    s = pow(k, N - 2, N) * (z + r * key) % N
    recid = R[1] & 1
    if s > N // 2:
        s, recid = N - s, recid ^ 1
    sig = r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([recid])
    return bech32(hrp, data + _words(sig))


def aperture_macaroon(payment_hash: str, location="api.example.com", caveats=("services=pulse:0",)) -> bytes:
    def field(t, v: bytes):
        return bytes([t, len(v)]) + v
    ident = b"\x00\x00" + bytes.fromhex(payment_hash) + b"\x07" * 32
    raw = b"\x02" + field(1, location.encode()) + field(2, ident) + b"\x00"
    for c in caveats:
        raw += field(2, c.encode()) + b"\x00"
    return raw + b"\x00" + field(6, b"\x99" * 32)


def sign_verdict(args: dict, tool: str, verdict="approve", verified_at=1791658010, sk=ISSUER_SK):
    content = {"schema": "invinoveritas.verdict_proof.v1", "verdict": verdict, "verified_at": verified_at,
               "action_binding_args_hash": "sha256:" + hashlib.sha256(canonicalize(args).encode()).hexdigest(),
               "action_binding_tool_hash": "sha256:" + hashlib.sha256(tool.encode()).hexdigest(),
               "decision_ref_preimage_fields": ["verdict", "verified_at", "action_binding_args_hash", "action_binding_tool_hash"]}
    content["decision_ref"] = "sha256:" + hashlib.sha256(canonicalize({f: content[f] for f in content["decision_ref_preimage_fields"]}).encode()).hexdigest()
    ev = {"pubkey": bip340.pubkey(sk).hex(), "created_at": verified_at, "kind": 30078, "tags": [["t", "invinoveritas"]],
          "content": json.dumps(content, separators=(",", ":"), sort_keys=True)}
    ev["id"] = nostr_event_id(ev)
    ev["sig"] = bip340.sign(sk, bytes.fromhex(ev["id"]), b"\x00" * 32).hex()
    return {"verdict": verdict, "confidence": 0.9, "summary": "synthetic", "proof": {"event": ev}}
