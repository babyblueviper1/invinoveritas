"""BIP-340 Schnorr signatures over secp256k1, standard library only (from the BIP's reference code).

Used by check.py to verify decider claims, and by gen_vectors.py to sign the test vectors. Verification is
the part a reader needs; signing here is for deterministic test vectors only (not constant time, not for
real keys)."""
import hashlib

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def tagged_hash(tag, msg):
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    if p1[0] == p2[0] and p1[1] != p2[1]:
        return None
    if p1 == p2:
        lam = (3 * p1[0] * p1[0] * pow(2 * p1[1], P - 2, P)) % P
    else:
        lam = ((p2[1] - p1[1]) * pow(p2[0] - p1[0], P - 2, P)) % P
    x3 = (lam * lam - p1[0] - p2[0]) % P
    return (x3, (lam * (p1[0] - x3) - p1[1]) % P)


def _mul(pt, k):
    r = None
    for i in range(256):
        if (k >> i) & 1:
            r = _add(r, pt)
        pt = _add(pt, pt)
    return r


def _lift_x(x):
    if x >= P:
        return None
    c = (pow(x, 3, P) + 7) % P
    y = pow(c, (P + 1) // 4, P)
    if pow(y, 2, P) != c:
        return None
    return (x, y if y % 2 == 0 else P - y)


def _b(x):
    return x.to_bytes(32, "big")


def _i(b):
    return int.from_bytes(b, "big")


def pubkey(seckey: bytes) -> bytes:
    d = _i(seckey)
    if not 1 <= d <= N - 1:
        raise ValueError("bad secret key")
    return _b(_mul(G, d)[0])


def sign(seckey: bytes, msg: bytes, aux: bytes = bytes(32)) -> bytes:
    d0 = _i(seckey)
    if not 1 <= d0 <= N - 1:
        raise ValueError("bad secret key")
    pt = _mul(G, d0)
    d = d0 if pt[1] % 2 == 0 else N - d0
    t = bytes(a ^ b for a, b in zip(_b(d), tagged_hash("BIP0340/aux", aux)))
    k0 = _i(tagged_hash("BIP0340/nonce", t + _b(pt[0]) + msg)) % N
    if k0 == 0:
        raise ValueError("nonce is zero")
    r = _mul(G, k0)
    k = k0 if r[1] % 2 == 0 else N - k0
    e = _i(tagged_hash("BIP0340/challenge", _b(r[0]) + _b(pt[0]) + msg)) % N
    return _b(r[0]) + _b((k + e * d) % N)


def verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    if len(pub) != 32 or len(sig) != 64:
        return False
    pt = _lift_x(_i(pub))
    r, s = _i(sig[:32]), _i(sig[32:])
    if pt is None or r >= P or s >= N:
        return False
    e = _i(tagged_hash("BIP0340/challenge", sig[:32] + pub + msg)) % N
    rr = _add(_mul(G, s), _mul(pt, N - e))
    return rr is not None and rr[1] % 2 == 0 and rr[0] == r
