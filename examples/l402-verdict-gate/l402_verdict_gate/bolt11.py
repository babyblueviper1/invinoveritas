"""BOLT11 invoice decoding, standard library only.

Decodes the fields a payer must check before paying: network, amount, payment_hash, payee node key, creation time and
expiry, description. The payee key is recovered from the invoice signature (and checked against the `n` field when
the invoice carries one), so a decoded invoice is also a verified one: a single changed character fails.
Spec: https://github.com/lightning/bolts/blob/master/11-payment-encoding.md
"""
import hashlib
from dataclasses import dataclass, field
from typing import Optional

from .bip340 import G, N, P, _add, _mul

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_GEN = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
_MULT = {"m": 10**8, "u": 10**5, "n": 10**2, "p": 10**-1}  # msat per unit of amount (1 BTC = 1e11 msat)
NETWORKS = {"bc": "bitcoin", "tb": "testnet", "tbs": "signet", "bcrt": "regtest"}


class InvoiceError(ValueError):
    pass


@dataclass
class Invoice:
    bolt11: str
    network: str                 # "bc", "tb", "tbs", "bcrt"
    amount_msat: Optional[int]   # None for an amount-less invoice
    timestamp: int
    expiry: int                  # seconds, default 3600
    payment_hash: str            # 64 hex
    payee_pubkey: str            # 66 hex, compressed, recovered from the signature
    description: Optional[str] = None
    description_hash: Optional[str] = None
    payment_secret: Optional[str] = None
    min_final_cltv_expiry: int = 18
    tags: dict = field(default_factory=dict)

    @property
    def expires_at(self) -> int:
        return self.timestamp + self.expiry

    @property
    def amount_sat(self) -> Optional[int]:
        return None if self.amount_msat is None else self.amount_msat // 1000


