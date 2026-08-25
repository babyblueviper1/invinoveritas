#!/usr/bin/env python3
"""Mutation-survival gate for the ERC-8309 vantage-authority companion (spec v0.3.3 §10).

§10: "every normative MUST in this document maps to at least one mutant a conformant suite MUST
KILL." This runs that gate for real rather than declaring it: each mutant is applied to a copy of
services/vantage_resolution.py, the conformance suite is run against the mutated module, and the
mutant is KILLED only if at least one test actually goes red.

A mutant that SURVIVES is a normative MUST with no enforcing vector -- a real gap in the suite,
reported as such, never rounded down to a pass.

Emits conformance/erc-8309-vantage/spec-mutations.json in the same shape as the base's
conformance/erc-8309/spec-mutations.json (ccip-router#3, 5/5 KILLED).

Usage:  venv/bin/python scripts/vantage_spec_mutations.py [--json-only]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "services"))
import mutation_classify as mc  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "services", "vantage_resolution.py")
OUT_DIR = os.path.join(ROOT, "conformance", "erc-8309-vantage")
OUT = os.path.join(OUT_DIR, "spec-mutations.json")

# (id, spec clause, what the MUST says, regex to find, replacement) -- each mutation removes or
# inverts exactly one guard.
MUTANTS = [
    ("M1-signer-counting", "§7.1",
     "quorum counts distinct signers per vantage class, never raw attestations",
     r"signers_per_value\.setdefault\(a\.value, set\(\)\)\.add\(a\.signer\)",
     "signers_per_value.setdefault(a.value, list()).append(a.signature)"),

    ("M2-window-signed-timestamp", "§5 E5",
     "evaluation windows MUST NOT be defined over signed timestamps",
     r'if self\.e5_synchrony\.get\("window_basis"\) == "signed_timestamp":',
     'if False:'),

    ("M3-global-independence", "§5 E3 / §8",
     "independence is claimed per vantage class, never globally",
     r'if self\.e3_independence\.get\("global"\) is True:',
     'if False:'),

    ("M4-ineligible-in-commitment", "§4.2 / V2",
     "eligibility is recomputed at commitment time; ineligible rows never enter the committed set",
     r"if a\.structurally_eligible\(\)\n        and \(cryptographically_eligible is None",
     "if True\n        and (cryptographically_eligible is None"),

    # NOTE: an earlier M5 removed the explicit `or s == "0x"` clause. That is an EQUIVALENT
    # mutant -- the length check below already rejects "0x" (len 2 != 132), so behaviour is
    # unchanged and no test could ever kill it. Equivalent mutants are not suite gaps, and
    # reporting one as a gap would be a false alarm of exactly the kind §6's false-red
    # prohibition warns about. Mutating the load-bearing guard instead.
    ("M5-unsigned-eligible", "§4.2 / §11",
     'a "0x" signature is structurally ineligible -- presence is not verification',
     r"return len\(s\) == 132  # 0x \+ 130 hex chars == 65 bytes",
     "return True  # mutant: structural eligibility check removed"),

    # M6 REPLACED (not relabeled), 2026-08-24, Pavlo's ruling, endorsed by Merlini and taken here.
    # The old M6 removed encodeJsonUtf8Lf's trailing LF and was labelled "canonical form is
    # sorted-key UTF-8 JSON with a single trailing LF". After the v0.3 per-schema split the
    # companion asserts NOTHING about the LF form beyond its binding assignments (v0.3.3 §5,
    # verbatim), so that mutation tested a MUST the document no longer makes. Relabelling it would
    # have left a mutant testing a removed claim -- "coverage of nothing wearing a green digit"
    # (Merlini). The exactly-one-LF mutant belongs to the future LF byte-contract gate, once that
    # contract is specified and bound; it does not belong to this companion gate now.
    #
    # The replacement mutates the claim the companion DOES make: a JCS-bound schema's canonical
    # bytes are RFC 8785 with NO trailing byte. Appending 0x0a to the JCS encoder's output is the
    # exact one-byte break that "a spec that says JCS but adds one byte" would cause -- silent,
    # and only surfacing when two implementations first try to agree.
    ("M6-jcs-trailing-byte-appended", "§5",
     "a JCS-bound schema's canonical bytes are RFC 8785 with NO trailing byte",
     r"    return rfc8785\.dumps\(obj\)",
     '    return rfc8785.dumps(obj) + b"\\\\n"  # mutant: JCS must emit no trailing byte'),

    ("M7-insufficient-without-inspected-set", "§9",
     '"not found" without an inspected-set commitment is nonconformant',
     r"inspected_set_digest=inspected_set_digest\(attestations\),\n            inspected_count=len\(attestations\)\)\n    values",
     'inspected_set_digest="sha256:" + "0" * 64,\n            inspected_count=0)\n    values'),

    ("M8-v2-order-dependent", "§5 V2",
     "V2 is a digest over the SORTED signatures -- a set commitment, never ingest-order dependent",
     r"sigs = sorted\(\n        a\.signature for a in attestations",
     "sigs = list(\n        a.signature for a in attestations"),

    ("M9-equivocation-silent", "§3",
     "the detector MUST warn on same-signer equivocation",
     r"if any\(len\(v\) > 1 for v in by_signer\.values\(\)\):",
     "if False:"),

    ("M10-quorum-emits-agreement", "§6 / V5",
     "no false green: a failed/auto resolution MUST NOT surface as agreement",
     r"return profile_a_surface\(attestations\)\n    return Resolved\(",
     "return Agreement(committed_set_digest=dg)\n    return Resolved("),

    ("M11-source-peer-in-identity", "§4.2",
     "transport metadata (source_peer) cannot redefine record identity",
     r'digest\(\{"v2_committed_signatures": sigs\}\)',
     'digest({"v2_committed_signatures": sigs, "peers": sorted(str(a.source_peer) for a in attestations)})'),

    ("M12-finality-implied", "§5 E4 / §6a",
     "no evaluation carries finality unless the profile declares a finality rule",
     r'return bool\(self\.e4_fault_model\.get\("finality_rule"\)\)',
     'return True'),

    ("M13-supersession-mutates", "§6a",
     "supersession neither rewrites nor invalidates the superseded claim",
     r"supersedes=self\.evaluation_id\(\),",
     "supersedes=newer.evaluation_id(),"),

    ("M14-resolving-without-ref", "§6 Q2",
     "resolved(...) carries the full set by reference; retrievability demonstrated not declared",
     r"if not committed_set_ref:",
     "if False:"),

    # --- v0.3 §5 additions (2026-08-24) --------------------------------------
    # Added after Pavlo asked whether this gate actually covers v0.3's NEW normative MUSTs or was
    # only re-running the v0.2.2 set. It was only re-running: both MUSTs below had TESTS but no
    # MUTANT, so a clean "14/14" would have read as coverage it did not have. That is precisely
    # the failure §10's gate exists to prevent, sitting inside the gate itself -- and it is the
    # third time this round that an artifact held up as the reference for a rule was quietly
    # breaking it one level down.
    ("M15-unbound-schema-defaults", "§5 (v0.3)",
     "an unbound schema MUST raise -- no default serializer, inference forbidden",
     r'    try:\n        return _ENCODERS\[SERIALIZER_BINDINGS\[schema\]\]\(obj\)\n    except KeyError:',
     '    try:\n        return _ENCODERS[SERIALIZER_BINDINGS[schema]](obj)\n    except KeyError:\n        return _ENCODERS["rfc8785-jcs"](obj)  # mutant: silent default\n    except RuntimeError:'),

    ("M16-bindings-collapse", "§5 (v0.3)",
     "the companion binds TWO schemas to DIFFERENT serializers; collapsing them re-creates the "
     "exact ambiguity the per-schema rule was ratified to remove",
     r'"ccip\.attestation\.unsigned\.v1": "encode-json-utf8-lf",',
     '"ccip.attestation.unsigned.v1": "rfc8785-jcs",'),
]



# --- expected_kill_tests (Pavlo, 2026-08-25) --------------------------------------------------
# A call-phase failure ANYWHERE in the suite can certify a MUST by accident. KILLED now requires
# the red to land in the mutant's own mapped enforcing test.
#
# These values are MEASURED, not asserted: every mutant was run and the failing nodeid recorded
# (2026-08-25T01:40Z). That matters twice over -- it means the initial mapping reflects what the
# suite actually does rather than what I believe it does, AND any future drift between those two
# is exactly what this field now catches.
#
# What the measurement found: 14 of 16 kill exactly one test, and it is the mapped one. The
# exceptions are why the field is needed:
#   M6  reds FOUR tests -- honest collateral, since the mutation makes JCS emit a trailing byte
#       and everything JCS-dependent breaks with it. Only the mapped one is listed; the rest are
#       recorded as collateral rather than discarded.
#   M11 reds its own enforcer AND test_ineligible_rows_never_enter_the_v2_commitment, which is
#       M4's. It is ONE DELETED TEST from being certified entirely by a test written for a
#       different MUST. Nothing is mis-certified today -- the gate simply could not have noticed.
#   M15/M16 each also pick up test_companion_binds_two_schemas_not_one.
EXPECTED_KILL_TESTS = {
    'M1-signer-counting': ['test_quorum_counts_distinct_signers_not_attestations'],
    'M2-window-signed-timestamp': ['test_window_over_signed_timestamps_is_rejected'],
    'M3-global-independence': ['test_global_independence_claim_is_rejected'],
    'M4-ineligible-in-commitment': ['test_ineligible_rows_never_enter_the_v2_commitment'],
    'M5-unsigned-eligible': ['test_malformed_length_signature_is_ineligible'],
    'M6-jcs-trailing-byte-appended': ['test_the_two_serializers_differ_by_exactly_the_trailing_byte'],
    'M7-insufficient-without-inspected-set': ['test_insufficient_observation_carries_inspected_set_commitment'],
    'M8-v2-order-dependent': ['test_v2_is_order_independent'],
    'M9-equivocation-silent': ['test_same_signer_equivocation_is_byzantine_evidence'],
    'M10-quorum-emits-agreement': ['test_quorum_failure_falls_back_to_profile_a_never_to_agreement'],
    'M11-source-peer-in-identity': ['test_source_peer_is_excluded_from_identity_by_enumeration'],
    'M12-finality-implied': ['test_no_finality_unless_declared'],
    'M13-supersession-mutates': ['test_supersession_does_not_mutate_the_prior_claim'],
    'M14-resolving-without-ref': ['test_resolving_profile_without_a_retrievable_ref_is_rejected'],
    'M15-unbound-schema-defaults': ['test_serializer_is_never_inferred_for_an_unbound_schema'],
    'M16-bindings-collapse': ['test_companion_binds_two_schemas_not_one'],
}


def compile_ok(path: str) -> bool:
    """A mutation that does not PARSE kills every mutant trivially -- the M6 defect. Checked first
    so such a run is classified VACUOUS rather than scored as a kill."""
    try:
        compile(open(path).read(), path, "exec")
        return True
    except SyntaxError:
        return False


def run_suite(workdir: str) -> tuple[bool, str]:
    """Return (all_green, tail). Runs the conformance suite against the mutated tree.

    Also drops the phase-recording conftest in and points it at a report path, so classification
    keys off WHERE the red happened rather than pytest's summary-line wording.
    """
    shutil.copy(os.path.join(OUT_DIR, "mutation_conftest.py"),
                os.path.join(workdir, "tests", "conftest.py"))
    # NO -x. It was here to fail fast, and it is INCOMPATIBLE with expected_kill_tests: -x stops
    # at the FIRST failure, so if an unrelated test fails earlier in file order the mutant's own
    # mapped enforcing test never executes and the mutant is scored SURVIVED for a reason that has
    # nothing to do with the suite's coverage. Found immediately on wiring the classifier -- M11
    # flipped to SURVIVED because M4's enforcer fails first and aborted the run before M11's own
    # test could run. That is the same shape as the collection-error case: a test that never ran
    # leaves no evidence to classify, and -x manufactures exactly that condition.
    env = dict(os.environ)
    env["PYTHONPATH"] = workdir
    env["MUTATION_REPORT_PATH"] = os.path.join(workdir, "mutation_report.json")
    # sys.executable, not a hardcoded venv path: the gate has to run wherever a
    # reader checks it, not only inside this repo's tree.
    p = subprocess.run(
        [sys.executable, "-m", "pytest",
         os.path.join(workdir, "tests", "test_vantage_resolution.py"), "-q", "--no-header"],
        cwd=workdir, capture_output=True, text=True, env=env, timeout=300)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode == 0, out.strip().splitlines()[-1] if out.strip() else ""


def _red_is_a_real_failure(tail: str) -> bool:
    """A mutant counts as KILLED only if a test ASSERTED its way to red.

    Found 2026-08-24 by Pavlo, who noticed M6 was recorded as "1 error" rather than "1 failed" and
    asked whether the red was actually caused by the violation. It was not. M6's replacement string
    contained a backslash-n, and re.sub PROCESSES ESCAPES IN THE REPLACEMENT -- so it emitted a real
    newline into the middle of a bytes literal, producing an unterminated string and a SyntaxError.
    pytest reported a collection error, the gate saw not-green, and counted it KILLED. The mutant
    never tested the JCS trailing-byte claim; it broke the file.

    That is the vacuous-digest defect of §9 one level up, inside the gate whose whole job is to
    prove tests are load-bearing: ANY mutation that fails to parse kills every mutant trivially, so
    a gate that accepts an error as a kill can report 100% while testing nothing. The fix is
    structural rather than M6-specific -- every mutant now has to earn its red the same way.
    """
    return "failed" in tail


def main() -> int:
    json_only = "--json-only" in sys.argv
    original = open(SRC).read()
    results = []

    # baseline must be green, or nothing below means anything
    with tempfile.TemporaryDirectory() as td:
        shutil.copytree(os.path.join(ROOT, "services"), os.path.join(td, "services"))
        os.makedirs(os.path.join(td, "tests"), exist_ok=True)
        shutil.copy(os.path.join(ROOT, "tests", "test_vantage_resolution.py"),
                    os.path.join(td, "tests", "test_vantage_resolution.py"))
        green, tail = run_suite(td)
        if not green:
            print(f"BASELINE IS RED -- fix before running the gate: {tail}", file=sys.stderr)
            return 2
        if not json_only:
            print(f"baseline: GREEN ({tail})\n")

    for mid, clause, must, pattern, repl in MUTANTS:
        mutated, n = re.subn(pattern, repl, original, count=1)
        if n != 1:
            results.append({"id": mid, "clause": clause, "must": must,
                            "status": "NOT_APPLIED",
                            "note": "mutation pattern did not match source -- the guard moved or "
                                    "was renamed; this mutant is not testing anything"})
            if not json_only:
                print(f"  {mid:38} NOT APPLIED (pattern missed)")
            continue
        with tempfile.TemporaryDirectory() as td:
            shutil.copytree(os.path.join(ROOT, "services"), os.path.join(td, "services"))
            os.makedirs(os.path.join(td, "tests"), exist_ok=True)
            shutil.copy(os.path.join(ROOT, "tests", "test_vantage_resolution.py"),
                        os.path.join(td, "tests", "test_vantage_resolution.py"))
            src_path = os.path.join(td, "services", "vantage_resolution.py")
            with open(src_path, "w") as f:
                f.write(mutated)
            compiled = compile_ok(src_path)
            green, tail = run_suite(td)
            phase_report = None
            rp = os.path.join(td, "mutation_report.json")
            if os.path.exists(rp):
                try:
                    phase_report = json.load(open(rp))
                except Exception:
                    phase_report = None
        status, reason, evidence = mc.classify(
            phase_report, EXPECTED_KILL_TESTS.get(mid), compile_ok=compiled)
        results.append({"id": mid, "clause": clause, "must": must,
                        "status": status, "reason": reason,
                        "expected_kill_tests": EXPECTED_KILL_TESTS.get(mid, []),
                        "evidence": evidence, "suite_result": tail})
        if not json_only:
            mark = {"KILLED": "KILLED",
                    "VACUOUS": "VACUOUS   <-- NOT A KILL",
                    "SURVIVED": "SURVIVED  <-- GAP"}.get(status, status)
            extra = ""
            if status == "KILLED" and evidence.get("collateral_failures"):
                extra = f"  (+{len(evidence['collateral_failures'])} collateral)"
            print(f"  {mid:38} {mark:26} {tail[:34]}{extra}")

    counts = mc.tally(results, len(MUTANTS))     # raises if a mutant is in an unnamed state
    killed = counts["KILLED"]
    applied = sum(1 for r in results if r["status"] != "NOT_APPLIED")
    payload = {
        "schema": "erc-8309-vantage-authority-companion/spec-mutations",
        "spec_version": "0.3.3",
        "implementation_under_test": "services/vantage_resolution.py",
        "conformance_suite": "tests/test_vantage_resolution.py",
        "declared_expectation": "conformant",
        # Serialized from the four independent counts, never hand-built here -- see
        # mutation_classify.summarize() for what this used to be and why it was wrong on BOTH gates.
        "summary": mc.summarize(counts),
        "mutants": results,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    if not json_only:
        print(f"\n  {killed}/{applied} KILLED -> {os.path.relpath(OUT, ROOT)}")
        # Branch survived vs vacuous: they mean OPPOSITE things. A survivor is a real coverage gap
        # (a normative MUST nothing enforces); a vacuous mutant proved nothing at all and the gate
        # learned nothing from it. Printing the survivor message for a vacuous mutant would report
        # a gap that does not exist while hiding one that does.
        if counts[mc.SURVIVED]:
            print("  SURVIVING mutants are normative MUSTs with no enforcing vector -- real gaps.")
        if counts[mc.VACUOUS]:
            print(f"  {counts[mc.VACUOUS]} VACUOUS mutant(s): the claim was never evaluated "
                  f"(broken file / collection / setup). NOT a kill and NOT a gap -- fix the mutant.")
    return 0 if killed == applied and applied == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
