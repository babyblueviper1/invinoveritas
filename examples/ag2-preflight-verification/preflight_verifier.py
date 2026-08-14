"""AG2 pre-flight verifier backed by invinoveritas /review + /verify-proof.

Implements safal207's PreflightVerifier Protocol (ag2ai/ag2#3156) by composing
against the production mechanism already running at api.babyblueviper.com:

    intent_ref  == sha256(JCS(canonical_arguments))
                == production artifact_hash when the JCS string is what /review hashed
    decision_ref == sha256(JCS({artifact_hash, artifact_type, policy_version,
                                verdict, source_class, ...}))
                 == a signed binding of a verdict to that exact artifact_hash

The core invariant this file enforces:

    preflight_verdict.intent_ref == proposed_action.intent_ref
    AND both equal sha256(JCS(canonical_arguments))

A validly-signed verdict that binds a different intent_ref does not authorize
execution. Binding is derived from canonical bytes, never from a producer-
asserted label.

Two fields on safal207's contract have no production counterpart today
(confirmed against services/proof_signing.py and routes/inference.py):

    * logical_operation_id / execution_id — each submitted artifact is
      independent. Identical canonical bytes recompute the same decision_ref
      (content-addressed idempotency), but nothing names "attempt 2 of
      operation X". Retry reuse below is implemented in THIS example gate.
    * revalidate_if — production proofs do not emit this. The gate honors it
      when a verdict carries it; our issuer always returns [].
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from preflight_contract import PreflightVerdict, PreflightVerifier, ProposedAction  # noqa: E402

REVIEW_URL = "https://api.babyblueviper.com/review"
VERIFY_PROOF_URL = "https://api.babyblueviper.com/verify-proof"
DEFAULT_VERIFIER_ID = "invinoveritas"

# Production JCS used by compute_decision_ref / sign_payload (RFC 8785 subset:
# lexicographic keys, compact separators, raw UTF-8). Same call as
# services/proof_signing.py — not the restricted AISP demo subset.
def jcs(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def derive_intent_ref(canonical_arguments: dict[str, Any]) -> str:
    """sha256(JCS(canonical_arguments)) — the frozen intent binding.

    Production artifact_hash is sha256 of the raw submitted artifact string
    (not a re-canonicalization of structured JSON). Submitting this JCS
    string as /review's artifact makes artifact_hash == intent_ref.
    """
    return hashlib.sha256(jcs(canonical_arguments).encode("utf-8")).hexdigest()


def map_review_verdict(review_verdict: str | None) -> Literal["allow", "deny", "refer"]:
    """Map /review's three-way verdict onto safal207's three-way decision.

    approve                -> allow
    reject                 -> deny
    approve_with_concerns  -> refer   (residual concern; do not collapse to binary)
    anything else          -> refer   (cannot determine is not an allow)
    """
    if review_verdict == "approve":
        return "allow"
    if review_verdict == "reject":
        return "deny"
    return "refer"


def _utc(ts: int | float | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def _load_api_key(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit.strip() or None
    env = os.environ.get("OPERATOR_FULL_API_KEY") or os.environ.get("INVINO_API_KEY")
    if env:
        return env.strip()
    env_path = _ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            if line.startswith("OPERATOR_FULL_API_KEY="):
                return line.split("=", 1)[1].strip() or None
    return None


def _artifact_type_for(tool_name: str) -> str:
    name = (tool_name or "").lower()
    onchain = (
        "transfer", "swap", "approve", "allowance", "bridge", "erc20",
        "erc721", "onchain", "tx", "web3",
    )
    if any(tok in name for tok in onchain):
        return "onchain_action"
    return "plan"


@dataclass
class GateResult:
    """Middleware outcome — not part of safal207's dataclass contract.

    `eligible` means the join held (binding recomputed, proof valid, not
    expired). The next layer (TealTiger / deterministic per-call gate) then
    sees `decision`. `may_execute` is True only for eligible + allow.
    """
    outcome: Literal["eligible", "blocked"]
    reason_code: str
    reason: str
    decision: Literal["allow", "deny", "refer"] | None = None
    verdict: PreflightVerdict | None = None
    reused: bool = False
    proof_checks: dict[str, Any] | None = None

    @property
    def may_execute(self) -> bool:
        return self.outcome == "eligible" and self.decision == "allow"


class InvinoveritasPreflightVerifier:
    """Issues an intent-bound PreflightVerdict via production /review(sign=true).

    After the HTTP call, independently re-verifies the signed event with
    services.proof_signing.verify_proof_event (the same function /verify-proof
    runs) and refuses to treat a proof as authority unless:

      * the schnorr envelope is valid and issued by the published key
      * decision_ref recomputes from the proof's own preimage fields
      * artifact_hash == sha256(JCS(canonical_arguments))  (derived, not claimed)
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        review_url: str = REVIEW_URL,
        timeout_seconds: float = 30.0,
        review_call: Callable[[ProposedAction, str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.api_key = _load_api_key(api_key)
        self.review_url = review_url
        self.timeout_seconds = timeout_seconds
        self.review_call = review_call

    async def verify(self, action: ProposedAction) -> PreflightVerdict:
        derived = derive_intent_ref(action.canonical_arguments)
        artifact = jcs(action.canonical_arguments)
        artifact_type = _artifact_type_for(action.tool_name)
        raw = await asyncio.to_thread(
            self._call_review, artifact, artifact_type, action,
        )
        return self.verdict_from_review_response(raw, derived_intent_ref=derived)

    def _call_review(self, artifact: str, artifact_type: str, action: ProposedAction) -> dict[str, Any]:
        if self.review_call is not None:
            return self.review_call(action, artifact, artifact_type)
        if not self.api_key:
            raise RuntimeError(
                "no API key (pass api_key=, set OPERATOR_FULL_API_KEY / INVINO_API_KEY, "
                "or put OPERATOR_FULL_API_KEY in the repo .env)"
            )
        body = json.dumps({
            "artifact": artifact,
            "artifact_type": artifact_type,
            "sign": True,
            "context": (
                f"AG2 pre-flight of tool {action.tool_name!r} "
                f"(logical_operation_id={action.logical_operation_id}, "
                f"execution_id={action.execution_id}). "
                "Judge whether this planned tool call is sound to release."
            ),
        }).encode("utf-8")
        req = urllib.request.Request(
            self.review_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"/review HTTP {exc.code}: {detail}") from exc

    def verdict_from_review_response(
        self,
        response: dict[str, Any],
        *,
        derived_intent_ref: str,
    ) -> PreflightVerdict:
        proof = response.get("proof") or {}
        event = proof.get("event") or {}
        payload = proof.get("proof_payload") or {}
        if not payload and isinstance(event.get("content"), str):
            try:
                payload = json.loads(event["content"])
            except json.JSONDecodeError:
                payload = {}

        checks = self.recompute_proof_binding(event, derived_intent_ref)
        if not checks["binding_ok"]:
            # Keep the hash the proof actually binds (or empty), not the
            # derived intent. Putting derived_intent_ref here would make the
            # gate's join look successful and turn a mismatch into a plain deny.
            claimed = str(payload.get("artifact_hash") or "")
            return PreflightVerdict(
                verdict_id=str(event.get("id") or payload.get("decision_ref") or "unverified"),
                intent_ref=claimed,
                decision="deny",
                verifier_id=DEFAULT_VERIFIER_ID,
                authority_basis=f"proof_binding_failed:{checks['binding_reason']}",
                evidence_refs=[f"reason:{checks['binding_reason']}"],
                issued_at=_utc(payload.get("verified_at") or time.time()),
                expires_at=None,
                revalidate_if=[],
            )

        evidence_refs: list[str] = []
        if payload.get("decision_ref"):
            evidence_refs.append(str(payload["decision_ref"]))
        if event.get("id"):
            evidence_refs.append(f"nostr:{event['id']}")
        if payload.get("artifact_hash"):
            evidence_refs.append(f"artifact_hash:{payload['artifact_hash']}")

        mediator = payload.get("mediator_evidence") or {}
        authority = mediator.get("authority_basis") or (
            f"source_class={payload.get('source_class')}" if payload.get("source_class") else None
        )

        return PreflightVerdict(
            verdict_id=str(event.get("id") or payload.get("decision_ref") or ""),
            intent_ref=derived_intent_ref,
            decision=map_review_verdict(payload.get("verdict") or response.get("verdict")),
            verifier_id=str(payload.get("verifier_pubkey") or DEFAULT_VERIFIER_ID),
            authority_basis=authority,
            evidence_refs=evidence_refs,
            issued_at=_utc(payload.get("verified_at")),
            expires_at=None,          # production proofs do not carry expiry
            revalidate_if=[],         # production proofs do not declare revalidate_if
        )

    @staticmethod
    def recompute_proof_binding(event: dict[str, Any], expected_intent_ref: str) -> dict[str, Any]:
        """Independent recompute — same function /verify-proof uses, plus the
        artifact_hash == derived intent_ref check the HTTP handler only runs
        when expect_artifact_hash is passed.
        """
        from services.proof_signing import compute_decision_ref, verify_proof_event

        result = verify_proof_event(event)
        payload = result.get("proof_payload") or {}
        claimed_hash = str(payload.get("artifact_hash") or "")
        hash_matches = claimed_hash.lower() == expected_intent_ref.lower()
        result.setdefault("checks", {})
        result["checks"]["artifact_hash_matches"] = hash_matches

        decision_ref_ok = result["checks"].get("decision_ref_recomputes")
        if payload.get("decision_ref") and decision_ref_ok is None:
            declared = payload.get("decision_ref_preimage_fields")
            fields = tuple(declared) if isinstance(declared, list) else None
            recomputed = compute_decision_ref(payload, fields)
            decision_ref_ok = recomputed == payload.get("decision_ref")
            result["checks"]["decision_ref_recomputes"] = decision_ref_ok

        envelope_ok = bool(result.get("valid"))
        binding_ok = envelope_ok and hash_matches and bool(decision_ref_ok)
        if not envelope_ok:
            reason = "proof_envelope_invalid"
        elif not hash_matches:
            reason = "artifact_hash_intent_ref_mismatch"
        elif not decision_ref_ok:
            reason = "decision_ref_recompute_failed"
        else:
            reason = "bound_and_verified"
        result["binding_ok"] = binding_ok
        result["binding_reason"] = reason
        return result


def verify_proof_over_http(event: dict[str, Any], expect_artifact_hash: str | None = None,
                           timeout_seconds: float = 15.0) -> dict[str, Any]:
    """POST /verify-proof (free, no-auth) — the public check a peer would run."""
    body: dict[str, Any] = {"event": event}
    if expect_artifact_hash:
        body["expect_artifact_hash"] = expect_artifact_hash
    req = urllib.request.Request(
        VERIFY_PROOF_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        return json.loads(resp.read())


class PreflightVerificationMiddleware:
    """Slow, once-per-logical-operation join in front of a fast per-call gate.

    Ordering (from the issue): freeze intent → this middleware → TealTiger →
    tool execution. `on_timeout` is fail-closed: only "deny" or "refer" are
    accepted; "allow" is refused so a hang cannot become an accidental allow.
    """

    def __init__(
        self,
        verifiers: list[PreflightVerifier] | None = None,
        *,
        required: bool = True,
        on_timeout: Literal["deny", "refer"] = "deny",
        timeout_seconds: float = 30.0,
    ) -> None:
        if on_timeout not in ("deny", "refer"):
            raise ValueError("on_timeout must be 'deny' or 'refer' (fail-closed; never allow)")
        self.verifiers = list(verifiers or [])
        self.required = required
        self.on_timeout = on_timeout
        self.timeout_seconds = timeout_seconds
        # Retry cache lives HERE, not in production /review. Keyed by
        # (logical_operation_id, derived_intent_ref). See README "honest gaps".
        self._cache: dict[tuple[str, str], PreflightVerdict] = {}

    def _derived_or_block(self, action: ProposedAction) -> tuple[str | None, GateResult | None]:
        derived = derive_intent_ref(action.canonical_arguments)
        if action.intent_ref and action.intent_ref != derived:
            return None, GateResult(
                outcome="blocked",
                reason_code="intent_ref_recompute_failed",
                reason=(
                    f"producer-asserted intent_ref {action.intent_ref} != "
                    f"sha256(JCS(canonical_arguments)) {derived}"
                ),
            )
        return derived, None

    def evaluate(
        self,
        action: ProposedAction,
        verdict: PreflightVerdict | None,
        *,
        now: datetime | None = None,
        reused: bool = False,
        proof_checks: dict[str, Any] | None = None,
    ) -> GateResult:
        """Pure join: given an action and an optional verdict, apply the contract."""
        clock = now or datetime.now(timezone.utc)
        derived, early = self._derived_or_block(action)
        if early is not None:
            return early
        assert derived is not None

        if verdict is None:
            if self.required:
                return GateResult(
                    outcome="blocked",
                    reason_code="required_evidence_missing",
                    reason="policy requires a pre-flight verdict and none was presented",
                )
            return GateResult(
                outcome="eligible",
                reason_code="no_attestation_required",
                reason="no verdict presented and required=False",
                decision="allow",
            )

        if verdict.intent_ref != derived:
            return GateResult(
                outcome="blocked",
                reason_code="intent_ref_mismatch",
                reason=(
                    f"preflight_verdict.intent_ref ({verdict.intent_ref}) != "
                    f"proposed_action.intent_ref ({derived})"
                ),
                verdict=verdict,
                reused=reused,
                proof_checks=proof_checks,
            )

        if verdict.expires_at is not None:
            exp = verdict.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if clock >= exp:
                return GateResult(
                    outcome="blocked",
                    reason_code="verdict_expired",
                    reason=f"verdict {verdict.verdict_id} expired at {exp.isoformat()}",
                    verdict=verdict,
                    reused=reused,
                )

        fired = self._revalidate_if_fired(action, verdict, derived, clock)
        if fired:
            return GateResult(
                outcome="blocked",
                reason_code="revalidate_required",
                reason=f"revalidate_if condition fired: {fired}",
                verdict=verdict,
                reused=reused,
            )

        return GateResult(
            outcome="eligible",
            reason_code="intent_bound_and_verified",
            reason="verdict binds the exact derived intent_ref; eligible for deterministic governance",
            decision=verdict.decision,
            verdict=verdict,
            reused=reused,
            proof_checks=proof_checks,
        )

    def _revalidate_if_fired(
        self,
        action: ProposedAction,
        verdict: PreflightVerdict,
        derived: str,
        clock: datetime,
    ) -> str | None:
        """Honor declared revalidate_if conditions. Unknown names fail closed.

        Production /review does not emit this field. The check exists so a
        verdict that DOES declare conditions (another verifier, or a future
        production field) cannot be reused past them.
        """
        for cond in verdict.revalidate_if or []:
            if cond in ("intent_ref_changed", "canonical_arguments_changed"):
                if verdict.intent_ref != derived:
                    return cond
                continue
            if cond == "expired":
                if verdict.expires_at is not None:
                    exp = verdict.expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if clock >= exp:
                        return cond
                continue
            if cond == "new_execution_id":
                # Explicit "never reuse across attempts" — we do not have this
                # signal in production; if a verdict declares it, honor it.
                return cond
            # Unknown condition: fail closed rather than silently ignore.
            return cond
        return None

    async def check(self, action: ProposedAction) -> GateResult:
        derived, early = self._derived_or_block(action)
        if early is not None:
            return early
        assert derived is not None

        cache_key = (action.logical_operation_id, derived)
        cached = self._cache.get(cache_key)
        if cached is not None:
            reused = self.evaluate(action, cached, reused=True)
            if reused.outcome == "eligible":
                return reused
            # Cached verdict no longer valid (expired / revalidate_if). Fall through.

        if not self.verifiers:
            return self.evaluate(action, None)

        verdicts: list[PreflightVerdict] = []
        for verifier in self.verifiers:
            try:
                verdict = await asyncio.wait_for(
                    verifier.verify(action),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError:
                return GateResult(
                    outcome="blocked",
                    reason_code="verifier_timeout",
                    reason=(
                        f"verifier {type(verifier).__name__} exceeded "
                        f"{self.timeout_seconds}s; on_timeout={self.on_timeout}"
                    ),
                    decision=self.on_timeout,
                )
            except Exception as exc:
                return GateResult(
                    outcome="blocked",
                    reason_code="verifier_error",
                    reason=f"verifier {type(verifier).__name__} failed closed: {type(exc).__name__}: {exc}",
                    decision="deny",
                )
            join = self.evaluate(action, verdict)
            if join.outcome == "blocked":
                return join
            verdicts.append(verdict)

        # Multiple verifiers: any deny wins; any refer (with no deny) refers;
        # allow only if every verifier allowed.
        final = verdicts[-1]
        if any(v.decision == "deny" for v in verdicts):
            final = next(v for v in verdicts if v.decision == "deny")
        elif any(v.decision == "refer" for v in verdicts):
            final = next(v for v in verdicts if v.decision == "refer")
        self._cache[cache_key] = final
        return self.evaluate(action, final)


def make_action(
    canonical_arguments: dict[str, Any],
    *,
    tool_name: str = "erc20_transfer",
    logical_operation_id: str = "op-1",
    execution_id: str = "exec-1",
    intent_ref: str | None = None,
) -> ProposedAction:
    derived = derive_intent_ref(canonical_arguments)
    return ProposedAction(
        logical_operation_id=logical_operation_id,
        execution_id=execution_id,
        intent_ref=derived if intent_ref is None else intent_ref,
        tool_name=tool_name,
        canonical_arguments=canonical_arguments,
    )


# A reckless unlimited-allowance transfer. Used by the live demo / tests so
# /review's onchain_action engine has something real to judge. Binding, not
# the specific verdict, is what the contract tests.
DEMO_ARGUMENTS: dict[str, Any] = {
    "action": "erc20_approve",
    "chainId": "8453",
    "token": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "spender": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
    "amount": "115792089237316195423570985008687907853269984665640564039457584007913129639935",
}


async def _demo() -> int:
    action = make_action(DEMO_ARGUMENTS, tool_name="erc20_approve")
    print(f"derived intent_ref = {action.intent_ref}")
    verifier = InvinoveritasPreflightVerifier()
    gate = PreflightVerificationMiddleware(verifiers=[verifier], required=True, on_timeout="deny")
    result = await gate.check(action)
    print(f"outcome     = {result.outcome}")
    print(f"reason_code = {result.reason_code}")
    print(f"decision    = {result.decision}")
    print(f"may_execute = {result.may_execute}")
    if result.verdict:
        print(f"verdict_id  = {result.verdict.verdict_id}")
        print(f"authority   = {result.verdict.authority_basis}")
        print(f"evidence    = {result.verdict.evidence_refs}")
    return 0 if result.reason_code in (
        "intent_bound_and_verified", "required_evidence_missing",
    ) or result.outcome in ("eligible", "blocked") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_demo()))
