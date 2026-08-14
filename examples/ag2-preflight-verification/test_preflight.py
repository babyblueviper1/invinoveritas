"""Conformance tests for safal207's ag2ai/ag2#3156 pre-flight contract.

Covers the six failure-semantics cases named in the issue:

  1. matching evidence
  2. mismatched evidence (valid verdict, different intent_ref)
  3. missing required evidence
  4. expired / stale verdict
  5. retry / re-drive under the same logical_operation_id
  6. verifier timeout → fail-closed

Cases 1–3 also exercise the production binding (artifact_hash / decision_ref
recompute via services.proof_signing), not just the dataclass join. The live
/review + /verify-proof path runs when an API key is available; it is skipped
(not faked) otherwise.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from preflight_contract import PreflightVerdict, ProposedAction
from preflight_verifier import (
    DEMO_ARGUMENTS,
    InvinoveritasPreflightVerifier,
    PreflightVerificationMiddleware,
    derive_intent_ref,
    jcs,
    make_action,
    map_review_verdict,
)


def _run(coro):
    return asyncio.run(coro)


class _StaticVerifier:
    def __init__(self, verdict: PreflightVerdict | Exception, delay: float = 0.0):
        self.verdict = verdict
        self.delay = delay
        self.calls = 0

    async def verify(self, action: ProposedAction) -> PreflightVerdict:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


class _HandshakeIsolation(unittest.TestCase):
    """Redirect proof_signing's handshake DB so local issuance never touches prod."""

    def setUp(self):
        from services import proof_signing as ps
        if not ps.PUBLISHED_PUBKEY:
            self.skipTest("NOSTR_NSEC unset — cannot issue a real signed proof")
        self._ps = ps
        self._real_db = ps._HANDSHAKE_DB
        ps._HANDSHAKE_DB = os.path.join(tempfile.mkdtemp(), "hs_example.db")

    def tearDown(self):
        if getattr(self, "_ps", None) is None:
            return
        try:
            os.remove(self._ps._HANDSHAKE_DB)
        except OSError:
            pass
        self._ps._HANDSHAKE_DB = self._real_db

    def _issue(self, artifact: str, artifact_type: str = "plan",
               review_result: dict | None = None) -> dict:
        result = review_result or {
            "verdict": "reject",
            "confidence": 0.95,
            "summary": "example: unlimited allowance is not a sound release",
        }
        return self._ps.build_verdict_proof(artifact, artifact_type, result)


class TestIntentRefDerivation(unittest.TestCase):
    def test_derives_from_jcs_bytes_not_asserted_label(self):
        args = {"b": 2, "a": 1}
        # Key order in the dict must not matter.
        self.assertEqual(derive_intent_ref(args), derive_intent_ref({"a": 1, "b": 2}))
        expected = hashlib.sha256(jcs(args).encode("utf-8")).hexdigest()
        self.assertEqual(derive_intent_ref(args), expected)

    def test_same_jcs_as_production_compute_decision_ref(self):
        from services.proof_signing import compute_decision_ref
        fields = {
            "artifact_hash": "abc",
            "artifact_type": "plan",
            "policy_version": "test",
            "verdict": "reject",
            "source_class": "agent_reported",
        }
        # compute_decision_ref is sha256(JCS(preimage)); our jcs() is that JCS.
        preimage_fields = tuple(fields.keys())
        via_prod = compute_decision_ref(fields, preimage_fields)
        via_local = "sha256:" + hashlib.sha256(jcs(fields).encode("utf-8")).hexdigest()
        self.assertEqual(via_prod, via_local)

    def test_map_review_verdict_keeps_tri_state(self):
        self.assertEqual(map_review_verdict("approve"), "allow")
        self.assertEqual(map_review_verdict("reject"), "deny")
        self.assertEqual(map_review_verdict("approve_with_concerns"), "refer")
        self.assertEqual(map_review_verdict("???"), "refer")


