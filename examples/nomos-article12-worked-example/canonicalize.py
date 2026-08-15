#!/usr/bin/env python3
"""Canonical bytes + sha256 fingerprint of the synthetic transfer artifact.

Matches the property Allan described for .nomos: one standard representation
is locked down *before* fingerprinting, so field order, key spacing, and
formatting cannot change the digest. Later attestations (our /review proof,
a future NOMOS authority-gate seal) attach *to* this fingerprint; they do
not enter it.

Stdlib only. No JCS library — sorted keys + fixed separators is enough for
this fixture's documented subset (str / int / bool / dict / list / null;
no float).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ARTIFACT = HERE / "synthetic_fund_transfer_artifact.json"


def _reject_floats(obj, path: str = "$") -> None:
    if isinstance(obj, float) and not isinstance(obj, bool):
        raise ValueError(
            f"{path}: float {obj!r} is outside the locked subset "
            "(use int minor-units for money, ISO-8601 strings for time)"
        )
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_floats(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_floats(v, f"{path}[{i}]")


def canonicalize(obj: object) -> bytes:
    """Deterministic UTF-8 bytes. Field order and spacing cannot change this."""
    _reject_floats(obj)
    text = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return text.encode("utf-8")


def fingerprint(obj: object) -> str:
    digest = hashlib.sha256(canonicalize(obj)).hexdigest()
    return f"sha256:{digest}"


def load_artifact(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse as an object")
    return data


def _self_test(obj: dict) -> None:
    """Prove field-order / spacing cannot change the fingerprint."""
    a = fingerprint(obj)
    shuffled = json.loads(json.dumps(obj))
    # Re-insert keys in a different insertion order.
    shuffled = {k: shuffled[k] for k in reversed(list(shuffled))}
    b = fingerprint(shuffled)
    spaced = json.dumps(obj, indent=4, sort_keys=False).encode("utf-8")
    spaced_hash = "sha256:" + hashlib.sha256(spaced).hexdigest()
    if a != b:
        raise SystemExit(f"SELF-TEST FAIL: insertion order changed the fingerprint\n  {a}\n  {b}")
    if a == spaced_hash:
        raise SystemExit(
            "SELF-TEST FAIL: pretty-printed bytes hashed the same as canonical "
            "bytes — canonicalize() is not actually locking a representation"
        )
    print("self-test ok: insertion order invariant; pretty-print is a different digest")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    ap.add_argument("--write-fingerprint", type=Path, default=HERE / "artifact_fingerprint.txt")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    obj = load_artifact(args.artifact)
    if args.self_test:
        _self_test(obj)
    canon = canonicalize(obj)
    fp = fingerprint(obj)
    print(canon.decode("utf-8"))
    print(fp)
    args.write_fingerprint.write_text(fp + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
