"""Conformance tests for the AIR v0.3-draft-2 verdict-side dry-run.

A verifier with no failing case is a stamp, not a check. This file exercises
the live passing path (real relay-or-cached event, real verify_proof_event)
AND at least one deliberately-broken path (tampered artifact bytes; a
trust-policy that does not list our published key).
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from services.proof_signing import (  # noqa: E402
    PUBLISHED_PUBKEY,
    compute_decision_ref,
    verify_proof_event,
)

from verdict_binding import (  # noqa: E402
    SCHEME,
    SPEC_VERSION,
    authorization_sha256,
    binding_shape_errors,
    build_binding,
    jcs,
    obtain_event,
    point_in_time_axes,
    published_authority_ref,
)
from verify_dryrun import (  # noqa: E402
    STRUCTURALLY_INVALID,
    STRUCTURALLY_VALID_ZERO_AUTHORITY,
    VALID_AND_AUTHORIZED,
    classify_authority,
    fixture_flip,
    run_procedure,
    step5_coherence,
    tamper_artifact_bytes,
    write_policy_fixtures,
    _policies,
)


class RealArtifactMixin(unittest.TestCase):
    """Load the real #62 event once. Network only on a cold cache."""

    event: dict
    blob: bytes
    binding: dict
    obtain_meta: dict

    @classmethod
    def setUpClass(cls) -> None:
        if not PUBLISHED_PUBKEY:
            raise unittest.SkipTest("PUBLISHED_PUBKEY empty — .env / NOSTR_NSEC required")
        cls.event, cls.blob, cls.obtain_meta = obtain_event()
        cls.binding = build_binding(cls.event)
        write_policy_fixtures()


class TestBindingShape(RealArtifactMixin):
    def test_common_core_and_issuer_signed_conditional_set(self):
        b = self.binding
        self.assertEqual(b["scheme"], SCHEME)
        self.assertTrue(b["decision_ref"].startswith("sha256:"))
        self.assertEqual(b["trust_model"], "issuer_signed")
        self.assertEqual(b["authority_ref"], published_authority_ref())
        self.assertEqual(b["transport_hint"], "relay_event")
        self.assertEqual(b["authorization_uri"], f"nostr:{self.event['id']}")
        self.assertEqual(b["authorization_sha256"], hashlib.sha256(self.blob).hexdigest())
        self.assertEqual(b["authorization_sha256"], b["authorization_sha256"].lower())
        self.assertEqual(len(b["authorization_sha256"]), 64)
        self.assertNotIn("anchor", b)
        self.assertNotIn("locator", b)
        self.assertEqual(binding_shape_errors(b), [])

    def test_axes_match_worked_example_one(self):
        self.assertEqual(self.binding["axes"], point_in_time_axes())
        self.assertEqual(
            self.binding["axes"],
            {"precedence": {"field": "created_at"}, "freshness": None, "correctness": None},
        )
        # Omission of a key is a different canonical form.
        omitted = dict(self.binding)
        omitted["axes"] = {"precedence": {"field": "created_at"}, "freshness": None}
        errs = binding_shape_errors(omitted)
        self.assertTrue(any("correctness" in e for e in errs), errs)

    def test_uppercase_digest_is_non_conforming(self):
        bad = dict(self.binding)
        bad["authorization_sha256"] = bad["authorization_sha256"].upper()
        errs = binding_shape_errors(bad)
        self.assertTrue(any("lowercase" in e for e in errs), errs)

    def test_chain_anchored_fields_illegal_on_issuer_signed(self):
        bad = dict(self.binding)
        bad["anchor"] = {"chain_id": "eip155:8453"}
        errs = binding_shape_errors(bad)
        self.assertTrue(any("anchor" in e for e in errs), errs)


