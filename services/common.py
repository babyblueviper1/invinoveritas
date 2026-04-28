"""Shared primitives for autonomous services.

The service modules are intentionally JSON-first: every public method returns a
plain dict that can be stored, broadcast to Nostr, listed on the marketplace, or
consumed by another agent without adapter code.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}_{hashlib.sha256(raw).hexdigest()[:16]}"


@dataclass
class ServiceResult:
    service: str
    title: str
    payload: dict[str, Any]
    revenue_hint: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def result(service: str, title: str, payload: dict[str, Any], revenue_hint: str) -> dict[str, Any]:
    return ServiceResult(
        service=service,
        title=title,
        payload=payload,
        revenue_hint=revenue_hint,
        created_at=utc_now(),
    ).to_dict()

