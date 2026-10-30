"""Reference encoder for the ERC-8299 signing-input profile, v0 (Safe binding) -- see ENCODER.md.

Python standard library only, so a stranger can run it with nothing else installed. Pure functions: the same intent gives the
same payload on any machine. Also exports the primitives the checker shares (keccak-256, RFC 8785 JCS, ABI encoding, EIP-712
hashing, secp256k1 public-key recovery).

    payload, info = encode(intent)          # info: the SafeTx fields, payload_hash, signing_digest
"""
import hashlib
import json
import re

# ---------------------------------------------------------------- keccak-256 (Ethereum's, i.e. original Keccak padding 0x01)
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
       0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
       0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
       0x000000000000800A, 0x800000008000000A, 0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def _f1600(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def keccak256(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * ((-len(msg)) % rate)
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        blk = msg[off:off + rate]
        for i in range(rate // 8):
            a[i % 5][i // 5] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        a = _f1600(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(25))
    return out[:32]


# ---------------------------------------------------------------- RFC 8785 JCS (the subset an intent can contain)
def jcs(v) -> bytes:
    """RFC 8785: object members sorted by UTF-16 code units, no whitespace, ECMAScript string escaping. Floats are refused
    (the intent carries integers as decimal strings; chainId is a JSON integer)."""
    def ser(x):
        if x is None:
            return "null"
        if x is True:
            return "true"
        if x is False:
            return "false"
        if isinstance(x, int):
            return str(x)
        if isinstance(x, float):
            raise ValueError("JCS: floats are not allowed in an intent")
        if isinstance(x, str):
            return json.dumps(x, ensure_ascii=False)
        if isinstance(x, list):
            return "[" + ",".join(ser(i) for i in x) + "]"
        if isinstance(x, dict):
            ks = sorted(x, key=lambda k: k.encode("utf-16-be"))
            return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + ser(x[k]) for k in ks) + "}"
        raise ValueError(f"JCS: unsupported type {type(x).__name__}")
    return ser(v).encode("utf-8")


# ---------------------------------------------------------------- secp256k1 public-key recovery (ecrecover)
P = 2 ** 256 - 2 ** 32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    if p1[0] == p2[0] and (p1[1] + p2[1]) % P == 0:
        return None
    if p1 == p2:
        lam = 3 * p1[0] * p1[0] * pow(2 * p1[1], -1, P) % P
    else:
        lam = (p2[1] - p1[1]) * pow(p2[0] - p1[0], -1, P) % P
    x = (lam * lam - p1[0] - p2[0]) % P
    return x, (lam * (p1[0] - x) - p1[1]) % P


def _mul(k, pt):
    r = None
    while k:
        if k & 1:
            r = _add(r, pt)
        pt = _add(pt, pt)
        k >>= 1
    return r


def ecrecover(digest: bytes, sig65: bytes):
    """The address that produced a 65-byte (r, s, v) signature over a 32-byte digest, v in {27, 28}; None if invalid.
    Same acceptance as the EVM precompile (high s is accepted; r, s in [1, n-1])."""
    if len(sig65) != 65 or len(digest) != 32:
        return None
    r, s, v = int.from_bytes(sig65[:32], "big"), int.from_bytes(sig65[32:64], "big"), sig65[64]
    if v not in (27, 28) or not (0 < r < N) or not (0 < s < N):
        return None
    y2 = (pow(r, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if y * y % P != y2:
        return None
    if y % 2 != v - 27:
        y = P - y
    z = int.from_bytes(digest, "big")
    rinv = pow(r, -1, N)
    q = _add(_mul(s * rinv % N, (r, y)), _mul((-z * rinv) % N, G))
    if q is None:
        return None
    return "0x" + keccak256(q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big"))[12:].hex()


# ---------------------------------------------------------------- RLP encoding (for rebuilding a block header in live_check.py)
def rlp_encode(x) -> bytes:
    if isinstance(x, int):
        x = x.to_bytes((x.bit_length() + 7) // 8, "big") if x else b""
    if isinstance(x, bytes):
        if len(x) == 1 and x[0] < 0x80:
            return x
        return (bytes([0x80 + len(x)]) if len(x) < 56 else bytes([0xb7 + (len(len(x).to_bytes(8, "big").lstrip(b"\x00")))]) + len(x).to_bytes(8, "big").lstrip(b"\x00")) + x
    body = b"".join(rlp_encode(i) for i in x)
    return (bytes([0xc0 + len(body)]) if len(body) < 56 else bytes([0xf7 + len(len(body).to_bytes(8, "big").lstrip(b"\x00"))]) + len(body).to_bytes(8, "big").lstrip(b"\x00")) + body


# ---------------------------------------------------------------- ABI encoding (the v0 subset; see ENCODER.md section 4)
ADDR = re.compile(r"^0x[0-9a-f]{40}$")
HEX = re.compile(r"^0x([0-9a-f]{2})*$")
DEC = re.compile(r"^(0|[1-9][0-9]*)$")
SDEC = re.compile(r"^(0|-?[1-9][0-9]*)$")
TYPE = re.compile(r"^(address|bool|string|bytes|uint(8|16|24|32|40|48|56|64|72|80|88|96|104|112|120|128|136|144|152|160|168|176|184|192|"
                  r"200|208|216|224|232|240|248|256)|int(8|16|24|32|40|48|56|64|72|80|88|96|104|112|120|128|136|144|152|160|168|176|184|"
                  r"192|200|208|216|224|232|240|248|256)|bytes([1-9]|[12][0-9]|3[0-2]))$")


class EncodeError(ValueError):
    pass


def _word(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _static(t: str, v) -> bytes:
    if t == "address":
        if not (isinstance(v, str) and ADDR.match(v)):
            raise EncodeError(f"address must be lowercase 0x + 40 hex: {v!r}")
        return b"\x00" * 12 + bytes.fromhex(v[2:])
    if t == "bool":
        if not isinstance(v, bool):
            raise EncodeError(f"bool must be a JSON true/false: {v!r}")
        return _word(int(v))
    if t.startswith("uint"):
        bits = int(t[4:])
        if not (isinstance(v, str) and DEC.match(v)) or int(v) >= 2 ** bits:
            raise EncodeError(f"{t} must be a decimal string in range: {v!r}")
        return _word(int(v))
    if t.startswith("int"):
        bits = int(t[3:])
        if not (isinstance(v, str) and SDEC.match(v)) or not (-(2 ** (bits - 1)) <= int(v) < 2 ** (bits - 1)):
            raise EncodeError(f"{t} must be a decimal string in range: {v!r}")
        return _word(int(v) % 2 ** 256)
    if t.startswith("bytes"):
        n = int(t[5:])
        if not (isinstance(v, str) and HEX.match(v)) or len(v) != 2 + 2 * n:
            raise EncodeError(f"{t} must be lowercase 0x hex of exactly {n} bytes: {v!r}")
        return bytes.fromhex(v[2:]) + b"\x00" * (32 - n)
    raise EncodeError(f"unsupported static type {t}")


def _dyn(t: str, v) -> bytes:
    if t == "string":
        if not isinstance(v, str):
            raise EncodeError(f"string must be a JSON string: {v!r}")
        b = v.encode("utf-8")
    else:
        if not (isinstance(v, str) and HEX.match(v)):
            raise EncodeError(f"bytes must be lowercase 0x hex: {v!r}")
        b = bytes.fromhex(v[2:])
    return _word(len(b)) + b + b"\x00" * ((-len(b)) % 32)


def abi_encode(types, values) -> bytes:
    """Standard Solidity ABI encoding of a flat tuple (head/tail; dynamic = bytes, string)."""
    heads, tails = [], b""
    hl = 32 * len(types)
    for t, v in zip(types, values):
        if t in ("bytes", "string"):
            heads.append(_word(hl + len(tails)))
            tails += _dyn(t, v)
        else:
            heads.append(_static(t, v))
    return b"".join(heads) + tails


# ---------------------------------------------------------------- EIP-712
def typehash(s: str) -> bytes:
    return keccak256(s.encode())


def eip712_digest(domain_separator: bytes, struct_hash: bytes) -> bytes:
    return keccak256(b"\x19\x01" + domain_separator + struct_hash)


SAFE_DOMAIN_TYPE = "EIP712Domain(uint256 chainId,address verifyingContract)"
SAFE_TX_TYPE = ("SafeTx(address to,uint256 value,bytes data,uint8 operation,uint256 safeTxGas,uint256 baseGas,uint256 gasPrice,"
                "address gasToken,address refundReceiver,uint256 nonce)")
WYRIWE_DOMAIN_TYPE = "EIP712Domain(string name,string version,uint256 chainId)"
WYRIWE_DOMAIN_NAME, WYRIWE_DOMAIN_VERSION = "ERC8004AttestationGateway", "1"     # ERC-8299 section 4
WYRIWE_TYPE = ("WyriweSigningInput(uint256 chainId,address account,bytes32 intentHash,bytes32 encoderPipelineHash,bytes32 payloadHash,"
               "bytes32 signingDigest,uint256 timestamp)")
ZERO = "0x" + "00" * 20


def safe_domain_separator(chain_id: int, safe: str) -> bytes:
    return keccak256(typehash(SAFE_DOMAIN_TYPE) + _word(chain_id) + _static("address", safe))


def safe_tx_hash(chain_id: int, safe: str, f: dict) -> bytes:
    """The Safe's signing digest (getTransactionHash, Safe v1.3.0+)."""
    sh = keccak256(typehash(SAFE_TX_TYPE) + _static("address", f["to"]) + _word(f["value"]) + keccak256(f["data"])
                   + _word(f["operation"]) + _word(f["safeTxGas"]) + _word(f["baseGas"]) + _word(f["gasPrice"])
                   + _static("address", f["gasToken"]) + _static("address", f["refundReceiver"]) + _word(f["nonce"]))
    return eip712_digest(safe_domain_separator(chain_id, safe), sh)


def wyriwe_domain_separator(chain_id: int) -> bytes:
    return keccak256(typehash(WYRIWE_DOMAIN_TYPE) + keccak256(WYRIWE_DOMAIN_NAME.encode()) + keccak256(WYRIWE_DOMAIN_VERSION.encode())
                     + _word(chain_id))


def wyriwe_struct_digest(domain_chain_id: int, s: dict) -> bytes:
    """EIP-712 digest a reviewer signs (profile section 7) under the ERC-8299 section 4 domain."""
    sh = keccak256(typehash(WYRIWE_TYPE) + _word(s["chainId"]) + _static("address", s["account"])
                   + bytes.fromhex(s["intentHash"][2:]) + bytes.fromhex(s["encoderPipelineHash"][2:]) + bytes.fromhex(s["payloadHash"][2:])
                   + bytes.fromhex(s["signingDigest"][2:]) + _word(s["timestamp"]))
    return eip712_digest(wyriwe_domain_separator(domain_chain_id), sh)


ROOT_PIN_TYPE = "WyriweReviewTrustRoot(address account,bytes32 listHash,uint256 pinnedAtBlock)"


def root_pin_digest(domain_chain_id: int, s: dict) -> bytes:
    """EIP-712 digest the account's owners sign to pin a reviewer list (its content hash) at a block, before a flow
    (authority + prior binding for reviewer-list@commitment; Pavlo, WG 5962)."""
    sh = keccak256(typehash(ROOT_PIN_TYPE) + _static("address", s["account"]) + bytes.fromhex(s["listHash"][2:]) + _word(s["pinnedAtBlock"]))
    return eip712_digest(wyriwe_domain_separator(domain_chain_id), sh)


# ---------------------------------------------------------------- the profile's hashes and the v0 Safe encoder
INTENT_KEYS = {"chainId", "account", "target", "value", "function", "args", "operation", "nonce"}
FUNC = re.compile(r"^([A-Za-z_$][A-Za-z0-9_$]*)\(([a-z0-9,]*)\)$")
PAYLOAD_TYPES = ["address", "uint256", "bytes", "uint8", "uint256", "uint256", "uint256", "address", "address", "uint256"]
FIELDS = ["to", "value", "data", "operation", "safeTxGas", "baseGas", "gasPrice", "gasToken", "refundReceiver", "nonce"]


def intent_hash(intent: dict) -> bytes:
    return keccak256(jcs(intent))


def encoder_pipeline_hash(encoder_spec_cid: str, ih: bytes) -> bytes:
    return keccak256(encoder_spec_cid.encode("utf-8") + ih)


def safe_fields(intent: dict) -> dict:
    """ENCODER.md section 3: intent -> SafeTx fields. Raises EncodeError on anything outside v0."""
    if not isinstance(intent, dict) or set(intent) != INTENT_KEYS:
        raise EncodeError(f"intent members must be exactly {sorted(INTENT_KEYS)}")
    ci = intent["chainId"]
    if isinstance(ci, bool) or not isinstance(ci, int) or ci <= 0:
        raise EncodeError("chainId must be a positive JSON integer")
    for k in ("account", "target"):
        if not (isinstance(intent[k], str) and ADDR.match(intent[k])):
            raise EncodeError(f"{k} must be a lowercase 0x address")
    if not (isinstance(intent["value"], str) and DEC.match(intent["value"])) or int(intent["value"]) >= 2 ** 256:
        raise EncodeError("value must be a decimal string (wei)")
    if intent["operation"] not in ("call", "delegatecall"):
        raise EncodeError("operation must be 'call' or 'delegatecall'")
    if not (isinstance(intent["nonce"], str) and DEC.match(intent["nonce"])):
        raise EncodeError("v0 (Safe) requires nonce as a decimal string")
    args = intent["args"]
    if not isinstance(args, list) or any(not isinstance(a, dict) or set(a) != {"type", "value"} for a in args):
        raise EncodeError("args must be a list of {type, value}")
    fn = intent["function"]
    if fn == "":
        if args:
            raise EncodeError("a plain value transfer (function '') takes no args")
        data = b""
    else:
        m = FUNC.match(fn) if isinstance(fn, str) else None
        if not m:
            raise EncodeError("function must be a canonical signature, e.g. transfer(address,uint256)")
        types = m.group(2).split(",") if m.group(2) else []
        if types != [a["type"] for a in args]:
            raise EncodeError("function signature types must equal the args types, in order")
        for t in types:
            if not TYPE.match(t):
                raise EncodeError(f"type {t} is outside v0 (no arrays or tuples)")
        data = keccak256(fn.encode())[:4] + abi_encode(types, [a["value"] for a in args])
    return {"to": intent["target"], "value": int(intent["value"]), "data": data, "operation": 0 if intent["operation"] == "call" else 1,
            "safeTxGas": 0, "baseGas": 0, "gasPrice": 0, "gasToken": ZERO, "refundReceiver": ZERO, "nonce": int(intent["nonce"])}


def payload_of(f: dict) -> bytes:
    return abi_encode(PAYLOAD_TYPES, [f["to"], str(f["value"]), "0x" + f["data"].hex(), str(f["operation"]), str(f["safeTxGas"]),
                                      str(f["baseGas"]), str(f["gasPrice"]), f["gasToken"], f["refundReceiver"], str(f["nonce"])])


def encode(intent: dict):
    """The v0 encoder: intent -> (payload bytes, info). Deterministic and pure."""
    f = safe_fields(intent)
    payload = payload_of(f)
    return payload, {"fields": f, "payload_hash": keccak256(payload),
                     "signing_digest": safe_tx_hash(intent["chainId"], intent["account"], f)}


def sha256_file(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()