class TestMatchingEvidence(_HandshakeIsolation):
    def test_matching_intent_ref_is_eligible(self):
        action = make_action(DEMO_ARGUMENTS, tool_name="erc20_approve")
        artifact = jcs(action.canonical_arguments)
        proof = self._issue(artifact, artifact_type="onchain_action")
        event = proof["event"]
        payload = proof["proof_payload"]

        self.assertEqual(payload["artifact_hash"], action.intent_ref)

        checks = InvinoveritasPreflightVerifier.recompute_proof_binding(event, action.intent_ref)
        self.assertTrue(checks["binding_ok"], checks)
        self.assertTrue(checks["checks"]["artifact_hash_matches"])
        self.assertTrue(checks["checks"]["decision_ref_recomputes"])
        self.assertTrue(checks["valid"])

        verdict = InvinoveritasPreflightVerifier().verdict_from_review_response(
            {"proof": proof, "verdict": payload["verdict"]},
            derived_intent_ref=action.intent_ref,
        )
        self.assertEqual(verdict.intent_ref, action.intent_ref)
        self.assertEqual(verdict.decision, map_review_verdict(payload["verdict"]))
        self.assertEqual(verdict.revalidate_if, [])
        self.assertIsNone(verdict.expires_at)

        gate = PreflightVerificationMiddleware(required=True)
        result = gate.evaluate(action, verdict, proof_checks=checks)
        self.assertEqual(result.outcome, "eligible")
        self.assertEqual(result.reason_code, "intent_bound_and_verified")
        self.assertEqual(result.decision, verdict.decision)
        print(
            f"[matching] eligible reason={result.reason_code} "
            f"decision={result.decision} artifact_hash={payload['artifact_hash'][:16]}… "
            f"decision_ref={payload['decision_ref']}"
        )


class TestMismatchedEvidence(_HandshakeIsolation):
    def test_valid_proof_for_different_intent_is_blocked(self):
        matching = make_action(DEMO_ARGUMENTS, tool_name="erc20_approve")
        other_args = {**DEMO_ARGUMENTS, "amount": "1"}
        other = make_action(other_args, tool_name="erc20_approve", execution_id="exec-other")
        self.assertNotEqual(matching.intent_ref, other.intent_ref)

        # Real signed proof bound to the UNLIMITED-amount intent.
        proof = self._issue(jcs(matching.canonical_arguments), artifact_type="onchain_action")
        event = proof["event"]

        # Envelope is valid against the original intent…
        good = InvinoveritasPreflightVerifier.recompute_proof_binding(event, matching.intent_ref)
        self.assertTrue(good["valid"])
        self.assertTrue(good["binding_ok"])

        # …and must NOT authorize the tampered amount, even though the
        # signature is the same valid signature.
        bad = InvinoveritasPreflightVerifier.recompute_proof_binding(event, other.intent_ref)
        self.assertTrue(bad["valid"], "signature is still valid — that is the point")
        self.assertFalse(bad["checks"]["artifact_hash_matches"])
        self.assertFalse(bad["binding_ok"])
        self.assertEqual(bad["binding_reason"], "artifact_hash_intent_ref_mismatch")

        # The adapter therefore issues a deny bound to the *presented* intent,
        # and the gate blocks a verdict that still carries the original hash
        # if we force that hash onto the verdict (the actual attack).
        stolen = PreflightVerdict(
            verdict_id=event["id"],
            intent_ref=proof["proof_payload"]["artifact_hash"],  # the OTHER intent
            decision="allow",  # attacker claims allow
            verifier_id="invinoveritas",
        )
        gate = PreflightVerificationMiddleware(required=True)
        result = gate.evaluate(other, stolen)
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason_code, "intent_ref_mismatch")
        self.assertFalse(result.may_execute)

        # Adapter path: wrapping the same valid-but-wrong-bound proof must
        # not produce a join-eligible deny on the *presented* intent.
        wrapped = InvinoveritasPreflightVerifier().verdict_from_review_response(
            {"proof": proof, "verdict": proof["proof_payload"]["verdict"]},
            derived_intent_ref=other.intent_ref,
        )
        self.assertEqual(wrapped.intent_ref, matching.intent_ref)
        self.assertNotEqual(wrapped.intent_ref, other.intent_ref)
        adapted = gate.evaluate(other, wrapped)
        self.assertEqual(adapted.reason_code, "intent_ref_mismatch")
        print(
            f"[mismatched] blocked reason={result.reason_code} "
            f"verdict.intent_ref={stolen.intent_ref[:16]}… "
            f"action.intent_ref={other.intent_ref[:16]}… "
            f"sig_valid={bad['valid']} binding_ok={bad['binding_ok']}"
        )

    def test_producer_asserted_intent_ref_is_not_trusted(self):
        action = make_action(DEMO_ARGUMENTS, intent_ref="0" * 64)
        gate = PreflightVerificationMiddleware(required=True)
        result = gate.evaluate(action, None)
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason_code, "intent_ref_recompute_failed")


