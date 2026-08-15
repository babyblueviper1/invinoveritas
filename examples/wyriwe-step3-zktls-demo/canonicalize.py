#!/usr/bin/env python3
"""Canonical bytes + sha256 of the attested zkTLS payload.

Same discipline as examples/nomos-article12-worked-example/canonicalize.py:
sorted keys, separators=(',',':'), no floats. This is OUR inputHash over the
revealed attestation data — not a WYRIWE-spec field name.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _reject_floats(obj: Any, path: str = "$") -> None:
    if isinstance(obj, float) and not isinstance(obj, bool):
        raise ValueError(
            f"{path}: float {obj!r} is outside the locked subset "
            "(stringify numbers before hashing)"
        )
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_floats(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_floats(v, f"{path}[{i}]")


def canonicalize(obj: Any) -> bytes:
    _reject_floats(obj)
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def fingerprint(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonicalize(obj)).hexdigest()