class TestRealPassingPath(RealArtifactMixin):
    def test_verify_proof_event_on_fetched_bytes(self):
        result = verify_proof_event(self.event)
        print(
            f"[step3] valid={result['valid']} checks={result['checks']} "
            f"event_id={self.event['id']} source={self.obtain_meta.get('source')}"
        )
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["checks"]["id_integrity"])
        self.assertTrue(result["checks"]["signature_valid"])
        self.assertTrue(result["checks"]["issued_by_invinoveritas"])
        self.assertTrue(result["checks"]["is_proof_event"])
        self.assertTrue(result["checks"]["decision_ref_recomputes"])

    def test_decision_ref_recomputes_via_production_function(self):
        payload = json.loads(self.event["content"])
        declared = payload.get("decision_ref_preimage_fields")
        recomputed = compute_decision_ref(
            payload, tuple(declared) if isinstance(declared, list) else None
        )
        self.assertEqual(recomputed, payload["decision_ref"])
        self.assertEqual(recomputed, self.binding["decision_ref"])

    def test_procedure_steps_1_through_5_on_real_bytes(self):
        report = run_procedure(self.binding, self.blob, self.obtain_meta)
        statuses = {s["step"]: s["status"] for s in report["steps"]}
        print(f"[procedure] statuses={statuses} structural_ok={report['structural_ok']}")
        print(f"[procedure] sha256={authorization_sha256(self.event)}")
        self.assertEqual(statuses[1], "pass")
        self.assertEqual(statuses[2], "pass")
        self.assertEqual(statuses[3], "pass")
        self.assertEqual(statuses[4], "pass")
        self.assertEqual(statuses[5], "n/a")
        self.assertTrue(report["structural_ok"])
        # Step 4 found created_at on the envelope, matching worked example (1).
        fields = report["steps"][3]["fields"]
        prec = next(f for f in fields if f.get("axis") == "precedence")
        self.assertEqual(prec["field"], "created_at")
        self.assertEqual(prec["where"], "event")
        self.assertEqual(prec["value"], self.event["created_at"])

    def test_step5_is_na_for_point_in_time_without_state(self):
        result = step5_coherence(self.binding, self.event)
        self.assertEqual(result["status"], "n/a")
        self.assertIsNone(result["state"])


class TestDeliberateFailures(RealArtifactMixin):
    def test_tampered_byte_fails_step2(self):
        tampered = tamper_artifact_bytes(self.blob)
        self.assertNotEqual(hashlib.sha256(tampered).hexdigest(), self.binding["authorization_sha256"])
        report = run_procedure(self.binding, tampered)
        step2 = report["steps"][1]
        print(
            f"[tamper] step2={step2['status']} declared={step2.get('declared')} "
            f"recomputed={step2.get('recomputed')}"
        )
        self.assertEqual(step2["status"], "fail")
        self.assertFalse(step2["match"])
        self.assertFalse(report["structural_ok"])

    def test_tampered_bytes_classify_structurally_invalid(self):
        tampered = tamper_artifact_bytes(self.blob)
        accepts, _ = _policies()
        report = run_procedure(self.binding, tampered, policies=[accepts])
        klass = report["steps"][5]["classifications"][0]
        self.assertEqual(klass["classification"], STRUCTURALLY_INVALID)
        self.assertEqual(klass["trust_policy_id"], accepts["trust_policy_id"])
        # Policy listed us — classification still invalid. Authority is
        # downstream of structure; a listed key cannot rescue a bad hash.
        self.assertTrue(klass["listed_by_policy"])
        self.assertFalse(klass["structural_ok"])

    def test_excluding_policy_is_zero_authority_not_invalid(self):
        accepts, excludes = _policies()
        report = run_procedure(self.binding, self.blob, policies=[excludes])
        klass = report["steps"][5]["classifications"][0]
        print(
            f"[zero-authority] {klass['classification']} policy={klass['trust_policy_id']}"
        )
        self.assertTrue(report["structural_ok"])
        self.assertEqual(klass["classification"], STRUCTURALLY_VALID_ZERO_AUTHORITY)
        self.assertFalse(klass["listed_by_policy"])
        self.assertEqual(klass["trust_policy_id"], excludes["trust_policy_id"])
        # Same bundle under the accepting policy must flip, not stay put.
        other = classify_authority(
            structural_ok=True,
            authority_ref=self.binding["authority_ref"],
            policy=accepts,
        )
        self.assertEqual(other["classification"], VALID_AND_AUTHORIZED)

    def test_issuer_signed_fixture_flip_shows_all_three_states(self):
        flip = fixture_flip(self.binding, self.blob)
        print(f"[fixture-flip] demonstrated={flip['demonstrated']}")
        self.assertTrue(all(flip["demonstrated"].values()), flip)
        self.assertEqual(SPEC_VERSION, "0.3-draft-2")


class TestCanonicalizationIsPinned(RealArtifactMixin):
    def test_default_json_dumps_is_a_different_digest(self):
        """The relay-serialization gap is real: default dumps != JCS.

        This is the finding the dry-run owes the spec, not a test we
        'fix' by hashing whatever json.dumps emits.
        """
        default = json.dumps(self.event).encode("utf-8")
        jcs_digest = hashlib.sha256(self.blob).hexdigest()
        default_digest = hashlib.sha256(default).hexdigest()
        print(f"[canon] jcs={jcs_digest} default_dumps={default_digest}")
        self.assertEqual(jcs_digest, self.binding["authorization_sha256"])
        # If these ever collide it is luck of key order, not a requirement.
        # We only assert JCS is what we bound; the inequality is informational.
        if default_digest != jcs_digest:
            self.assertNotEqual(default_digest, jcs_digest)
        # And JCS is what production decision_ref already uses.
        self.assertEqual(self.blob, jcs(json.loads(self.blob.decode("utf-8"))).encode("utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
