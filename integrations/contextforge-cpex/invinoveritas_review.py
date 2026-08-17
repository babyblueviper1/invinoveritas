# -*- coding: utf-8 -*-
"""Location: ./integrations/contextforge_cpex/invinoveritas_review.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: babyblueviper1

invinoveritas /review gate for cpex's tool_pre_invoke hook.

Canonical source for this plugin. Originally shipped as a PR against
IBM/mcp-context-forge (github.com/IBM/mcp-context-forge/pull/6014, closed not
merged 2026-08-06 -- the maintainer, cafalchio, is consolidating plugins away
from per-repo entries toward a shared marketplace built on the standalone
`cpex` package, github.com/contextforge-org/cpex). Filed contextforge-org/cpex#159
asking about the submission process; the maintainer (terylt) confirmed 2026-08-17
this should target `cpex` 0.1.x directly ("go full legacy") rather than the
CMF/Extensions path, since that's being built into a separate, still-early
Rust dataplane (contextforge-org/contextforge-data-plane) he isn't involved in
planning. This file lives here until cpex's own marketplace submission model
is decided.

Gates every tool invocation on an independent, signed pre-action verdict from
invinoveritas (api.babyblueviper.com/review) BEFORE the tool runs, rather than
a rule-based auto_approve boolean. A reject verdict blocks the call by default;
approve/approve_with_concerns always lets it proceed unmodified.

Design mirrors the same discipline used in the invinoveritas AutoGen
GovernedWorkbench integration (integrations/autogen/governed_workbench.py):
  - FAIL-OPEN on any /review-side problem (network error, timeout, malformed
    response, missing key) -- the tool call proceeds as if ungated, never
    silently hangs or blocks the gateway because our service had a bad moment.
    `review_unavailable` is set on the result metadata so it's visible, not
    silent.
  - GATES on a real reject verdict by default (block_on_reject=true in plugin
    config). Set block_on_reject=false for an advisory/observe-only rollout
    that never blocks, only annotates every ToolPreInvokeResult with the
    verdict.
  - Optional sign=true attaches a portable, independently-verifiable signed
    proof (verify at https://api.babyblueviper.com/verify-proof, free, no
    auth) to every verdict, win or block.

CALLER-IDENTITY ENRICHMENT (new in this version, 2026-08-17): the original
PR#6014 version left `context` unused, noting only that "a future revision
could bind context.global_context.user into the /review context field for a
richer audit trail." This is that revision. cpex's `PluginContext` exposes
`user_context` (a structured `UserContext`: user_id, email, groups, roles,
is_admin, auth_method, service_account, delegation_chain, team_id) whenever
the host gateway propagates identity to plugins -- see cpex's own
`test_identity_propagation.py`. When present, we fold a compact snapshot of
it into BOTH the free-text `context` field (for the human reviewer) AND the
`artifact` JSON itself (so it becomes part of what a signed proof's
artifact_hash/decision_ref commits to, when sign=true) -- meaning the signed
verdict binds not just to "what tool, what arguments" but "who the gateway
says was really behind this call at the moment it was reviewed."

HONEST SCOPE, stated plainly (do not round this up): this does NOT flip our
own `/review` response's `source_class` field to `independent_mediator` --
that field is driven server-side by whether the CALLING API key is registered
in invinoveritas's own mediator registry, a separate mechanism (see
`registered_mediator_name` in services/proof_signing.py), unrelated to
whatever identity a gateway chooses to report about itself. What this DOES
do: it makes the review's own evidentiary basis richer and, when signed,
cryptographically commits to a specific caller-identity snapshot instead of
a bare tool-name/arguments pair a compromised or misconfigured gateway could
otherwise misrepresent after the fact. Two callers presenting different
identities for the identical tool_name/arguments will now produce different
artifact_hash/decision_ref values -- intentional, not a bug: the identity is
part of what's being committed to.

If the gateway never populates `user_context` (many deployments won't, or a
given call is unauthenticated), this plugin behaves exactly as the original
PR#6014 version did -- caller_identity is simply omitted, nothing else
changes.

Configuration (inside plugins/config.yaml ``config:`` block), see
PLUGIN_CONFIG below for every field and its default:

    config:
      api_key: null              # falls back to IVV_API_KEY env var
      base_url: "https://api.babyblueviper.com"
      block_on_reject: true
      sign: false
      artifact_type: "general"
      timeout_s: 15.0
      include_caller_identity: true   # NEW -- set false to opt out entirely
"""