def _polymod(values):
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= _GEN[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_decode(s: str):
    if s.lower() != s and s.upper() != s:
        raise InvoiceError("mixed case")
    s = s.lower()
    pos = s.rfind("1")
    if pos < 1 or pos + 7 > len(s):
        raise InvoiceError("no bech32 separator")
    hrp, data = s[:pos], s[pos + 1:]
    try:
        words = [CHARSET.index(c) for c in data]
    except ValueError:
        raise InvoiceError("invalid bech32 character") from None
    if _polymod(_hrp_expand(hrp) + words) != 1:
        raise InvoiceError("bad bech32 checksum")
    return hrp, words[:-6]


def _to_bytes(words, pad=True):
    acc = bits = 0
    out = bytearray()
    for w in words:
        acc = (acc << 5) | w
        bits += 5
        while bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    if pad and bits:
        out.append((acc << (8 - bits)) & 0xFF)
    return bytes(out)


def _to_int(words):
    n = 0
    for w in words:
        n = (n << 5) | w
    return n


def _parse_hrp(hrp: str):
    if not hrp.startswith("ln"):
        raise InvoiceError("not a lightning invoice")
    rest = hrp[2:]
    for net in sorted(NETWORKS, key=len, reverse=True):
        if rest.startswith(net):
            amt = rest[len(net):]
            break
    else:
        raise InvoiceError(f"unknown network prefix in {hrp!r}")
    if not amt:
        return net, None
    mult = amt[-1] if amt[-1] in _MULT else None
    digits = amt[:-1] if mult else amt
    if not digits.isdigit() or (len(digits) > 1 and digits[0] == "0"):
        raise InvoiceError("bad amount")
    n = int(digits)
    if mult is None:
        return net, n * 10**11
    if mult == "p":
        if n % 10:
            raise InvoiceError("pico-btc amount is not a whole msat")
        return net, n // 10
    return net, n * _MULT[mult]


def _recover(msg32: bytes, sig64: bytes, recid: int):
    """ECDSA public key recovery on secp256k1 (compressed key, hex)."""
    r, s = int.from_bytes(sig64[:32], "big"), int.from_bytes(sig64[32:], "big")
    if not (1 <= r < N and 1 <= s < N) or recid not in (0, 1, 2, 3):
        raise InvoiceError("bad signature")
    x = r + (recid >> 1) * N
    if x >= P:
        raise InvoiceError("bad signature")
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if y * y % P != y2:
        raise InvoiceError("bad signature")
    if (y & 1) != (recid & 1):
        y = P - y
    e = int.from_bytes(msg32, "big") % N
    rinv = pow(r, N - 2, N)
    sR = _mul((x, y), s)
    eG = _mul(G, (N - e) % N)
    Q = _add(sR, eG)
    Q = _mul(Q, rinv) if Q else None
    if Q is None:
        raise InvoiceError("bad signature")
    return ("02" if Q[1] % 2 == 0 else "03") + Q[0].to_bytes(32, "big").hex()


def _verify_ecdsa(msg32: bytes, sig64: bytes, pub_hex: str) -> bool:
    pub = bytes.fromhex(pub_hex)
    x = int.from_bytes(pub[1:], "big")
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if (y & 1) != (pub[0] & 1):
        y = P - y
    r, s = int.from_bytes(sig64[:32], "big"), int.from_bytes(sig64[32:], "big")
    if not (1 <= r < N and 1 <= s < N):
        return False
    w = pow(s, N - 2, N)
    e = int.from_bytes(msg32, "big") % N
    pt = _add(_mul(G, e * w % N), _mul((x, y), r * w % N))
    return pt is not None and pt[0] % N == r


def decode(bolt11: str) -> Invoice:
    s = bolt11.strip()
    if s.lower().startswith("lightning:"):
        s = s[10:]
    hrp, words = _bech32_decode(s)
    if len(words) < 7 + 104:
        raise InvoiceError("too short")
    net, amount_msat = _parse_hrp(hrp)
    data, sigw = words[:-104], words[-104:]
    sig = _to_bytes(sigw, pad=False)
    if len(sig) != 65:
        raise InvoiceError("bad signature length")
    msg = hashlib.sha256(hrp.encode() + _to_bytes(data)).digest()
    ts = _to_int(data[:7])
    i, tags = 7, {}
    while i < len(data):
        if i + 3 > len(data):
            raise InvoiceError("truncated tagged field")
        t, ln = CHARSET[data[i]], data[i + 1] * 32 + data[i + 2]
        v = data[i + 3:i + 3 + ln]
        if len(v) != ln:
            raise InvoiceError("truncated tagged field")
        i += 3 + ln
        tags.setdefault(t, []).append(v)

    def first(t, nwords=None):
        for v in tags.get(t, []):
            if nwords is None or len(v) == nwords:  # BOLT11: skip p/h/s/n fields of the wrong length
                return v
        return None

    ph = first("p", 52)
    if ph is None:
        raise InvoiceError("no payment_hash")
    d, h, sec, n, x, c = first("d"), first("h", 52), first("s", 52), first("n", 53), first("x"), first("c")
    if d is not None and h is not None:
        raise InvoiceError("both description and description_hash")
    recid = sig[64]
    if n is not None:
        payee = _to_bytes(n, pad=False)[:33].hex()
        if not _verify_ecdsa(msg, sig[:64], payee):
            raise InvoiceError("signature does not verify against the n field")
    else:
        payee = _recover(msg, sig[:64], recid)
    return Invoice(
        bolt11=s.lower(), network=net, amount_msat=amount_msat, timestamp=ts,
        expiry=_to_int(x) if x is not None else 3600,
        payment_hash=_to_bytes(ph, pad=False)[:32].hex(), payee_pubkey=payee,
        description=_to_bytes(d, pad=False).decode("utf-8", "replace") if d is not None else None,
        description_hash=_to_bytes(h, pad=False)[:32].hex() if h is not None else None,
        payment_secret=_to_bytes(sec, pad=False)[:32].hex() if sec is not None else None,
        min_final_cltv_expiry=_to_int(c) if c is not None else 18,
        tags={k: len(v) for k, v in tags.items()},
    )
