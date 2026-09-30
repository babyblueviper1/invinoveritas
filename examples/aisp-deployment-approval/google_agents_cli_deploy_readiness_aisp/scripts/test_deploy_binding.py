#!/usr/bin/env python3
"""Deploy-time bind: approved plan vs a fresh re-resolve of live flags/manifest.

The required fixture is two-sided: same flags must bind, and a
service_account A→B drift must refuse. A test that only checks
`bound is True` on the happy path would not have caught a no-op compare.
"""
from __future__ import annotations

import unittest

import approval_verifier as av
import deployment_approval_example as dae
import resolve_agents_cli_plan as resolver


SA_A = "sa-a@company-prod.iam.gserviceaccount.com"
SA_B = "sa-b@company-prod.iam.gserviceaccount.com"

BASE_FLAGS = {
    "--deployment-target": "cloud_run",
    "--project": "company-prod",
    "--region": "us-central1",
    "--service-name": "support-agent",
    "--service-account": SA_A,
    "--image": "us-central1-docker.pkg.dev/company-prod/support-agent/img:abc",
    "--cpu": "2",
    "--memory": "4Gi",
}


def _approved_plan(flags=None):
    result, plan = av.resolve_from_inputs(
        flags or BASE_FLAGS, None, defaults_mode="create",
        supplements={
            "environment": "production",
            "python_version": "3.13",
            "eval_evidence": "sha256:eval",
            "rollback_plan": "gcloud run services update-traffic ...",
            "observability_requirements": "logs+traces",
        },
    )
    return result, plan


class TestDeployBinding(unittest.TestCase):
    def test_same_flags_bind(self):
        _result, plan = _approved_plan()
        report = av.check_deploy_binding(plan, BASE_FLAGS, None)
        self.assertTrue(report["bound"], report)
        self.assertEqual(report["divergences"], [])
        av.assert_deploy_bound(plan, BASE_FLAGS, None)

    def test_service_account_drift_refuses(self):
        _result, plan = _approved_plan()
        drifted = dict(BASE_FLAGS)
        drifted["--service-account"] = SA_B
        report = av.check_deploy_binding(plan, drifted, None)
        self.assertFalse(report["bound"], report)
        fields = [d["field"] for d in report["divergences"]]
        self.assertEqual(fields, ["service_account"])
        diff = report["divergences"][0]
        self.assertEqual(diff["approved"], SA_A)
        self.assertEqual(diff["live"], SA_B)
        self.assertTrue(diff["approved_present"] and diff["live_present"])
        with self.assertRaises(av.PlanDivergenceError) as ctx:
            av.assert_deploy_bound(plan, drifted, None)
        self.assertIn("service_account", str(ctx.exception))
        self.assertEqual(ctx.exception.report["divergences"], report["divergences"])

    def test_region_drift_also_refuses(self):
        _result, plan = _approved_plan()
        drifted = dict(BASE_FLAGS)
        drifted["--region"] = "europe-west1"
        report = av.check_deploy_binding(plan, drifted, None)
        self.assertFalse(report["bound"])
        self.assertIn("region", [d["field"] for d in report["divergences"]])

    def test_policy_supplements_do_not_affect_bind(self):
        """rollback_plan lives only on the approved plan; it is not execution-relevant."""
        _result, plan = _approved_plan()
        self.assertIn("rollback_plan", plan)
        report = av.check_deploy_binding(plan, BASE_FLAGS, None)
        self.assertTrue(report["bound"], report)
        self.assertNotIn("rollback_plan", report["execution_relevant_fields"])

    def test_execution_supplement_refused_at_merge(self):
        result, _plan = av.resolve_from_inputs(
            {k: v for k, v in BASE_FLAGS.items() if k != "--service-account"},
            None, defaults_mode="create",
        )
        self.assertIn("service_account", result.absent_fields)
        with self.assertRaises(ValueError) as ctx:
            av.merge_supplements(result, {"service_account": SA_B})
        self.assertIn("execution-input", str(ctx.exception))

    def test_source_revision_supplement_refused(self):
        flags = {k: v for k, v in BASE_FLAGS.items() if k != "--image"}
        result, _plan = av.resolve_from_inputs(flags, None, defaults_mode="create")
        self.assertIn("source_revision", result.absent_fields)
        with self.assertRaises(ValueError) as ctx:
            av.merge_supplements(result, {
                "source_revision": "invented-sha",
                "rollback_plan": "undo",
            })
        self.assertIn("source_revision", str(ctx.exception))

    def test_policy_supplement_still_fills_absent(self):
        result, plan = av.resolve_from_inputs(
            BASE_FLAGS, None, defaults_mode="create",
            supplements={"rollback_plan": "undo via traffic split"},
        )
        self.assertEqual(plan["rollback_plan"], "undo via traffic split")
        self.assertNotIn("rollback_plan", result.plan)

    def test_compare_treats_absent_vs_present_as_divergence(self):
        approved = {"service_account": SA_A, "region": "us-central1"}
        live = {"region": "us-central1"}
        diffs = av.compare_execution_fields(approved, live)
        fields = {d["field"] for d in diffs}
        self.assertIn("service_account", fields)
        sa = next(d for d in diffs if d["field"] == "service_account")
        self.assertTrue(sa["approved_present"])
        self.assertFalse(sa["live_present"])


