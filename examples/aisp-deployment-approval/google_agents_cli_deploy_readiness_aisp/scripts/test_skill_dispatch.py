"""Integration test: the skill's deploy tool binding, end to end, against a recording stub target.

Entry point: the command the AISP `deploy` node names (deploy.step2 -> resource `deploy_dispatch` ->
`python3 scripts/approval_verifier.py dispatch ... --config verifier_config.json`), run as a subprocess
exactly as a runtime's code tool would run it.

What is MOCKED, stated so nothing here implies more than it shows:
  - the deploy target: $AGENTS_CLI_BIN points at a stub that appends its argv to a file and exits 0;
    no cloud call is made and real agents-cli is not invoked;
  - the human decision: approvals are built by this harness with the TEST-ONLY fixture key; no
    sys.io.confirm interaction and no AISOP/SoulBot runtime are exercised; the test runs the tool
    command the skill's deploy node names, not the runtime that would issue it.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(HERE))

import approval_verifier as av  # noqa: E402
import deployment_approval_example as dae  # noqa: E402
from test_deploy_binding import BASE_FLAGS, SA_B, _approved_plan  # noqa: E402

DIGEST_IMAGE = "us-central1-docker.pkg.dev/company-prod/support-agent/img@sha256:" + "ab" * 32


def _resign(env, key):
    signed = {k: env[k] for k in dae.SIGNED_FIELD_NAMES}
    env["signature"] = key.sign_schnorr(hashlib.sha256(dae._canon(signed).encode()).digest()).hex()
    return env


class TestSkillDispatchBinding(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.calls = self.tmp / "calls.jsonl"
        stub = self.tmp / "agents-cli"
        stub.write_text("#!/usr/bin/env python3\nimport json, sys\n"
                        f"open({str(self.calls)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        self.env = {**os.environ, "AGENTS_CLI_BIN": str(stub)}
        self.key = dae.PrivateKey(bytes.fromhex(dae.FIXED_TEST_SIGNING_KEY_HEX))
        cfg = json.loads((SKILL / "verifier_config.json").read_text())
        cfg["replay_store"] = str(self.tmp / "nonces.json")      # per-test store
        self.cfg = cfg

    # -- the skill names this command; take it from the skill file, not from memory ------------
    def test_deploy_node_binds_the_dispatch_tool(self):
        skill = json.loads((SKILL / "aisp.aisop.json").read_text())
        content = skill[1]["content"]
        deploy = content["aisop"]["functions"]["deploy"] if "functions" in content["aisop"] else content["functions"]["deploy"]
        self.assertIn("scripts/approval_verifier.py dispatch", deploy["step2"])
        self.assertIn("--config verifier_config.json", deploy["step2"])
        self.assertIn("sys.assert('deploy_result.dispatched == true'", deploy["step3"])
        ids = {r["id"] for r in content["aisp_contract"]["resources"]}
        self.assertTrue({"deploy_dispatch", "verifier_config"} <= ids)
        rules = {r["enforced_by"] for r in content["aisp_contract"]["non_negotiable"]}
        self.assertIn("deploy.step1:sys.assert", rules)

    def run_tool(self, plan, approval, flags=BASE_FLAGS, cfg=None, strict=False):
        def w(name, obj):
            p = self.tmp / name
            p.write_text(json.dumps(obj))
            return str(p)
        cmd = [sys.executable, str(HERE / "approval_verifier.py"), "dispatch", "--plan", w("plan.json", plan),
               "--approval", w("approval.json", approval), "--flags", w("flags.json", flags),
               "--config", w("cfg.json", cfg or self.cfg)] + (["--strict"] if strict else [])
        proc = subprocess.run(cmd, capture_output=True, text=True, env=self.env, cwd=str(SKILL))
        return proc.returncode, json.loads(proc.stdout)

    def n_calls(self):
        return len(self.calls.read_text().splitlines()) if self.calls.exists() else 0

    def approval(self, plan):
        return dae.build_approval_response(plan, approver="alice@example.com", signing_key=self.key)

    def test_valid_dispatches_once_with_the_complete_checked_argv(self):
        _r, plan = _approved_plan()
        rc, out = self.run_tool(plan, self.approval(plan))
        self.assertEqual((rc, out["dispatched"]), (0, True), out)
        lines = self.calls.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        argv = json.loads(lines[0])
        self.assertEqual(argv[0], "deploy")
        # the complete expected execution-input set: every live flag, as checked, nothing else
        expected = []
        for k in sorted(BASE_FLAGS, key=lambda x: x.lstrip("-")):
            expected += [k, str(BASE_FLAGS[k])]
        self.assertEqual(argv[1:], expected)
        self.assertEqual(out["dispatched_values"], {k: plan.get(k) for k in out["dispatched_values"]})

    def test_tampered_approval_zero_calls(self):
        _r, plan = _approved_plan()
        bad = self.approval(plan)
        bad["plan_sha256"] = "sha256:" + "0" * 64
        rc, out = self.run_tool(plan, bad)
        self.assertEqual((rc, out["dispatched"], self.n_calls()), (3, False, 0))

    def test_execution_input_drift_zero_calls(self):
        _r, plan = _approved_plan()
        rc, out = self.run_tool(plan, self.approval(plan), flags=dict(BASE_FLAGS, **{"--service-account": SA_B}))
        self.assertEqual((rc, self.n_calls()), (3, 0))
        self.assertFalse(out["detail"]["bind"]["bound"])

    def test_replayed_approval_refused_second_time(self):
        _r, plan = _approved_plan()
        ap = self.approval(plan)
        self.assertEqual(self.run_tool(plan, ap)[0], 0)
        rc, out = self.run_tool(plan, ap)
        self.assertEqual((rc, self.n_calls()), (3, 1))
        self.assertIn("replay", out["refused"])

    def test_correctly_signed_approval_for_another_operation_refused(self):
        _r, plan = _approved_plan()
        other = _resign(dict(self.approval(plan), operation="agents-cli.delete"), self.key)
        self.assertTrue(dae.verify_approval(plan, other)["checks"]["signature_valid"])   # the signature is fine
        rc, out = self.run_tool(plan, other)
        self.assertEqual((rc, self.n_calls()), (3, 0))
        self.assertFalse(out["detail"]["verify"]["checks"]["operation_matches"])

    def test_correctly_signed_approval_for_another_skill_refused(self):
        _r, plan = _approved_plan()
        other = _resign(dict(self.approval(plan), skill_id="some_other_skill"), self.key)
        rc, out = self.run_tool(plan, other)
        self.assertEqual((rc, self.n_calls()), (3, 0))
        self.assertFalse(out["detail"]["verify"]["checks"]["skill_id_matches"])

    def test_untrusted_signer_refused_when_keys_configured(self):
        _r, plan = _approved_plan()
        cfg = dict(self.cfg, trusted_public_keys=["11" * 32])
        rc, out = self.run_tool(plan, self.approval(plan), cfg=cfg)
        self.assertEqual((rc, self.n_calls()), (3, 0))
        self.assertFalse(out["detail"]["verify"]["checks"]["signer_authorized"])
        own = self.approval(plan)["public_key"]
        rc, out = self.run_tool(plan, self.approval(plan), cfg=dict(self.cfg, trusted_public_keys=[own]))
        self.assertEqual((rc, self.n_calls(), out["verify"]["signer_authority"]), (0, 1, "trusted_key_list"))

    def test_without_key_list_signer_authority_is_reported_not_established(self):
        _r, plan = _approved_plan()
        rc, out = self.run_tool(plan, self.approval(plan))
        self.assertEqual((rc, out["verify"]["signer_authority"], out["verify"]["replay"]),
                         (0, "not_established", "enforced_at_dispatch"))

    def test_from_source_cannot_be_approved_or_dispatched(self):
        # A from-source plan has no source_revision, and the approval builder refuses an incomplete
        # plan, so no valid approval for it exists: strict mode's from-source refusal is unreachable
        # through a valid approval. What CAN happen at dispatch is live flags dropping --image under an
        # image-approved plan; that must be refused with zero calls, strict or not.
        flags = {k: v for k, v in BASE_FLAGS.items() if k != "--image"}
        _r, src_plan = _approved_plan(flags)
        with self.assertRaises(ValueError):
            self.approval(src_plan)
        _r, plan = _approved_plan()
        for strict in (False, True):
            rc, out = self.run_tool(plan, self.approval(plan), flags=flags, strict=strict)
            self.assertEqual((rc, self.n_calls()), (3, 0))
            self.assertIn("source_revision", [d["field"] for d in out["detail"]["bind"]["divergences"]])

    def test_strict_mutable_tag_refused_at_dispatch(self):
        _r, plan = _approved_plan()                      # BASE_FLAGS image is a :abc tag
        rc, out = self.run_tool(plan, self.approval(plan), strict=True)
        self.assertEqual((rc, self.n_calls()), (3, 0))
        self.assertIn("immutable", out["refused"])
        self.assertIn("not pinned by digest", out["detail"]["artifact"]["reason"])

    def test_strict_digest_pinned_dispatches(self):
        flags = dict(BASE_FLAGS, **{"--image": DIGEST_IMAGE})
        _r, plan = _approved_plan(flags)
        rc, out = self.run_tool(plan, self.approval(plan), flags=flags, strict=True)
        self.assertEqual((rc, self.n_calls()), (0, 1))
        self.assertIn(DIGEST_IMAGE, json.loads(self.calls.read_text().splitlines()[0]))

    def test_failed_check_does_not_burn_the_nonce(self):
        _r, plan = _approved_plan()
        ap = self.approval(plan)
        self.assertEqual(self.run_tool(plan, ap, flags=dict(BASE_FLAGS, **{"--service-account": SA_B}))[0], 3)
        self.assertEqual(self.run_tool(plan, ap)[0], 0)          # same approval still usable once
        self.assertEqual(self.n_calls(), 1)


if __name__ == "__main__":
    unittest.main()
