#!/usr/bin/env python3
"""Cold checker for the invinoveritas work-acceptance record log (schema invinoveritas.work-acceptance.record_log.v1).

Python 3 stdlib only. It checks the published files against each other and needs nothing from us beyond the bytes:

  python3 record_log_check.py                                   # fetch the live index and every day file
  python3 record_log_check.py --dir ./log                       # or a local copy: index.json (or index.jsonl) + <date>.jsonl
  python3 record_log_check.py --key did:key:z6Mk...             # one producer's state

What it checks, per day:
  1. sha256(file) equals the index's file_sha256.
  2. The first line is the header; sha256(JCS(header)) equals the index's log_root.
  3. header.prev_root equals the previous day's log_root (the first day: 64 zeros); days are consecutive.
  4. The Merkle root over sha256(line) of the body equals header.merkle_root; n_enrollments / n_records match the body.
  5. Every enrollment line's Ed25519 signature verifies over "invinoveritas work-acceptance enrollment v1 <key>" with that key.
Across days:
  6. Append-only: every line of day N is in day N+1 unchanged, except producer_signature, which may only move from
     'absent' to 'present' or 'declined'. 'present' and 'declined' are final.
Per producer key (the latest day):
  7. records, present / absent / declined, and a decline rate over CLOSED records only (present + declined). With no closed
     records the rate is NOT_MEASURED, never 0. A key with no enrollment line is NOT_MEASURED (not enrolled): the log says
     nothing about it, and that is not the same fact as "no declines".

Not checked here: the OpenTimestamps proofs. Run `ots verify <date>.ots` against sha256 = log_root to tie each root to its
Bitcoin block. Completeness itself rests on the issuer listing every covered record; what this checker makes provable is
that nothing listed was later dropped, rewritten or re-dated.
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.request

SCHEMA = "invinoveritas.work-acceptance.record_log.v1"
GENESIS = "0" * 64
EMPTY_ROOT = hashlib.sha256(f"{SCHEMA}|empty".encode()).hexdigest()
ENROLL_STATEMENT = "invinoveritas work-acceptance enrollment v1 {key}"
DEFAULT_BASE = "https://api.babyblueviper.com/work-acceptance/records/log"


def jcs(v):
    # RFC 8785 for the values these files carry (objects, arrays, strings, integers)
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def merkle_root(leaves):
    if not leaves:
        return EMPTY_ROOT
    level = list(leaves)
    while len(level) > 1:
        level = [hashlib.sha256((level[i] + (level[i + 1] if i + 1 < len(level) else level[i])).encode()).hexdigest()
                 for i in range(0, len(level), 2)]
    return level[0]


# ---- Ed25519 verify (RFC 8032 section 5.1.7), stdlib only ----
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _recover_x(y, sign):
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P:
        x = x * _I % _P
    if (x * x - xx) % _P:
        return None
    if x == 0 and sign:
        return None
    return _P - x if (x & 1) != sign else x


def _decode_point(b):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    if y >= _P:
        return None
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s, p):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _eq(p, q):
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


_G = _decode_point(bytes.fromhex("5866666666666666666666666666666666666666666666666666666666666666"))


def ed25519_verify(pub, msg, sig):
    if len(sig) != 64:
        return False
    a, r = _decode_point(pub), _decode_point(sig[:32])
    s = int.from_bytes(sig[32:], "little")
    if a is None or r is None or s >= _L:
        return False
    k = int.from_bytes(hashlib.sha512(sig[:32] + pub + msg).digest(), "little") % _L
    return _eq(_mul(s, _G), _add(r, _mul(k, a)))


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def did_key_ed25519(key):
    """did:key:z6Mk... -> 32-byte Ed25519 public key, or None."""
    if not key.startswith("did:key:z"):
        return None
    n = 0
    for ch in key[len("did:key:z"):]:
        if ch not in _B58:
            return None
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    raw = b"\x00" * (len(key[len("did:key:z"):]) - len(key[len("did:key:z"):].lstrip("1"))) + raw
    return raw[2:] if len(raw) == 34 and raw[:2] == b"\xed\x01" else None


# ---- loading ----
def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "record_log_check/1"}), timeout=30) as r:
        return r.read()


def load(args):
    if args.dir:
        for name in ("index.json", "index.jsonl"):
            p = os.path.join(args.dir, name)
            if os.path.exists(p):
                raw = open(p, "rb").read().decode()
                days = json.loads(raw)["days"] if name == "index.json" else [json.loads(x) for x in raw.splitlines() if x.strip()]
                break
        else:
            sys.exit(f"no index.json or index.jsonl in {args.dir}")
        return days, lambda d: open(os.path.join(args.dir, f"{d}.jsonl"), "rb").read()
    idx = json.loads(fetch(args.base))
    if idx.get("schema") != SCHEMA:
        sys.exit(f"unexpected schema {idx.get('schema')!r}")
    return idx["days"], lambda d: fetch(f"{args.base}/{d}.jsonl")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=DEFAULT_BASE, help="log index URL (default: the live one)")
    ap.add_argument("--dir", help="local directory instead of fetching")
    ap.add_argument("--key", action="append", default=[], help="report this producer key (repeatable)")
    args = ap.parse_args()

    days, read = load(args)
    days = sorted(days, key=lambda x: x["date"])
    fails, prev_root, prev_lines, prev_date = [], GENESIS, None, None
    import datetime as dt

    def fail(msg):
        fails.append(msg)
        print("FAIL " + msg)

    last_body = []
    for day in days:
        d = day["date"]
        data = read(d)
        if hashlib.sha256(data).hexdigest() != day["file_sha256"]:
            fail(f"{d}: sha256(file) != index file_sha256")
        rows = data.decode("utf-8").split("\n")
        if rows and rows[-1] == "":
            rows = rows[:-1]
        try:
            header, body = json.loads(rows[0]), rows[1:]
            lines = [json.loads(x) for x in body]
        except (ValueError, IndexError):
            fail(f"{d}: a line is not JSON; day not checked further")
            continue
        if header.get("schema") != SCHEMA or header.get("date") != d:
            fail(f"{d}: header schema/date mismatch")
        if jcs(header).decode() != rows[0]:
            fail(f"{d}: header line is not JCS")
        root = hashlib.sha256(jcs(header)).hexdigest()
        if root != day["log_root"]:
            fail(f"{d}: sha256(JCS(header)) {root[:12]} != index log_root {day['log_root'][:12]}")
        if header.get("prev_root") != prev_root:
            fail(f"{d}: prev_root {str(header.get('prev_root'))[:12]} does not chain to {prev_root[:12]}")
        if prev_date and dt.date.fromisoformat(d) != dt.date.fromisoformat(prev_date) + dt.timedelta(days=1):
            fail(f"{d}: not the day after {prev_date}")
        if merkle_root([hashlib.sha256(b.encode()).hexdigest() for b in body]) != header.get("merkle_root"):
            fail(f"{d}: merkle_root does not recompute")
        if any(jcs(x).decode() != b for x, b in zip(lines, body)):
            fail(f"{d}: a body line is not JCS")
        n_e = sum(1 for x in lines if x.get("type") == "enrollment")
        n_r = sum(1 for x in lines if x.get("type") == "record")
        if (n_e, n_r) != (header.get("n_enrollments"), header.get("n_records")):
            fail(f"{d}: header counts {header.get('n_enrollments')}/{header.get('n_records')} != body {n_e}/{n_r}")
        for e in (x for x in lines if x.get("type") == "enrollment"):
            pub = did_key_ed25519(e.get("key", ""))
            ok = pub is not None and e.get("statement") == ENROLL_STATEMENT.format(key=e["key"])
            try:
                import base64
                ok = ok and ed25519_verify(pub, e["statement"].encode(), base64.b64decode(e.get("signature", ""), validate=True))
            except ValueError:
                ok = False
            if not ok:
                fail(f"{d}: enrollment signature does not verify for {e.get('key')}")
        if prev_lines is not None:
            cur = {(x["type"], x.get("key") or x.get("receipt_sha256")): x for x in lines}
            for k, old in prev_lines.items():
                new = cur.get(k)
                if new is None:
                    fail(f"{d}: {k[0]} {k[1][:16]} listed on {prev_date} is missing")
                    continue
                strip = lambda x: {a: b for a, b in x.items() if a != "producer_signature"}
                if strip(new) != strip(old):
                    fail(f"{d}: {k[0]} {k[1][:16]} changed since {prev_date}")
                o, n = old.get("producer_signature"), new.get("producer_signature")
                if o != n and o != "absent":
                    fail(f"{d}: record {k[1][:16]} moved {o} -> {n} (only 'absent' may change)")
        print(f"ok   {d}: log_root {root[:16]} chains to {prev_root[:16]}; {n_e} enrollments, {n_r} records"
              + (f"; Bitcoin block {day['bitcoin_block_height']} per index (check with ots verify)" if day.get("bitcoin_block_height") else ""))
        prev_root, prev_date, last_body = root, d, lines
        prev_lines = {(x["type"], x.get("key") or x.get("receipt_sha256")): x for x in lines}

    enrolled = {x["key"] for x in last_body if x.get("type") == "enrollment"}
    keys = list(dict.fromkeys(args.key or sorted(enrolled)))
    print(f"\nproducers (as of {prev_date or 'no days'}):" if keys else f"\nproducers (as of {prev_date or 'no days'}): none enrolled, so no producer is measurable")
    for k in keys:
        if k not in enrolled:
            print(f"  {k}: NOT_MEASURED (not enrolled; the log says nothing about this key)")
            continue
        st = [x["producer_signature"] for x in last_body if x.get("type") == "record" and x.get("producer_key") == k]
        p, a, dcl = st.count("present"), st.count("absent"), st.count("declined")
        closed = p + dcl
        rate = f"{dcl}/{closed} declined" if closed else "NOT_MEASURED (no closed records)"
        print(f"  {k}: {len(st)} records (present {p}, absent {a}, declined {dcl}); decline rate {rate}")

    print(f"\n{'FAILED: ' + str(len(fails)) if fails else 'ALL CHECKS PASS'} ({len(days)} days)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
