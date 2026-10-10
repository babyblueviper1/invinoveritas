"""Parse an L402 (or legacy LSAT) challenge from a 402 response.

    WWW-Authenticate: L402 macaroon="<base64>", invoice="<bolt11>"      (spec, Aperture, lnget)
    WWW-Authenticate: L402 version="0", token="<base64>", invoice="..."  (variant seen in the wild)

The parser accepts both credential parameter names, mirrors the server's prefix for the retry header (as lnget does),
and pulls out the payment_hash the credential commits to, when it can, so the gate can check that the credential
and the invoice belong together before any money moves.
Spec: https://github.com/lightninglabs/L402 . Reference client: https://github.com/lightninglabs/lnget (l402/header.go).
"""
import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Optional

_SCHEME = re.compile(r"(?i)\b(L402|LSAT)\s+(.*)")
_PARAM = re.compile(r'([A-Za-z0-9_-]+)\s*=\s*"([^"]*)"')


class ChallengeError(ValueError):
    pass


@dataclass
class Challenge:
    prefix: str                     # "L402" or "LSAT", mirrored in the Authorization header
    credential: str                 # base64 macaroon (or token) to present with the preimage
    invoice: str                    # BOLT11
    credential_param: str           # "macaroon" or "token"
    credential_payment_hash: Optional[str]  # hex, when the credential commits to one we can read
    credential_location: Optional[str] = None
    credential_caveats: tuple = ()
    credential_expires_at: Optional[int] = None

    def authorization(self, preimage_hex: str) -> str:
        return f"{self.prefix} {self.credential}:{preimage_hex}"


def _b64(s: str) -> bytes:
    s = s.strip()
    pad = "=" * (-len(s) % 4)
    try:
        return base64.urlsafe_b64decode(s.replace("+", "-").replace("/", "_") + pad)
    except (binascii.Error, ValueError):
        raise ChallengeError("credential is not base64") from None


def _uvarint(b: bytes, i: int):
    shift = n = 0
    while True:
        if i >= len(b):
            raise ChallengeError("truncated varint")
        c = b[i]
        i += 1
        n |= (c & 0x7F) << shift
        if c < 0x80:
            return n, i
        shift += 7


def parse_macaroon_v2(raw: bytes) -> Optional[dict]:
    """Location, identifier and first-party caveats of a binary v2 macaroon (the format Aperture issues), or None."""
    if not raw or raw[0] != 0x02:
        return None

    def section(i):
        f = {}
        while True:
            t, i = _uvarint(raw, i)
            if t == 0:
                return f, i
            ln, i = _uvarint(raw, i)
            f[t] = raw[i:i + ln]
            i += ln

    head, i = section(1)
    caveats = []
    while i < len(raw):
        if raw[i] == 0:  # end of caveats; the signature follows
            break
        cav, i = section(i)
        if 2 in cav and 4 not in cav:
            caveats.append(cav[2].decode("utf-8", "replace"))
    if 2 not in head:
        return None
    return {"location": head.get(1, b"").decode("utf-8", "replace") or None, "identifier": head[2], "caveats": caveats}


def credential_info(credential: str) -> dict:
    """What a credential commits to, where it can be read: payment_hash, location, caveats, expiry.
    Aperture macaroon: identifier = uint16 version (0) || payment_hash (32) || token_id (32); caveats such as
    "services=name:tier" and "<service>_valid_until=<unix>". JSON token (e.g. Lightning Faucet): caveats
    [{"type": "payment_hash" | "expiry" | "service" | ..., "value": ...}] and a "location"."""
    out = {"payment_hash": None, "location": None, "caveats": [], "expires_at": None, "format": "opaque"}
    raw = _b64(credential)
    mac = parse_macaroon_v2(raw)
    if mac is not None:
        ident = mac["identifier"]
        if len(ident) == 66 and ident[:2] == b"\x00\x00":
            out["payment_hash"] = ident[2:34].hex()
        out.update(format="macaroon_v2", location=mac["location"], caveats=mac["caveats"])
        for c in mac["caveats"]:
            k, _, v = c.partition("=")
            if k.strip().endswith("_valid_until") and v.strip().isdigit():
                t = int(v.strip())
                out["expires_at"] = t if out["expires_at"] is None else min(out["expires_at"], t)
        return out
    try:
        j = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return out
    if not isinstance(j, dict):
        return out
    out.update(format="json_token", location=j.get("location") if isinstance(j.get("location"), str) else None)
    for c in j.get("caveats", []):
        if not isinstance(c, dict):
            continue
        out["caveats"].append(f"{c.get('type')}={json.dumps(c.get('value'), separators=(',', ':'))}")
        if c.get("type") == "payment_hash" and isinstance(c.get("value"), str):
            out["payment_hash"] = c["value"].lower()
        if c.get("type") == "expiry" and isinstance(c.get("value"), int):
            out["expires_at"] = c["value"]
    return out


def credential_payment_hash(credential: str) -> Optional[str]:
    return credential_info(credential)["payment_hash"]


def parse_challenge(www_authenticate: str) -> Challenge:
    m = _SCHEME.search(www_authenticate or "")
    if not m:
        raise ChallengeError("not an L402/LSAT challenge")
    params = {k.lower(): v for k, v in _PARAM.findall(m.group(2))}
    name = "macaroon" if "macaroon" in params else "token" if "token" in params else None
    if not name or "invoice" not in params:
        raise ChallengeError("challenge needs a macaroon (or token) and an invoice")
    cred = params[name]
    info = credential_info(cred)
    return Challenge(prefix=m.group(1).upper(), credential=cred, invoice=params["invoice"], credential_param=name,
                     credential_payment_hash=info["payment_hash"], credential_location=info["location"],
                     credential_caveats=tuple(info["caveats"]), credential_expires_at=info["expires_at"])