# Standard
import json
import logging
import os
from typing import Any, Optional

# Third-Party
import httpx

# First-Party
from cpex.framework import Plugin, PluginContext, PluginResult, PluginViolation
from cpex.framework.hooks.tools import ToolPreInvokePayload, ToolPreInvokeResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.babyblueviper.com"
DEFAULT_TIMEOUT_S = 15.0
_VALID_VERDICTS = ("approve", "approve_with_concerns", "reject")

# UserContext fields worth surfacing to a reviewer/proof -- deliberately excludes
# `attributes` (open-ended, deployment-specific, could carry arbitrary/large/sensitive
# data we have no way to bound) and `authenticated_at` (timing noise, not identity).
_USER_CONTEXT_FIELDS = (
    "user_id", "email", "full_name", "is_admin", "groups", "roles",
    "team_id", "teams", "department", "auth_method", "service_account",
    "delegation_chain",
)


def _extract_caller_identity(context: PluginContext) -> Optional[dict[str, Any]]:
    """Best-effort snapshot of the gateway-reported caller identity, or None if the
    gateway never populated one (the common case for unauthenticated/legacy calls).

    Only includes fields the gateway EXPLICITLY set, via Pydantic's own
    ``model_fields_set`` -- not just "non-None, non-empty." A plain None/empty-list
    check would silently misrepresent a field like `is_admin` (bool, defaults to
    False): there is no way to distinguish "the gateway confirmed this caller is
    not an admin" from "the gateway never populated this field at all" by looking
    at the value alone, since both read as `False`. model_fields_set tracks
    construction-time explicitness directly, so an untouched default field is
    correctly omitted regardless of what its default happens to be.
    """
    uc = getattr(context, "user_context", None)
    if uc is None:
        return None
    fields_set = getattr(uc, "model_fields_set", None) or set()
    out: dict[str, Any] = {}
    for field in _USER_CONTEXT_FIELDS:
        if field not in fields_set:
            continue
        val = getattr(uc, field, None)
        if val is None:
            continue
        if isinstance(val, (list, tuple)) and len(val) == 0:
            continue
        out[field] = val
    return out or None


def _summarize_caller_identity(identity: dict[str, Any]) -> str:
    """Compact one-line human-readable summary for the /review `context` field."""
    parts = []
    if identity.get("user_id"):
        parts.append(f"user={identity['user_id']}")
    if identity.get("service_account"):
        parts.append(f"service_account={identity['service_account']}")
    if identity.get("delegation_chain"):
        parts.append(f"delegation_chain={identity['delegation_chain']}")
    if identity.get("auth_method"):
        parts.append(f"auth={identity['auth_method']}")
    if identity.get("is_admin"):
        parts.append("is_admin=true")
    return "caller_identity(" + ", ".join(parts) + ")" if parts else ""


