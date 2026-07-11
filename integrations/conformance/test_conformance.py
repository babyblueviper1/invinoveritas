"""pytest wrapper — every fixture verifies to its declared expectation, one broken join per negative."""
import json
from pathlib import Path

import pytest

from verifier import verify_fixture

FIX = Path(__file__).resolve().parent / "fixtures"
FIXTURES = sorted(p for p in FIX.glob("*.json")
                  if p.name not in ("trust_policy.json", "live_confirmed_anchor.json"))


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