class TestUnsupportedExecutionFlagRefuses(unittest.TestCase):
    """A live execution-affecting flag with no field to diverge from must
    still refuse `bound`, not silently pass because nothing compared unequal."""

    def test_unmapped_execution_flag_present_refuses_even_with_matching_fields(self):
        _result, plan = _approved_plan()
        live = dict(BASE_FLAGS)
        live["--update-env-vars"] = "FEATURE_FLAG=on"
        report = av.check_deploy_binding(plan, live, None)
        self.assertEqual(report["divergences"], [])  # nothing to diverge from
        self.assertIn("update_env_vars", report["unsupported_execution_flags"])
        self.assertFalse(report["bound"], report)
        with self.assertRaises(av.PlanDivergenceError) as ctx:
            av.assert_deploy_bound(plan, live, None)
        self.assertIn("update_env_vars", str(ctx.exception))

    def test_control_flag_present_does_not_affect_bound(self):
        """no_wait etc. are control-flow, not execution-affecting -- must not refuse."""
        _result, plan = _approved_plan()
        live = dict(BASE_FLAGS)
        live["--no-wait"] = True
        report = av.check_deploy_binding(plan, live, None)
        self.assertEqual(report["unsupported_execution_flags"], [])
        self.assertTrue(report["bound"], report)


class TestDispatchGate(unittest.TestCase):
    """The actual dispatch gate: does check-then-dispatch really block dispatch,
    or only report a status a caller could ignore? Uses a stub deployment
    target so no real cloud call is needed, per optimization2026's ask."""

    def setUp(self):
        self.calls: list[dict] = []

    def _dispatch_fn(self, values: dict, argv=None) -> str:
        self.calls.append(values)
        return "dispatched-ok"

    def _valid_approval(self, plan):
        # Live issuance (real time.time() / fresh nonce), like the demo's real-verify
        # path -- the fixed v2 fixture timestamps are for byte-reproducible vectors
        # only and would already read as expired against a live clock.
        key = dae.PrivateKey(bytes.fromhex(dae.FIXED_TEST_SIGNING_KEY_HEX))
        return dae.build_approval_response(plan, approver="alice@example.com", signing_key=key)

    def test_invalid_approval_zero_dispatch_calls(self):
        _result, plan = _approved_plan()
        approval = self._valid_approval(plan)
        tampered = dict(approval)
        tampered["plan_sha256"] = "sha256:" + "0" * 64  # forged digest
        with self.assertRaises(av.DispatchRefused):
            av.dispatch_deploy(plan, tampered, BASE_FLAGS, None, self._dispatch_fn)
        self.assertEqual(self.calls, [])

    def test_execution_input_mismatch_zero_dispatch_calls(self):
        _result, plan = _approved_plan()
        approval = self._valid_approval(plan)
        drifted = dict(BASE_FLAGS)
        drifted["--service-account"] = SA_B
        with self.assertRaises(av.DispatchRefused) as ctx:
            av.dispatch_deploy(plan, approval, drifted, None, self._dispatch_fn)
        self.assertEqual(self.calls, [])
        self.assertIn("bind", ctx.exception.detail)
        self.assertFalse(ctx.exception.detail["bind"]["bound"])

    def test_matching_valid_inputs_dispatch_with_same_validated_values(self):
        _result, plan = _approved_plan()
        approval = self._valid_approval(plan)
        outcome = av.dispatch_deploy(plan, approval, BASE_FLAGS, None, self._dispatch_fn)
        self.assertTrue(outcome["dispatched"])
        self.assertEqual(len(self.calls), 1)
        dispatched_values = self.calls[0]
        # Every value dispatch received matches what the live re-resolve
        # confirmed, and matches the approved plan on the same fields.
        for field, value in dispatched_values.items():
            self.assertEqual(plan.get(field), value, field)
        self.assertEqual(outcome["dispatched_values"], dispatched_values)

    def test_unsupported_execution_flag_cannot_reach_dispatch(self):
        """The gap named directly: an execution-affecting input the adapter
        cannot account for must refuse, not silently produce a successful
        strict-path dispatch just because it matches on the fields it knows."""
        _result, plan = _approved_plan()
        approval = self._valid_approval(plan)
        live = dict(BASE_FLAGS)
        live["--update-env-vars"] = "SOME_VAR=malicious"
        with self.assertRaises(av.DispatchRefused) as ctx:
            av.dispatch_deploy(plan, approval, live, None, self._dispatch_fn)
        self.assertEqual(self.calls, [])
        self.assertIn(
            "update_env_vars", ctx.exception.detail["bind"]["unsupported_execution_flags"]
        )


