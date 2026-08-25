"""Phase-bound outcome recorder for the ERC-8309 mutation gates.

Design: Merlini (2026-08-25), with Pavlo's expected_kill_tests precision. Dropped into the
staged test directory of each mutant run; writes one JSON blob the gate reads back.

WHY A HOOK AND NOT A SUMMARY-LINE MATCH. The gate previously decided KILLED by looking for the
word "failed" in pytest's summary line. That agreed with the sound rule on every live mutant --
and only because pytest happens to map call-phase failures to "failed" and pre-call breakage to
"error". Correct by coincidence of another tool's formatting is not correct by construction.

The decisive case is stronger than "hard to parse": A COLLECTION ERROR CAN ABORT THE KILL TESTS
SO THEY NEVER EXECUTE AT ALL. There is then nothing on the summary line to recover, however
cleverly it is read -- the evidence does not exist in aggregate counts, so no heuristic over them
can be sound. That is a claim about what is knowable, and it is why the hook is the only closure.

What gets recorded per test: nodeid, when (setup/call/teardown), outcome, and the exception class.
`when` is the load-bearing field: a raise during the CALL phase can be the violated behaviour
itself (a ValueError where a never-raise MUST is enforced) and is a genuine kill, while the same
exception class at collect/setup means the claim was never evaluated.
"""
import json
import os

_RECORDS = []
_COLLECT_ERRORS = []
_OUT = os.environ.get("MUTATION_REPORT_PATH", "mutation_report.json")


def pytest_runtest_makereport(item, call):
    _RECORDS.append({
        "nodeid": item.nodeid.split("::")[-1],
        "when": call.when,
        "outcome": "failed" if call.excinfo is not None else "passed",
        "exception_class": call.excinfo.typename if call.excinfo is not None else None,
    })


def pytest_collectreport(report):
    if report.failed:
        _COLLECT_ERRORS.append(str(report.nodeid))


def pytest_sessionfinish(session, exitstatus):
    with open(_OUT, "w") as fh:
        json.dump({"records": _RECORDS, "collect_errors": _COLLECT_ERRORS,
                   "exitstatus": int(exitstatus)}, fh)
