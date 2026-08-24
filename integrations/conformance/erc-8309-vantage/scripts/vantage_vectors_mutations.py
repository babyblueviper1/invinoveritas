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


def run_suite(workdir: str) -> tuple:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(workdir, "services")
    # sys.executable, not a hardcoded venv path: the gate has to run wherever a
    # reader checks it, not only inside this repo's tree.
    p = subprocess.run(
        [sys.executable, "-m", "pytest",
         os.path.join(workdir, "tests", "test_vantage_vectors_consumer.py"),
         "-q", "--no-header", "-x"],
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
            green, tail = run_suite(td)
        killed = not green
        results.append({"id": mid, "clause": clause, "must": must,
                        "status": "KILLED" if killed else "SURVIVED", "suite_result": tail})
        if not json_only:
            print(f"  {mid:40} {'KILLED' if killed else 'SURVIVED  <-- GAP'}  {tail[:46]}")

    sys.path.insert(0, os.path.join(ROOT, "services"))
    from vantage_vectors_consumer import golden_set_inventory  # noqa: E402

    killed = sum(1 for r in results if r["status"] == "KILLED")
    applied = sum(1 for r in results if r["status"] != "NOT_APPLIED")
    payload = {
        "schema": "erc-8309-vantage-authority-companion/vectors-consumer-mutations",
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
        "summary": {"applied": applied, "killed": killed, "survived": applied - killed,
                    "not_applied": len(results) - applied},
        "golden_set_inventory": golden_set_inventory([]),
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
        if applied - killed:
            print("  SURVIVING mutants are normative MUSTs with no enforcing vector -- real gaps.")
    return 0 if killed == applied == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
