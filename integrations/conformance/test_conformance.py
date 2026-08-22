"""pytest wrapper — every fixture verifies to its declared expectation, one broken join per negative."""
import copy
import json
from pathlib import Path

import pytest

from verifier import verify_fixture

FIX = Path(__file__).resolve().parent / "fixtures"
FIXTURES = sorted(p for p in FIX.glob("*.json")
                  if p.name not in ("trust_policy.json", "live_confirmed_anchor.json"))

INVARIANTS = ("canonical_envelope", "chain_invariant", "admission_invariant",
              "anchoring_existence", "anchoring_precedence")


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_meets_declared_expectation(path):
    fx = json.loads(path.read_text())
    r = verify_fixture(fx)
    if fx["expected_overall"] == "pass":
        assert r["overall_pass"], f"{path.name} should pass: {r['suites']}"
    else:
        assert not r["overall_pass"], f"{path.name} should fail"
        assert r["failure_reason"] == fx["expected_failure_reason"], \
            f"{path.name}: got {r['failure_reason']}, expected {fx['expected_failure_reason']}"
        broken = [n for n, s in r["suites"].items() if s["pass"] is False]
        assert len(broken) == 1, f"{path.name}: expected exactly one broken join, got {broken}"


def test_positive_admission_is_real_published_key():
    """The positive fixture's admission must be signed by the published verifier key (not a mock)."""
    from _bip340_nostr import PUBLISHED_PUBKEY
    fx = json.loads((FIX / "positive.json").read_text())
    assert fx["admission"]["verdict_event"]["pubkey"] == PUBLISHED_PUBKEY


@pytest.mark.parametrize("invariant", INVARIANTS)
def test_every_declared_invariant_is_load_bearing(invariant):
    """2026-08-22 (Rul1an, crewAIInc/crewAI#4877): a fixture set can look complete while some
    declared invariant is never actually exercised -- a vector "passes" not because the rule it
    names held, but because nothing in the set could have made it fail. The falsifiability test:
    delete the rule (force its suite to always pass) and rerun every fixture; if no fixture's
    verdict moves, the suite never asked whether that rule mattered. Applying this to our own
    conformance suite found exactly that gap for canonical_envelope and chain_invariant (0/6
    negative fixtures broke either one) -- closed by adding
    negative_canonical_envelope_mismatch.json and negative_chain_action_ref_split.json. This test
    locks the finding so it can't silently regress: every invariant in INVARIANTS must have at
    least one fixture whose overall_pass or failure_reason changes when that invariant alone is
    deleted."""
    moved = False
    for path in FIXTURES:
        fx = json.loads(path.read_text())
        real = verify_fixture(fx)
        suites = copy.deepcopy(real["suites"])
        if invariant in suites and suites[invariant]["pass"] is not None:
            suites[invariant] = {"pass": True, "code": None, "detail": "(rule deleted for this test)"}
        deleted_overall = all(s["pass"] is True for s in suites.values())
        deleted_reason = next((s["code"] for s in suites.values() if s["pass"] is False), None)
        if (real["overall_pass"], real["failure_reason"]) != (deleted_overall, deleted_reason):
            moved = True
            break
    assert moved, (f"deleting {invariant} changed NO fixture's verdict -- this invariant is "
                   f"vacuous, no vector in the suite depends on it")
