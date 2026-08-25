#!/usr/bin/env python3
"""Mutation gate for the ERC-8309 vectors consumer -- the SECOND enforcement surface.

The companion's §10 requires every executable normative MUST to map to at least one mutant a
conformant suite MUST KILL. Until now this account had exactly one surface under that gate
(services/vantage_resolution.py, 16/16) and reported the number as if it were the whole picture.
It was not: three MUSTs constrain the VECTORS ARTIFACT and its consumer, which that gate never
touches. Those three are:

    bytes_hex REQUIRED as the normative carrier
    the adversarial PAIR must be present
    the wrong-serializer digest MUST be rejected

(A fourth from Merlini's map -- an unbound schema MUST raise -- is already banked as M15 on the
resolution surface, so three are outstanding here, not four. Pavlo corrected that count and he
was right.)

REPORTED BY SURFACE, NEVER AS ONE TOTAL. A single number across two implementations-under-test is
how "16/16" came to read as coverage it did not have. The emitted artifact keeps the surfaces
separate and carries the per-binding golden-set inventory in its three distinct states, so
"needs a conforming set" and "no denominator yet" cannot collapse into one blank.

Usage:  venv/bin/python scripts/vantage_vectors_mutations.py [--json-only]
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
SRC = os.path.join(ROOT, "services", "vantage_vectors_consumer.py")
SUITE = os.path.join(ROOT, "tests", "test_vantage_vectors_consumer.py")
OUT_DIR = os.path.join(ROOT, "conformance", "erc-8309-vantage")
OUT = os.path.join(OUT_DIR, "vectors-consumer-mutations.json")

MUTANTS = [
    ("V1-bytes-hex-optional", "§5 / v0.1 carrier",
     "bytes_hex is REQUIRED as the normative hashable carrier",
     r'    if "bytes_hex" not in vector:\n        raise VectorRejected\(',
     '    if False:\n        raise VectorRejected('),

    ("V2-adversarial-pair-optional", "§10 / v0.1 pair",
     "a binding's vector set MUST carry the adversarial pair",
     r"    if not isinstance\(vectors, list\) or len\(vectors\) < 2:",
     "    if False:"),

    ("V3-wrong-serializer-digest-accepted", "§5 / §9",
     "a digest produced under the unbound serializer MUST be rejected",
     r'    if str\(failure\)\.lower\(\)\.removeprefix\("sha256:"\) == conforming:',
     "    if False:"),

    # Not one of the three, but the collapse Pavlo specifically warned about: if the inventory
    # stops distinguishing "no set at all" from "a set that fails", the report goes back to being
    # a single blank and the whole by-surface exercise is undone.
    ("V4-inventory-state-collapse", "§10 inventory",
     "'needs a conforming set' and 'no denominator yet' MUST stay distinct states",
     r'            inventory\[schema\] = "needs a conforming set"',
     '            inventory[schema] = "no denominator yet"'),
]



# Measured 2026-08-25, same discipline as the surface-1 map: every mutant run, failing nodeid
# recorded. All four are clean 1:1 here -- no collateral, no borrowed enforcers.
EXPECTED_KILL_TESTS = {
    'V1-bytes-hex-optional': ['test_missing_bytes_hex_is_rejected'],
    'V2-adversarial-pair-optional': ['test_non_list_vectors_field_is_rejected_as_a_missing_pair'],
    'V3-wrong-serializer-digest-accepted': ['test_failure_digest_equal_to_the_conforming_one_is_rejected'],
    'V4-inventory-state-collapse': ['test_a_failing_set_reads_as_needs_one_not_as_absent'],
}


def run_suite(workdir: str) -> tuple:
    # NO -x. It was here to fail fast, and it is INCOMPATIBLE with expected_kill_tests: -x stops
    # at the FIRST failure, so if an unrelated test fails earlier in file order the mutant's own
    # mapped enforcing test never executes and the mutant is scored SURVIVED for a reason that has
    # nothing to do with the suite's coverage. Found immediately on wiring the classifier -- M11
    # flipped to SURVIVED because M4's enforcer fails first and aborted the run before M11's own
    # test could run. That is the same shape as the collection-error case: a test that never ran
    # leaves no evidence to classify, and -x manufactures exactly that condition.
    shutil.copy(os.path.join(OUT_DIR, "mutation_conftest.py"),
                os.path.join(workdir, "tests", "conftest.py"))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(workdir, "services")
    env["MUTATION_REPORT_PATH"] = os.path.join(workdir, "mutation_report.json")
    # sys.executable, not a hardcoded venv path: the gate has to run wherever a
    # reader checks it, not only inside this repo's tree.
    p = subprocess.run(
        [sys.executable, "-m", "pytest",
         os.path.join(workdir, "tests", "test_vantage_vectors_consumer.py"),
         "-q", "--no-header"],
        cwd=workdir, capture_output=True, text=True, env=env, timeout=300)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode == 0, (out.strip().splitlines()[-1] if out.strip() else "")


def _stage(td: str, mutated: str = None) -> None:
    shutil.copytree(os.path.join(ROOT, "services"), os.path.join(td, "services"))
    os.makedirs(os.path.join(td, "tests"), exist_ok=True)
    shutil.copy(SUITE, os.path.join(td, "tests", "test_vantage_vectors_consumer.py"))
    if mutated is not None:
        with open(os.path.join(td, "services", "vantage_vectors_consumer.py"), "w") as f:
            f.write(mutated)


def compile_ok(path: str) -> bool:
    """A mutation that does not PARSE kills every mutant trivially -- the M6 defect on the sibling
    surface. Checked so such a run classifies VACUOUS rather than scoring a kill."""
    try:
        compile(open(path).read(), path, "exec")
        return True
    except SyntaxError:
        return False


def main() -> int:
    json_only = "--json-only" in sys.argv
    original = open(SRC).read()
    results = []

    with tempfile.TemporaryDirectory() as td:
        _stage(td)
        green, tail = run_suite(td)
        if not green:
            print(f"BASELINE IS RED -- fix before running the gate: {tail}", file=sys.stderr)
            return 2
        if not json_only:
            print(f"baseline: GREEN ({tail})\n")

    for mid, clause, must, pattern, repl in MUTANTS:
        mutated, n = re.subn(pattern, repl, original, count=1)
        if n != 1:
            results.append({"id": mid, "clause": clause, "must": must, "status": "NOT_APPLIED",
                            "note": "pattern did not match -- the guard moved or was renamed; "
                                    "this mutant is not testing anything"})
            if not json_only:
                print(f"  {mid:40} NOT APPLIED (pattern missed)")
            continue
        with tempfile.TemporaryDirectory() as td:
            _stage(td, mutated)
            compiled = compile_ok(os.path.join(td, "services", "vantage_vectors_consumer.py"))
            green, tail = run_suite(td)
            phase_report = None
            rp = os.path.join(td, "mutation_report.json")
            if os.path.exists(rp):
                try:
                    phase_report = json.load(open(rp))
                except Exception:
                    phase_report = None
        # A kill must be an ASSERTION FAILURE, never a collection/runtime error. Ported from the
        # surface-1 gate the same day it was found there: M6's replacement string emitted a real
        # newline into a bytes literal, produced a SyntaxError, and the gate счёл the resulting
        # collection error a kill -- so the mutant proved nothing while reporting green. ANY
        # mutation that fails to parse kills every mutant trivially, which means a gate that
        # accepts an error as a kill can report 100% while testing nothing. Applied here too rather
        # than waiting for the same defect to be found on this surface separately.
        status, reason, evidence = mc.classify(
            phase_report, EXPECTED_KILL_TESTS.get(mid), compile_ok=compiled)
        results.append({"id": mid, "clause": clause, "must": must,
                        "status": status, "reason": reason,
                        "expected_kill_tests": EXPECTED_KILL_TESTS.get(mid, []),
                        "evidence": evidence, "suite_result": tail})
        if not json_only:
            mark = {"KILLED": "KILLED", "VACUOUS": "VACUOUS  <-- NOT A KILL",
                    "SURVIVED": "SURVIVED  <-- GAP"}.get(status, status)
            extra = (f"  (+{len(evidence['collateral_failures'])} collateral)"
                     if status == "KILLED" and evidence.get("collateral_failures") else "")
            print(f"  {mid:40} {mark:26} {tail[:30]}{extra}")

    sys.path.insert(0, os.path.join(ROOT, "services"))
    from vantage_vectors_consumer import golden_set_inventory  # noqa: E402

    counts = mc.tally(results, len(MUTANTS))     # raises if a mutant is in an unnamed state
    killed = counts["KILLED"]
    applied = sum(1 for r in results if r["status"] != "NOT_APPLIED")
    payload = {
        "schema": "erc-8309-vantage-authority-companion/vectors-consumer-mutations",
        # Machine pin, added 2026-08-24 (found Pavlo): the README claimed BOTH generated artifacts
        # carried spec_version 0.3.3, and this one carried no such field at all -- a documentation
        # claim about a machine-readable property that the machine did not actually assert. The
        # sibling surface-1 artifact had the pin; this one only had it in prose about it.
        "spec_version": "0.3.3",
        "reported_by_surface": True,
        "surface": {
            "name": "vectors consumer -- vector-artifact obligations",
            "implementation_under_test": "services/vantage_vectors_consumer.py",
            "conformance_suite": "tests/test_vantage_vectors_consumer.py",
        },
        "other_surfaces": {
            "vantage_resolution.py -- executable profile/serializer semantics":
                "see conformance/erc-8309-vantage/spec-mutations.json (16/16 KILLED)",
            "provenance-class MUSTs -- required artifact + independent reproducibility":
                "0 mutants BY DESIGN; a code mutant cannot express 'this vector was derived the "
                "wrong way'. Discharged by the definition-derived leg existing and being "
                "independently reproducible, scoped to v0.1's demonstration object only.",
        },
        # Serialized from the four independent counts, never hand-built here -- see
        # mutation_classify.summarize() for what this used to be and why it was wrong on BOTH gates.
        "summary": mc.summarize(counts),
        # Reported in Pavlo's exact two-part form. The wrong-serializer obligation has TWO halves
        # and only one is discharged; collapsing them into "done" is the same digit-collapse that
        # made 16/16 read as coverage it did not have, one level down.
        "wrong_serializer_obligation": {
            "status": "PARTIALLY DISCHARGED",
            "distinguishability": {
                "status": "discharged",
                "how": "mutation-tested and earned by recompute-and-compare -- the conforming "
                       "bytes are recomputed under the BOUND serializer from the demonstration "
                       "object, so a set whose failure_digest equals that recomputation is "
                       "rejected for a reason rather than by declaration (mutant V3).",
            },
            "alternate_serializer_equality": {
                "status": "OPEN -- not yet provable",
                "why": "the consumer checks the failure_digest for INEQUALITY against the "
                       "conforming JCS digest. It does not recompute the failure side under the "
                       "LF form and require EQUALITY, because a schema bound to one serializer "
                       "gives it no second serializer to recompute with. So it cannot today "
                       "distinguish 'this failure_digest is the LF reading of the same object' "
                       "from 'this failure_digest is arbitrary bytes that merely differ'. Both "
                       "pass.",
                "blocked_on": "the full encodeJsonUtf8Lf byte contract being specified and bound "
                              "in its own normative serializer-contract artifact (v0.3.3 §5 "
                              "asserts nothing about that form beyond the binding assignments).",
                "closes_when": "that contract lands -- recompute the same object under the LF "
                               "form and require the failure_digest to equal THAT, upgrading the "
                               "check from adversarial-looking to adversarial.",
            },
            "limitation_named_by": "Fede", "reporting_form": "Pavlo",
        },
        "golden_set_inventory": golden_set_inventory([]),
        "binding_universe": ("v0.3.3 §5 exact seven schema names. The previously published table "
                            "carried SIX, collapsing erc-8309.envelope and erc-8309.verdict into "
                            "one document-id entry -- inference inside the never-infer artifact "
                            "(found Pavlo). Six = stale, seven = aligned."),
        "inventory_note": ("Empty input deliberately: no conforming vector set has been published "
                           "against these bindings yet, so every binding reports 'no denominator "
                           "yet'. That is distinct from 'needs a conforming set' (a set exists and "
                           "fails) and the two must never collapse into one blank."),
        "mutants": results,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")
    if not json_only:
        print(f"\n  {killed}/{applied} KILLED -> {os.path.relpath(OUT, ROOT)}")
        # Survived and vacuous mean opposite things -- see the note in vantage_spec_mutations.py.
        if counts[mc.SURVIVED]:
            print("  SURVIVING mutants are normative MUSTs with no enforcing vector -- real gaps.")
        if counts[mc.VACUOUS]:
            print(f"  {counts[mc.VACUOUS]} VACUOUS mutant(s): the claim was never evaluated "
                  f"(broken file / collection / setup). NOT a kill and NOT a gap -- fix the mutant.")
    return 0 if killed == applied == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
