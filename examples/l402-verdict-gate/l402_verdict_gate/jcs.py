"""RFC 8785 JSON Canonicalization (the subset invinoveritas hashes use). Standard library only."""
import json
import math


def _num(x):
    if isinstance(x, bool):
        raise TypeError
    if isinstance(x, int):
        return str(x)
    if not math.isfinite(x):
        raise ValueError("JCS: NaN and Infinity are not representable")
    if x == int(x) and abs(x) < 1e21:
        return str(int(x))
    r = repr(x)
    if "e" in r:  # ECMAScript exponent form: 1e-07, 1.5e+21
        m, e = r.split("e")
        e = int(e)
        r = f"{m}e{'+' if e > 0 else '-'}{abs(e)}"
    return r


def canonicalize(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return _num(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(canonicalize(x) for x in v) + "]"
    if isinstance(v, dict):
        keys = sorted(v, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + canonicalize(v[k]) for k in keys) + "}"
    raise TypeError(f"JCS: unsupported type {type(v).__name__}")