class TestMissingEvidence(unittest.TestCase):
    def test_missing_required_verdict_is_blocked(self):
        action = make_action(DEMO_ARGUMENTS)
        gate = PreflightVerificationMiddleware(required=True)
        result = gate.evaluate(action, None)
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason_code, "required_evidence_missing")
        self.assertFalse(result.may_execute)
        print(f"[missing] blocked reason={result.reason_code}")

    def test_missing_is_distinct_from_mismatch(self):
        action = make_action(DEMO_ARGUMENTS)
        other_ref = derive_intent_ref({**DEMO_ARGUMENTS, "amount": "1"})
        mismatched = PreflightVerdict(
            verdict_id="v1", intent_ref=other_ref, decision="allow", verifier_id="x",
        )
        gate = PreflightVerificationMiddleware(required=True)
        missing = gate.evaluate(action, None)
        mismatch = gate.evaluate(action, mismatched)
        self.assertEqual(missing.reason_code, "required_evidence_missing")
        self.assertEqual(mismatch.reason_code, "intent_ref_mismatch")
        self.assertNotEqual(missing.reason_code, mismatch.reason_code)


class TestExpiredVerdict(unittest.TestCase):
    def test_expired_verdict_is_blocked(self):
        action = make_action(DEMO_ARGUMENTS)
        now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
        verdict = PreflightVerdict(
            verdict_id="v-exp",
            intent_ref=action.intent_ref,
            decision="allow",
            verifier_id="invinoveritas",
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(seconds=1),
        )
        gate = PreflightVerificationMiddleware(required=True)
        result = gate.evaluate(action, verdict, now=now)
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason_code, "verdict_expired")
        self.assertFalse(result.may_execute)
        print(f"[expired] blocked reason={result.reason_code} expires_at={verdict.expires_at.isoformat()}")


class TestRetryReuse(unittest.TestCase):
    def test_retry_reuses_verdict_when_intent_unchanged(self):
        args = dict(DEMO_ARGUMENTS)
        first = make_action(args, logical_operation_id="op-retry", execution_id="exec-1")
        verdict = PreflightVerdict(
            verdict_id="v-retry",
            intent_ref=first.intent_ref,
            decision="allow",
            verifier_id="invinoveritas",
        )
        static = _StaticVerifier(verdict)
        gate = PreflightVerificationMiddleware(verifiers=[static], required=True)

        r1 = _run(gate.check(first))
        self.assertEqual(r1.outcome, "eligible")
        self.assertFalse(r1.reused)
        self.assertEqual(static.calls, 1)

        second = make_action(
            args,
            logical_operation_id="op-retry",
            execution_id="exec-2",  # new attempt, same logical operation
        )
        self.assertEqual(second.intent_ref, first.intent_ref)
        self.assertNotEqual(second.execution_id, first.execution_id)

        r2 = _run(gate.check(second))
        self.assertEqual(r2.outcome, "eligible")
        self.assertTrue(r2.reused)
        self.assertEqual(static.calls, 1, "verifier must not be re-invoked on an unchanged intent")
        print(
            f"[retry] reused={r2.reused} calls={static.calls} "
            f"logical={second.logical_operation_id} "
            f"exec {first.execution_id}->{second.execution_id}"
        )

    def test_retry_does_not_reuse_when_intent_changes(self):
        first = make_action(DEMO_ARGUMENTS, logical_operation_id="op-retry2", execution_id="exec-1")
        verdict = PreflightVerdict(
            verdict_id="v-retry2",
            intent_ref=first.intent_ref,
            decision="allow",
            verifier_id="invinoveritas",
        )
        gate = PreflightVerificationMiddleware(verifiers=[_StaticVerifier(verdict)], required=True)
        self.assertEqual(_run(gate.check(first)).outcome, "eligible")

        changed = make_action(
            {**DEMO_ARGUMENTS, "amount": "1"},
            logical_operation_id="op-retry2",
            execution_id="exec-2",
        )
        result = _run(gate.check(changed))
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason_code, "intent_ref_mismatch")


class TestVerifierTimeout(unittest.TestCase):
    def test_timeout_is_fail_closed(self):
        action = make_action(DEMO_ARGUMENTS)
        slow = _StaticVerifier(
            PreflightVerdict(
                verdict_id="too-late",
                intent_ref=action.intent_ref,
                decision="allow",
                verifier_id="slow",
            ),
            delay=0.4,
        )
        gate = PreflightVerificationMiddleware(
            verifiers=[slow], required=True, on_timeout="deny", timeout_seconds=0.05,
        )
        result = _run(gate.check(action))
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason_code, "verifier_timeout")
        self.assertEqual(result.decision, "deny")
        self.assertFalse(result.may_execute)
        print(f"[timeout] blocked reason={result.reason_code} on_timeout={result.decision}")

    def test_on_timeout_allow_is_refused(self):
        with self.assertRaises(ValueError):
            PreflightVerificationMiddleware(on_timeout="allow")  # type: ignore[arg-type]

    def test_verifier_exception_is_fail_closed(self):
        action = make_action(DEMO_ARGUMENTS)
        boom = _StaticVerifier(RuntimeError("upstream 503"))
        gate = PreflightVerificationMiddleware(verifiers=[boom], required=True)
        result = _run(gate.check(action))
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason_code, "verifier_error")
        self.assertEqual(result.decision, "deny")