class TestStrictArtifactIdentity(unittest.TestCase):
    """Strict mode: a matched mutable tag is not an immutable artifact identity."""

    DIGEST_IMAGE = "us-central1-docker.pkg.dev/company-prod/support-agent/img@sha256:" + "ab" * 32

    def setUp(self):
        self.calls: list[dict] = []

    def _dispatch_fn(self, values: dict, argv=None) -> str:
        self.calls.append(values)
        return "dispatched-ok"

    def _approval(self, plan):
        key = dae.PrivateKey(bytes.fromhex(dae.FIXED_TEST_SIGNING_KEY_HEX))
        return dae.build_approval_response(plan, approver="alice@example.com", signing_key=key)

    def test_mutable_tag_refuses_in_strict_mode_zero_calls(self):
        _result, plan = _approved_plan()  # BASE_FLAGS uses a :abc tag
        with self.assertRaises(av.DispatchRefused) as ctx:
            av.dispatch_deploy(plan, self._approval(plan), BASE_FLAGS, None,
                               self._dispatch_fn, require_immutable_artifact=True)
        self.assertEqual(self.calls, [])
        self.assertFalse(ctx.exception.detail["artifact"]["immutable"])

    def test_mutable_tag_is_reported_even_outside_strict_mode(self):
        _result, plan = _approved_plan()
        outcome = av.dispatch_deploy(plan, self._approval(plan), BASE_FLAGS, None, self._dispatch_fn)
        self.assertFalse(outcome["artifact"]["immutable"])

    def test_digest_pinned_image_dispatches_in_strict_mode(self):
        flags = dict(BASE_FLAGS, **{"--image": self.DIGEST_IMAGE})
        _result, plan = _approved_plan(flags)
        outcome = av.dispatch_deploy(plan, self._approval(plan), flags, None,
                                     self._dispatch_fn, require_immutable_artifact=True)
        self.assertTrue(outcome["artifact"]["immutable"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["source_revision"], self.DIGEST_IMAGE)

    def test_from_source_deploy_refuses_in_strict_mode(self):
        self.assertFalse(av.immutable_artifact_identity({"source_revision": None})["immutable"])
        self.assertFalse(av.immutable_artifact_identity({"source_revision": "img@sha256:short"})["immutable"])


class TestUnmappedFlagsAreNamed(unittest.TestCase):
    def test_named_execution_unmapped_flags_exist(self):
        named = set(resolver.UNMAPPED_EXECUTION_CLI_FLAGS)
        self.assertEqual(named, {
            "update_env_vars", "agent_identity", "port",
            "build_args", "cluster_name",
        })
        self.assertIn("no_wait", resolver.UNMAPPED_CONTROL_CLI_FLAGS)
        for flag in (
            "--update-env-vars", "--agent-identity", "--port",
            "--build-args", "--cluster-name", "--no-wait",
        ):
            dest = resolver._FLAG_ALIASES[flag]
            self.assertIn(dest, resolver.UNMAPPED_CLI_FLAGS)

    def test_unmapped_flag_is_reported_not_planned(self):
        flags = dict(BASE_FLAGS)
        flags["--port"] = "8080"
        flags["--no-wait"] = True
        result = resolver.resolve_agents_cli_plan(flags, None)
        self.assertIn("port", result.unmapped_cli_flags_present)
        self.assertIn("no_wait", result.unmapped_cli_flags_present)
        self.assertNotIn("port", result.plan)


if __name__ == "__main__":
    unittest.main()
