"""Phase-bound mutant classification, shared by both ERC-8309 gates.

THE LADDER (Merlini's design; expected_kill_tests and the teardown exclusion from Pavlo):

    mutation pattern does not apply .................... NOT_APPLIED
    mutated module fails py_compile .................... VACUOUS
    collect / import / setup fails before the call ..... VACUOUS
    call phase fails IN A MAPPED ENFORCING TEST ........ KILLED
    call phase executes cleanly ........................ SURVIVED

Every rung exists because of a specific way the previous version was wrong:

VACUOUS is its own state, never folded into SURVIVED. "The mutation proved nothing" and "the
suite failed to catch it" are different facts about different things, and collapsing them is the
same digit-collapse that made 16/16 read as coverage it did not have. Discovered the hard way:
M6 was recorded KILLED for 22.5 hours because its replacement string emitted a real newline into
a bytes literal (re.sub processes escapes in the replacement), producing a SyntaxError -- pytest
reported a collection error, the gate saw not-green, and scored a kill.
(This line said "for a week" until 2026-08-25. It was 22.5 hours. I wrote the original from
impression rather than from the timestamps, and the exaggeration ran in the direction that made
the find sound better -- the same failure this whole round is about, in the file explaining it.
Corrected here after correcting it publicly rather than quietly dropping the number.) The mutant never tested
the trailing-byte claim. It broke the file.

MAPPED TESTS, not any test (Pavlo). A call-phase failure anywhere in the suite can certify a MUST
by accident. Measured on the live gate before adopting: 14 of 16 spec mutants kill exactly one
test and it is the mapped one -- but M11 kills its own enforcer AND M4's, so it is ONE DELETED
TEST away from being certified entirely by a test written for a different MUST. Nothing is
mis-certified today; the gate simply had no way to notice when that changes.

TEARDOWN-ONLY RED IS NOT A KILL. Teardown runs after the claim has already been evaluated, so a
failure there says nothing about the MUST.

COLLATERAL IS RECORDED, NOT DISCARDED. When a mutation reds tests beyond its mapped ones, that is
real information -- it measures blast radius against mapped claim. M6 legitimately reds four
tests (it makes JCS emit a trailing byte, so everything JCS-dependent breaks). Dropping that
silently loses the signal that a mutation is less surgical than its label implies.
"""
from __future__ import annotations

NOT_APPLIED = "NOT_APPLIED"
VACUOUS = "VACUOUS"
KILLED = "KILLED"
SURVIVED = "SURVIVED"

STATES = (KILLED, SURVIVED, VACUOUS, NOT_APPLIED)


def classify(report: dict, expected_kill_tests, compile_ok: bool = True) -> tuple:
    """-> (state, reason, evidence). `report` is the conftest blob; None means it never wrote one.

    Fails toward VACUOUS on missing evidence rather than toward KILLED: an unreadable run has not
    demonstrated anything, and a gate that scores unknown as success is the defect it exists to
    catch.
    """
    if not compile_ok:
        return VACUOUS, "mutated module fails py_compile -- the claim was never evaluated", {}
    if report is None:
        return VACUOUS, "no phase report was written -- the run produced no usable evidence", {}

    if report.get("collect_errors"):
        return (VACUOUS,
                "collection/import failed before the test call -- the enforcing test never ran, "
                "so nothing on the summary line could recover its intent",
                {"collect_errors": report["collect_errors"]})

    records = report.get("records") or []
    call_fails = [r for r in records if r.get("when") == "call" and r.get("outcome") == "failed"]
    pre_call = [r for r in records if r.get("when") == "setup" and r.get("outcome") == "failed"]

    expected = set(expected_kill_tests or ())
    mapped = [r for r in call_fails if r["nodeid"] in expected]
    collateral = [r["nodeid"] for r in call_fails if r["nodeid"] not in expected]

    if mapped:
        return (KILLED,
                "call-phase failure in a mapped enforcing test (assertion, or an exception the "
                "test treats as the violated behaviour)",
                {"killed_by": [r["nodeid"] for r in mapped],
                 "exception_classes": sorted({r["exception_class"] for r in mapped if r["exception_class"]}),
                 "collateral_failures": collateral})

    if pre_call:
        return (VACUOUS, "setup failed before the test call -- the claim was never evaluated",
                {"setup_failures": [r["nodeid"] for r in pre_call]})

    if call_fails:
        return (SURVIVED,
                "the suite went red, but NOT in this mutant's mapped enforcing test -- an "
                "unrelated assertion does not certify this MUST",
                {"unmapped_failures": collateral, "expected_kill_tests": sorted(expected)})

    return (SURVIVED, "every call phase executed cleanly -- no enforcing vector",
            {"expected_kill_tests": sorted(expected)})


def tally(results: list, total_mutants: int) -> dict:
    """Four INDEPENDENT counts. The sum invariant is a HARD failure, never a reported field.

    A number derived by subtraction can always hide a category nobody named -- and this artifact
    named two in a single day (VACUOUS, and unmapped-red-is-not-a-kill). The invariant is the
    guard against the third.
    """
    counts = {s: sum(1 for r in results if r.get("status") == s) for s in STATES}
    total = sum(counts.values())
    if total != total_mutants:
        raise AssertionError(
            f"mutant tally {counts} sums to {total}, expected {total_mutants}. A mutant is in a "
            f"state nobody named -- fix the classifier rather than the count.")
    return counts


def summarize(counts: dict) -> dict:
    """The SERIALIZED summary, derived from the four independent counts and nothing else.

    WHY THIS IS A FUNCTION RATHER THAN A DICT LITERAL IN EACH GATE (2026-08-25, found by Merlini
    on a clean clone of public main c97e3fc2). Both gates hand-built their own summary as

        {"applied": applied, "killed": killed, "survived": applied - killed, "not_applied": ...}

    which dropped VACUOUS entirely and derived survived by SUBTRACTION -- the exact collapse this
    round removed, inside the artifact built to close it, duplicated identically in two files. It
    read correct only because vacuous == 0; one vacuous mutant and the summary said "survived: 1"
    while tally() correctly held VACUOUS:1, SURVIVED:0, and the console printed "SURVIVING mutants
    are normative MUSTs with no enforcing vector -- real gaps" for a mutant that proved nothing.

    Two copies of a rule is two chances to break it. The counting was never wrong -- the
    SERIALIZATION was -- so the fix is to make the serialized form a function of the counts, in one
    place, with a test. `applied_derived` is named for what it is: every other number is counted.
    """
    for s in STATES:
        if s not in counts:
            raise AssertionError(
                f"summary is missing state {s!r}. A state that is not serialized cannot be read, "
                f"and an unread state is how a vacuous mutant passes for a survivor.")
    return {
        KILLED.lower(): counts[KILLED],
        SURVIVED.lower(): counts[SURVIVED],
        VACUOUS.lower(): counts[VACUOUS],
        NOT_APPLIED.lower(): counts[NOT_APPLIED],
        "applied_derived": counts[KILLED] + counts[SURVIVED] + counts[VACUOUS],
    }