class TestRevalidateIf(unittest.TestCase):
    def test_unknown_revalidate_if_fails_closed(self):
        action = make_action(DEMO_ARGUMENTS)
        verdict = PreflightVerdict(
            verdict_id="v-rev",
            intent_ref=action.intent_ref,
            decision="allow",
            verifier_id="invinoveritas",
            revalidate_if=["market_moved_2pct"],  # we cannot evaluate this
        )
        gate = PreflightVerificationMiddleware(required=True)
        result = gate.evaluate(action, verdict)
        self.assertEqual(result.outcome, "blocked")
        self.assertEqual(result.reason_code, "revalidate_required")

    def test_production_issuer_emits_empty_revalidate_if(self):
        # Honest: our adapter never claims a revalidate_if it cannot honor.
        action = make_action(DEMO_ARGUMENTS)
        verdict = InvinoveritasPreflightVerifier().verdict_from_review_response(
            {
                "verdict": "reject",
                "proof": {
                    "event": {},
                    "proof_payload": {
                        "verdict": "reject",
                        "artifact_hash": "nope",
                        "verified_at": 1,
                    },
                },
            },
            derived_intent_ref=action.intent_ref,
        )
        # Binding fails (no real event) → deny, and revalidate_if stays [].
        self.assertEqual(verdict.revalidate_if, [])
        self.assertIsNone(verdict.expires_at)


class TestLiveReviewAndVerifyProof(unittest.TestCase):
    """Real /review(sign=true) + /verify-proof when a key is present.

    Skipped (not mocked) if the key is missing or the HTTP call fails for a
    reason that is not the contract under test.
    """

    def test_live_review_binds_derived_intent_ref(self):
        from preflight_verifier import _load_api_key
        if not _load_api_key():
            self.skipTest("no OPERATOR_FULL_API_KEY / INVINO_API_KEY — live path skipped, not mocked")

        action = make_action(
            DEMO_ARGUMENTS,
            tool_name="erc20_approve",
            logical_operation_id="ag2-3156-example-live",
            execution_id="exec-live-1",
        )
        verifier = InvinoveritasPreflightVerifier()
        try:
            verdict = _run(verifier.verify(action))
        except Exception as exc:
            self.skipTest(f"live /review unavailable: {type(exc).__name__}: {exc}")

        self.assertEqual(verdict.intent_ref, action.intent_ref)
        self.assertIn(verdict.decision, ("allow", "deny", "refer"))
        self.assertEqual(verdict.revalidate_if, [])
        self.assertIsNone(verdict.expires_at)
        self.assertTrue(verdict.evidence_refs, "live verdict must carry decision_ref / event id")

        gate = PreflightVerificationMiddleware(required=True)
        result = gate.evaluate(action, verdict)
        self.assertEqual(result.outcome, "eligible")
        self.assertEqual(result.reason_code, "intent_bound_and_verified")

        http = _verify_by_event_id(verdict.verdict_id, action.intent_ref)
        self.assertTrue(http.get("valid"), http)
        self.assertTrue(http.get("checks", {}).get("artifact_hash_matches"), http.get("checks"))
        print(
            f"[live] /review verdict={verdict.decision} "
            f"verdict_id={verdict.verdict_id[:16]}… "
            f"intent_ref={verdict.intent_ref[:16]}… "
            f"/verify-proof valid={http.get('valid')} "
            f"artifact_hash_matches={http.get('checks', {}).get('artifact_hash_matches')}"
        )

        # Same live verdict must not authorize a different amount.
        tampered = make_action({**DEMO_ARGUMENTS, "amount": "1"}, tool_name="erc20_approve")
        stolen = PreflightVerdict(
            verdict_id=verdict.verdict_id,
            intent_ref=verdict.intent_ref,
            decision="allow",
            verifier_id=verdict.verifier_id,
            evidence_refs=list(verdict.evidence_refs),
        )
        mismatch = gate.evaluate(tampered, stolen)
        self.assertEqual(mismatch.reason_code, "intent_ref_mismatch")


def _verify_by_event_id(event_id: str, expect_artifact_hash: str) -> dict:
    import urllib.request
    body = json.dumps({"event_id": event_id, "expect_artifact_hash": expect_artifact_hash}).encode()
    req = urllib.request.Request(
        "https://api.babyblueviper.com/verify-proof",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
