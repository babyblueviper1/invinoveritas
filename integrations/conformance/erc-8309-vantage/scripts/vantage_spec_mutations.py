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


def run_suite(workdir: str) -> tuple[bool, str]:
    """Return (all_green, tail). Runs the conformance suite against the mutated tree."""
    env = dict(os.environ)
    env["PYTHONPATH"] = workdir
    # sys.executable, not a hardcoded venv path: the gate has to run wherever a
    # reader checks it, not only inside this repo's tree.
    p = subprocess.run(
        [sys.executable, "-m", "pytest",
         os.path.join(workdir, "tests", "test_vantage_resolution.py"), "-q", "--no-header", "-x"],
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
            with open(os.path.join(td, "services", "vantage_resolution.py"), "w") as f:
                f.write(mutated)
            green, tail = run_suite(td)
        vacuous = (not green) and not _red_is_a_real_failure(tail)
        killed = (not green) and not vacuous
        status = "VACUOUS" if vacuous else ("KILLED" if killed else "SURVIVED")
        results.append({"id": mid, "clause": clause, "must": must,
                        "status": status,
                        "suite_result": tail,
                        **({"note": "suite went red on an ERROR, not an assertion -- this mutation "
                                    "broke the module rather than violating the claim, so it proves "
                                    "nothing. NOT counted as a kill."} if vacuous else {})})
        if not json_only:
            print(f"  {mid:38} {'KILLED' if killed else 'SURVIVED  <-- GAP'}  {tail[:52]}")

    killed = sum(1 for r in results if r["status"] == "KILLED")
    applied = sum(1 for r in results if r["status"] != "NOT_APPLIED")
    payload = {
        "schema": "erc-8309-vantage-authority-companion/spec-mutations",
        "spec_version": "0.3.3",
        "implementation_under_test": "services/vantage_resolution.py",
        "conformance_suite": "tests/test_vantage_resolution.py",
        "declared_expectation": "conformant",
        "summary": {"applied": applied, "killed": killed,
                    "survived": applied - killed,
                    "not_applied": len(results) - applied},
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
    return 0 if killed == applied and applied == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