class InvinoveritasReviewPlugin(Plugin):
    """Gates tool_pre_invoke on an invinoveritas /review verdict.

    See module docstring for the full design discipline (fail-open, block_on_reject,
    sign, caller-identity enrichment). Register free, instant, no payment:
    POST https://api.babyblueviper.com/register
    """

    async def initialize(self) -> None:
        """Parse the plugin config block into local settings, once at startup."""
        cfg = self._config.config or {}
        self._api_key: Optional[str] = cfg.get("api_key") or os.environ.get("IVV_API_KEY")
        self._base_url: str = cfg.get("base_url", DEFAULT_BASE_URL)
        self._block_on_reject: bool = cfg.get("block_on_reject", True)
        self._sign: bool = cfg.get("sign", False)
        self._artifact_type: str = cfg.get("artifact_type", "general")
        self._timeout_s: float = cfg.get("timeout_s", DEFAULT_TIMEOUT_S)
        self._include_caller_identity: bool = cfg.get("include_caller_identity", True)
        if not self._api_key:
            logger.warning(
                "InvinoveritasReviewPlugin: no IVV_API_KEY set (config.api_key or env var) -- "
                "every tool call will proceed UNGATED (review_unavailable). Register free at "
                "%s/register", self._base_url,
            )

    async def tool_pre_invoke(
        self,
        payload: ToolPreInvokePayload,
        context: PluginContext,
    ) -> ToolPreInvokeResult:
        """Called before every tool invocation.

        Args:
            payload: contains the tool name and invocation arguments.
            context: gateway-provided request context. When the gateway populates
                context.user_context, a caller-identity snapshot is folded into
                the review artifact and context string -- see module docstring's
                CALLER-IDENTITY ENRICHMENT section for the honest scope of what
                this does and does not change about the returned verdict.

        Returns:
            A ToolPreInvokeResult -- pass-through (with the verdict attached as
            metadata) or blocked with a PluginViolation on a reject verdict.
        """
        verdict = await self._review(payload, context)

        if verdict is None:
            # fail-open: either not configured, or the /review call itself failed
            return PluginResult(continue_processing=True, metadata={"invinoveritas_review": "unavailable"})

        if verdict.get("verdict") == "reject" and self._block_on_reject:
            violation = PluginViolation(
                reason="Independent invinoveritas /review verdict: reject",
                description=verdict.get("summary", "Blocked by an independent pre-action verdict."),
                code="IVV_REVIEW_REJECT",
                details={
                    "verdict": verdict.get("verdict"),
                    "confidence": verdict.get("confidence"),
                    "issues": verdict.get("issues"),
                    "verify_url": f"{self._base_url}/verify-proof",
                },
            )
            logger.warning(
                "InvinoveritasReviewPlugin BLOCK tool_pre_invoke | tool=%s | confidence=%s",
                payload.name, verdict.get("confidence"),
            )
            return PluginResult(continue_processing=False, violation=violation)

        return PluginResult(continue_processing=True, metadata={"invinoveritas_review": verdict})

    # ---- internals ----

    async def _review(
        self, payload: ToolPreInvokePayload, context: PluginContext
    ) -> Optional[dict[str, Any]]:
        """Returns the /review response dict, or None on any failure/misconfiguration
        (fail-open -- the caller treats None exactly like an approve, just without a
        verdict to attach)."""
        if not self._api_key:
            return None

        artifact_dict: dict[str, Any] = {"tool_name": payload.name, "arguments": dict(payload.args or {})}
        review_context = "cpex tool_pre_invoke"
        request_id = context.global_context.request_id if context.global_context else None
        if request_id:
            review_context += f", request_id={request_id}"

        caller_identity: Optional[dict[str, Any]] = None
        if self._include_caller_identity:
            try:
                caller_identity = _extract_caller_identity(context)
            except Exception:  # noqa: BLE001 -- identity extraction is best-effort, never blocks review
                logger.debug("InvinoveritasReviewPlugin: caller-identity extraction failed, omitting", exc_info=True)
        if caller_identity:
            artifact_dict["caller_identity"] = caller_identity
            summary = _summarize_caller_identity(caller_identity)
            if summary:
                review_context += f", {summary}"

        artifact = json.dumps(artifact_dict, default=str)
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(
                    f"{self._base_url}/review",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={
                        "artifact": artifact,
                        "artifact_type": self._artifact_type,
                        "context": review_context,
                        "sign": self._sign,
                    },
                )
            resp.raise_for_status()
            data = resp.json()
            if data.get("verdict") not in _VALID_VERDICTS:
                logger.warning(
                    "InvinoveritasReviewPlugin: malformed /review response for %r, failing open: %r",
                    payload.name, data,
                )
                return None
            logger.info(
                "InvinoveritasReviewPlugin: %r -> %s (confidence=%s, caller_identity=%s)",
                payload.name, data.get("verdict"), data.get("confidence"), bool(caller_identity),
            )
            return data
        except Exception as e:  # noqa: BLE001 -- fail-open on ANY error, by design
            logger.warning(
                "InvinoveritasReviewPlugin: /review call failed for %r (%s), failing open (review_unavailable)",
                payload.name, e,
            )
            return None
