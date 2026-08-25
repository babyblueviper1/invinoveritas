# -*- coding: utf-8 -*-
"""Conformance tests for the phase-bound mutant classifier.

Design: Merlini. expected_kill_tests + the teardown exclusion: Pavlo. Every case below is a way
the PREVIOUS classifier was wrong, so each test names the specific defect it prevents rather than
restating the implementation.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "services")))

import mutation_classify as mc  # noqa: E402


def _rep(records, collect_errors=None):
    return {"records": records, "collect_errors": collect_errors or [], "exitstatus": 1}


def _call_fail(nodeid, exc="AssertionError"):
    return {"nodeid": nodeid, "when": "call", "outcome": "failed", "exception_class": exc}


def test_call_phase_failure_in_a_mapped_test_is_a_kill():
    st, _, ev = mc.classify(_rep([_call_fail("test_mapped")]), ["test_mapped"])
    assert st == mc.KILLED
    assert ev["killed_by"] == ["test_mapped"]


def test_a_violated_behaviour_raise_is_a_kill_not_an_error():
    """The correction Merlini caught in my framing: 'an error is never a kill' throws away real
    kills. A ValueError raised during the CALL phase can BE the violated behaviour -- a never-raise
    MUST being broken -- and the phase, not the exception class, is what distinguishes it."""
    st, _, ev = mc.classify(_rep([_call_fail("test_mapped", "ValueError")]), ["test_mapped"])
    assert st == mc.KILLED
    assert ev["exception_classes"] == ["ValueError"]


def test_red_in_an_unmapped_test_does_not_certify_the_must():
    """Pavlo's precision. Measured live before adopting: M11 reds its own enforcer AND M4's, so it
    was one deleted test from being certified entirely by a test written for a different MUST."""
    st, _, ev = mc.classify(_rep([_call_fail("test_someone_elses_enforcer")]), ["test_mine"])
    assert st == mc.SURVIVED
    assert ev["unmapped_failures"] == ["test_someone_elses_enforcer"]


def test_teardown_only_red_is_not_a_kill():
    """Teardown runs AFTER the claim was evaluated, so a failure there says nothing about it."""
    st, _, _ = mc.classify(
        _rep([{"nodeid": "test_mapped", "when": "teardown", "outcome": "failed",
               "exception_class": "RuntimeError"}]), ["test_mapped"])
    assert st == mc.SURVIVED


def test_collection_error_is_vacuous_not_a_kill():
    """THE defect this whole classifier exists for. M6 was scored KILLED for a week: re.sub
    processed the escape in its replacement, emitted a real newline into a bytes literal, produced
    a SyntaxError -> collection error -> harness saw not-green -> counted a kill. The mutant never
    tested the claim; it broke the file."""
    st, why, _ = mc.classify(_rep([], collect_errors=["tests/test_x.py"]), ["test_mapped"])
    assert st == mc.VACUOUS
    assert "never ran" in why


def test_a_mutant_that_does_not_parse_is_vacuous():
    st, _, _ = mc.classify(_rep([_call_fail("test_mapped")]), ["test_mapped"], compile_ok=False)
    assert st == mc.VACUOUS


def test_missing_evidence_fails_toward_vacuous_never_toward_killed():
    """An unreadable run has demonstrated nothing. A gate that scores unknown as success is the
    exact defect it exists to catch."""
    assert mc.classify(None, ["test_mapped"])[0] == mc.VACUOUS


def test_setup_failure_is_vacuous_because_the_claim_was_never_evaluated():
    st, _, _ = mc.classify(
        _rep([{"nodeid": "test_mapped", "when": "setup", "outcome": "failed",
               "exception_class": "ImportError"}]), ["test_mapped"])
    assert st == mc.VACUOUS


def test_clean_call_phase_is_survived():
    assert mc.classify(_rep([{"nodeid": "test_mapped", "when": "call", "outcome": "passed",
                              "exception_class": None}]), ["test_mapped"])[0] == mc.SURVIVED


def test_collateral_is_recorded_not_discarded():
    """M6 legitimately reds four tests -- the mutation makes JCS emit a trailing byte, so
    everything JCS-dependent breaks. Dropping that silently loses the signal that a mutation is
    less surgical than its label implies."""
    st, _, ev = mc.classify(
        _rep([_call_fail("test_mapped"), _call_fail("test_other_1"), _call_fail("test_other_2")]),
        ["test_mapped"])
    assert st == mc.KILLED
    assert sorted(ev["collateral_failures"]) == ["test_other_1", "test_other_2"]


def test_tally_is_four_independent_counts_summing_to_the_mutant_total():
    counts = mc.tally([{"status": "KILLED"}, {"status": "SURVIVED"},
                       {"status": "VACUOUS"}, {"status": "NOT_APPLIED"}], 4)
    assert counts == {"KILLED": 1, "SURVIVED": 1, "VACUOUS": 1, "NOT_APPLIED": 1}


def test_tally_raises_rather_than_reporting_a_wrong_sum():
    """A number derived by subtraction can hide a category nobody named -- and this artifact named
    two in a single day (VACUOUS, and unmapped-red-is-not-a-kill). The invariant is the guard
    against the third, so it must be a HARD failure and not a reported field."""
    try:
        mc.tally([{"status": "KILLED"}], 2)
    except AssertionError as e:
        assert "state nobody named" in str(e)
    else:
        raise AssertionError("tally accepted a short sum -- the invariant is not load-bearing")


def test_vacuous_is_its_own_state_never_folded_into_survived():
    """'The mutation proved nothing' and 'the suite failed to catch it' are different facts.
    Collapsing them is the same digit-collapse that made 16/16 read as coverage it did not have."""
    assert mc.VACUOUS in mc.STATES and mc.SURVIVED in mc.STATES
    assert mc.VACUOUS != mc.SURVIVED
    assert len(set(mc.STATES)) == 4
