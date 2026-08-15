#!/usr/bin/env python3
"""Deploy-time bind: approved plan vs a fresh re-resolve of live flags/manifest.

The required fixture is two-sided: same flags must bind, and a
service_account A→B drift must refuse. A test that only checks
`bound is True` on the happy path would not have caught a no-op compare.
"""
from __future__ import annotations

import unittest

import approval_verifier as av
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
