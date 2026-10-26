"""OpenTimestamps proof check, standard library only (deils-anchor-v1, PROFILE.md section "Anchor states").

Reads a detached .ots proof, checks that it is a proof for the expected digest, replays every operation path, and reports the
attestations it reaches. A Bitcoin attestation counts as CONFIRMED only when the caller supplies the block header for that height
and the header's merkle root equals the message the path computes; the header's proof of work is checked too. A calendar's
pending attestation is never confirmation, whatever the calendar claims.

The header is TRUSTED INPUT, not something this file fetches: obtain it from your own node or from explorers you choose (two that
agree is the minimum we suggest). The header must carry the PINNED difficulty for its retarget epoch (PINNED_BITS) and meet that
target; a header's self-declared bits are never trusted (Echo, review 2: regtest bits 0x207fffff pass at nonce 0). Even so, proof of
work only shows real work on that header, not that the block is in the best chain: the protection is where you got the header.""" 
import hashlib

MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
BITCOIN_TAG = bytes.fromhex("0588960d73d71901")
PENDING_TAG = bytes.fromhex("83dfe30d2ef90c8e")
UNARY = {0x08: lambda m: hashlib.sha256(m).digest(), 0x02: lambda m: hashlib.sha1(m).digest(),
         0x03: lambda m: hashlib.new("ripemd160", m).digest(), 0xF2: lambda m: m[::-1], 0xF3: lambda m: m.hex().encode()}
BINARY = {0xF0: lambda m, a: m + a, 0xF1: lambda m, a: a + m}


class OtsError(ValueError):
    pass


class _R:
    def __init__(self, b):
        self.b, self.i = b, 0

    def byte(self):
        if self.i >= len(self.b):
            raise OtsError("truncated proof")
        self.i += 1
        return self.b[self.i - 1]

    def bytes(self, n):
        if self.i + n > len(self.b):
            raise OtsError("truncated proof")
        self.i += n
        return self.b[self.i - n:self.i]

    def varuint(self):
        v, s = 0, 0
        while True:
            c = self.byte()
            v |= (c & 0x7F) << s
            if not c & 0x80:
                return v
            s += 7
            if s > 63:
                raise OtsError("varuint too long")

    def varbytes(self, maxlen=8192):
        n = self.varuint()
        if n > maxlen:
            raise OtsError("varbytes too long")
        return self.bytes(n)


def _walk(r, msg, out, depth=0):
    if depth > 256:
        raise OtsError("proof too deep")

    def one(tag):
        if tag == 0x00:
            atag = r.bytes(8); payload = _R(r.varbytes())
            if atag == BITCOIN_TAG:
                out.append({"kind": "bitcoin", "height": payload.varuint(), "msg": msg})
            elif atag == PENDING_TAG:
                out.append({"kind": "pending", "uri": payload.varbytes(1000).decode("utf-8", "replace"), "msg": msg})
            else:
                out.append({"kind": "unknown", "tag": atag.hex(), "msg": msg})
        elif tag in UNARY:
            _walk(r, UNARY[tag](msg), out, depth + 1)
        elif tag in BINARY:
            arg = r.varbytes(4096)
            _walk(r, BINARY[tag](msg, arg), out, depth + 1)
        else:
            raise OtsError(f"unknown op tag 0x{tag:02x}")

    tag = r.byte()
    while tag == 0xFF:
        one(r.byte())
        tag = r.byte()
    one(tag)


def attestations(ots: bytes, digest_hex: str):
    """All attestations the proof reaches. Raises OtsError if it is not a sha256 proof for digest_hex."""
    r = _R(ots)
    if r.bytes(len(MAGIC)) != MAGIC:
        raise OtsError("not an OpenTimestamps proof")
    if r.varuint() != 1:
        raise OtsError("unsupported proof version")
    if r.byte() != 0x08:
        raise OtsError("file hash is not sha256")
    d = r.bytes(32)
    if d.hex() != digest_hex.lower():
        raise OtsError(f"proof is for {d.hex()}, not {digest_hex}")
    out = []
    _walk(r, d, out)
    if r.i != len(ots):
        raise OtsError("trailing bytes after the proof")
    return out


# Expected difficulty per retarget epoch (height // 2016), from headers two explorers agree on. A header's own bits field is NOT
# trusted: with a self-declared easy target (regtest 0x207fffff) a forged header passes proof of work at nonce 0 (Echo, review 2,
# 2026-10-26). A height whose epoch is not pinned here cannot reach "confirmed": extend the table from your own node.
PINNED_BITS = {481: 0x17021EF0, 482: 0x17020093}


def _pow_ok(header: bytes, bits_expected: int) -> bool:
    """Proof of work under the PINNED target (the caller has already required header bits == pinned bits)."""
    exp, mant = bits_expected >> 24, bits_expected & 0xFFFFFF
    if mant & 0x800000 or exp < 3:
        return False
    target = mant << (8 * (exp - 3))
    h = int.from_bytes(hashlib.sha256(hashlib.sha256(header).digest()).digest(), "little")
    return h <= target


NOT_CONFIRMING = {"ots_bitcoin_header_missing", "ots_bits_unpinned"}   # reasons a proof is not (yet) confirmation; the rest are failures


def check(ots: bytes, digest_hex: str, headers: dict, pinned_bits: dict = None):
    """-> {"state": "confirmed"|"pending"|"none", "height", "codes"}. headers = {height(int): 80-byte header hex}; the header is TRUSTED
    INPUT (get it from your own node or explorers you choose). Checks: the epoch's bits are pinned and the header carries exactly them,
    proof of work under that target, merkle root == the message the proof computes.
    codes: ots_bitcoin_header_missing / ots_bits_unpinned (not confirmation, not failure); ots_header_bits_mismatch,
    ots_header_invalid_pow, ots_bitcoin_header_mismatch (failures). A digest mismatch or a malformed proof raises OtsError."""
    pins = PINNED_BITS if pinned_bits is None else pinned_bits
    att = attestations(ots, digest_hex)
    codes = []
    for a in att:
        if a["kind"] != "bitcoin":
            continue
        hx = headers.get(a["height"]) or headers.get(str(a["height"]))
        if not hx:
            codes.append("ots_bitcoin_header_missing"); continue
        hb = bytes.fromhex(hx)
        if len(hb) != 80:
            codes.append("ots_bitcoin_header_mismatch"); continue
        want = pins.get(a["height"] // 2016)
        if want is None:
            codes.append("ots_bits_unpinned"); continue
        if int.from_bytes(hb[72:76], "little") != want:
            codes.append("ots_header_bits_mismatch"); continue
        if not _pow_ok(hb, want):
            codes.append("ots_header_invalid_pow"); continue
        if hb[36:68] != a["msg"]:
            codes.append("ots_bitcoin_header_mismatch"); continue
        return {"state": "confirmed", "height": a["height"], "codes": []}
    if any(a["kind"] == "pending" for a in att) or codes:
        return {"state": "pending", "height": None, "codes": sorted(set(codes))}
    return {"state": "none", "height": None, "codes": sorted(set(codes))}
