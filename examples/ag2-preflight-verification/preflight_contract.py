"""Exact pre-flight contract from ag2ai/ag2#3156 (safal207, 2026-08-14).

Copied from the issue body's "Minimal contract" and "Possible API shape"
blocks, not paraphrased. Extra helpers live in preflight_verifier.py so this
file stays a faithful reproduction of the proposed seam.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol


@dataclass
class ProposedAction:
    logical_operation_id: str
    execution_id: str
    intent_ref: str
    tool_name: str
    canonical_arguments: dict[str, Any]


@dataclass
class PreflightVerdict:
    verdict_id: str
    intent_ref: str
    decision: Literal["allow", "deny", "refer"]
    verifier_id: str
    authority_basis: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    revalidate_if: list[str] = field(default_factory=list)


class PreflightVerifier(Protocol):
    async def verify(self, action: ProposedAction) -> PreflightVerdict: ...
