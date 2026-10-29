#!/usr/bin/env python3
"""Mutation run for deils-anchor-v1 (review 5; Echo TG 5890: "commit the mutation script next to the vectors, so the next reviewer can
replay it rather than take it on trust"). Standard library only, offline.

Part 1, MUTANTS: each entry edits one line of check.py / ots_verify.py / pins.py in a temporary copy of this directory and runs the
vectors (and pins.py --self-test for pins.py mutants). A mutant is KILLED when any vector (or the self-test) fails. Entries marked
equivalent=True are known equivalent mutants: no input can tell them apart, and they are expected to survive (reason given).

Part 2, WITNESSES (Pavlo TG 5889: negative witnesses for an incorrect date / height): every chain vector's pinned result fields are
tampered one at a time in a copy of vectors.json -- each day's date, each confirmed day's height, checked_from, from_genesis,
after_failure -- and the runner must report FAIL for every tamper. This proves the runner compares those fields, not just that the
checker produces them.

Part 3, CONTROLS (review 5 replay, Pavlo TG 5930): a crash is its own outcome, never a kill, and a witness counts as caught only
when the run finished and its own tampered vector is the line that failed; two built-in controls fail this run if either guard is
removed.

usage: python3 mutants.py            exit 0 iff the controls hold, every non-equivalent mutant is killed (none crashed) and every
                                     witness is caught by its own vector"""
import json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ("check.py", "ots_verify.py", "pins.py", "bip340.py", "vectors.json")

# (file, old text (must occur exactly once), new text, what the mutant breaks, equivalent?)
MUTANTS = [
    # chain and positions
    ("check.py", 'carried = prev_hdr["last_position"] if prev_hdr["count"] else prev_hdr["prev_last_position"]', 'carried = hdr["prev_last_position"]', "empty-day carry-forward"),
    ("check.py", '            codes.append("prev_last_mismatch")', "            pass", "prev_last_position must follow the previous day"),
    ("check.py", '            codes.append("position_gap")', "            pass", "positions are consecutive inside a day"),
    ("check.py", '            codes.append("created_at_after_day")', "            pass", "a record dated after its day fails"),
    ("check.py", '        if date in claims and state != "confirmed":', "        if False:", "a pending day claimed confirmed fails (pending_claimed_confirmed)"),
    # genesis and terminal failure
    ("check.py", 'elif state == "confirmed" and chain_ok and from_genesis:', 'elif state == "confirmed" and from_genesis:', "a failed day is terminal for every later day"),
    ("check.py", 'elif state == "confirmed" and chain_ok and from_genesis:', 'elif state == "confirmed" and chain_ok:', "anchored needs the chain checked from genesis"),
    ("check.py", 'from_genesis = hdr["prev_root"] == ZERO and hdr["prev_last_position"] == 0', 'from_genesis = hdr["prev_root"] == ZERO', "genesis half 1: zeros root alone is not genesis"),
    ("check.py", 'from_genesis = hdr["prev_root"] == ZERO and hdr["prev_last_position"] == 0', 'from_genesis = hdr["prev_last_position"] == 0', "genesis half 2 (mirror): position 0 alone is not genesis"),
    # late records and the grace window
    ("check.py", 'elif r["created_at"] < s:', 'elif r["created_at"] < s - 1:', "late_record starts at the day's 00:00:00 edge"),
    ("check.py", 'notices.append("late_record_beyond_grace" if r["created_at"] < s - GRACE_S else "late_record")', 'notices.append("late_record_beyond_grace" if r["created_at"] <= s - GRACE_S else "late_record")', "grace edge: start - 86400 is inside"),
    ("check.py", 'notices.append("late_record_beyond_grace" if r["created_at"] < s - GRACE_S else "late_record")', 'notices.append("late_record_beyond_grace" if r["created_at"] < s - GRACE_S - 1 else "late_record")', "grace edge: start - 86401 is beyond"),
    ("check.py", 'notices.append("late_record_beyond_grace" if r["created_at"] < s - GRACE_S else "late_record")', 'notices.append("late_record")', "the two late notices are distinct"),
    ("check.py", 'notices.append("late_record_beyond_grace" if r["created_at"] < s - GRACE_S else "late_record")', 'pass', "a late record is reported at all"),
    # field types and spellings
    ("check.py", 'if kind == "hex64" and not (isinstance(v, str) and HEX64.fullmatch(v)): return False', 'if kind == "hex64" and not (isinstance(v, str) and HEX64.match(v)): return False', "hex64 is a whole-string match (trailing newline)"),
    ("check.py", 'if kind == "date" and not (isinstance(v, str) and DATE_RE.fullmatch(v)): return False', 'if kind == "date" and not (isinstance(v, str) and DATE_RE.match(v)): return False', "date is a whole-string match (trailing newline)"),
    ("check.py", 'HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)', 'HEX64 = re.compile(r"[0-9a-fA-F]{64}", re.ASCII)', "lower-case hex only (one spelling per id)"),
    ("check.py", 'HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)', 'HEX64 = re.compile(r"[0-9a-f]{63,64}", re.ASCII)', "exactly 64 hex characters"),
    ("check.py", 'if kind == "int?" and v is not None and type(v) is not int: return False', "pass", "type int? (string or float in an int? field)"),
    ("check.py", 'if kind == "date" and not (isinstance(v, str) and DATE_RE.fullmatch(v)): return False', "pass", "header date type and spelling"),
    ("check.py", 'DATE_RE = re.compile(r"\\d{4}-\\d{2}-\\d{2}", re.ASCII)', 'DATE_RE = re.compile(r"\\d{4}-\\d{2}-\\d{2}")', "EQUIVALENT: a non-ASCII digit never reaches the regex (rejected at canonicalisation: line_not_canonical / bad_fields); kept as defense in depth (Echo TG 5890)", True),
    # merkle tree
    ("check.py", 'k *= 2', 'k += 1', "RFC 9162 split at the largest power of two below n"),
    ("check.py", 'b"\\x00" + leaves[0]', "leaves[0]", "leaf domain separation"),
    # records
    ("check.py", 'ev.get("pubkey") == issuer and ', "", "issuer pin on signed records"),
    ("check.py", 'return _h(_nip01([0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]]).encode("utf-8")).hex()',
     'return _h(json.dumps([0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]], separators=(",", ":"), ensure_ascii=False).encode()).hex()',
     "NIP-01 serialization (control characters verbatim)"),
    # section-8 output fields (review 4) and date / height (review 5)
    ("check.py", '"checked_from": checked_from, "from_genesis": bool(from_genesis), "after_failure": not chain_ok and not codes})',
     '"checked_from": checked_from, "from_genesis": True, "after_failure": not chain_ok and not codes})', "from_genesis is reported, not assumed"),
    ("check.py", '"checked_from": checked_from, "from_genesis": bool(from_genesis), "after_failure": not chain_ok and not codes})',
     '"checked_from": checked_from, "from_genesis": bool(from_genesis), "after_failure": False})', "after_failure is reported"),
    ("check.py", '"checked_from": checked_from, "from_genesis": bool(from_genesis), "after_failure": not chain_ok and not codes})',
     '"checked_from": date, "from_genesis": bool(from_genesis), "after_failure": not chain_ok and not codes})', "checked_from is the first checked day, not this day"),
    ("check.py", 'out.append({"date": date, "status": status', 'out.append({"date": checked_from, "status": status', "REVIEW 5: each day reports its own date"),
    ("check.py", 'out.append({"date": date, "status": status', 'out.append({"date": None, "status": status', "REVIEW 5: the date is reported"),
    ("check.py", 'state, height = o["state"], o["height"]', 'state, height = o["state"], (o["height"] or 0) + 1 if o["height"] else None', "REVIEW 5: the confirmed height is the attested block"),
    ("check.py", 'state, height = o["state"], o["height"]', 'state, height = o["state"], None', "REVIEW 5: a confirmed day reports its height"),
    ("check.py", 'state, height = "published", None', 'state, height = "published", 0', "REVIEW 5: a day with no confirmation reports no height"),
    # OpenTimestamps
    ("ots_verify.py", "    if r.i != len(ots):", "    if False:", "trailing bytes after the proof are malformed"),
    ("ots_verify.py", '        if int.from_bytes(hb[72:76], "little") != want:', "        if False:", "header bits must equal the pinned epoch bits"),
    ("ots_verify.py", "        if not _pow_ok(hb, want):", "        if False:", "proof of work under the pinned target"),
    ("ots_verify.py", '        if hb[36:68] != a["msg"]:', "        if False:", "the header's merkle root is the attested message"),
    ("ots_verify.py", "        if want is None:\n            codes.append(\"ots_bits_unpinned\"); continue",
     "        if want is None:\n            codes.append(\"ots_header_bits_mismatch\"); continue", "an unpinned epoch is pending, not a failure (epoch 483 rollover)"),
    ("ots_verify.py", 'NOT_CONFIRMING = {"ots_bitcoin_header_missing", "ots_bits_unpinned"}', 'NOT_CONFIRMING = {"ots_bitcoin_header_missing"}', "unpinned epoch end to end: not_anchored, never failed"),
    # pins.py (judged by pins.py --self-test)
    ("pins.py", "    if len({x for _, x in got}) != 1:", "    if False:", "pins: sources must agree"),
    ("pins.py", '    if int.from_bytes(hashlib.sha256(hashlib.sha256(header).digest()).digest(), "little") > target:', "    if False:", "pins: the header must meet its own proof of work"),
]


def _copy():
    d = tempfile.mkdtemp(prefix="anchor_mut_")
    for f in FILES:
        shutil.copy(os.path.join(HERE, f), d)
    shutil.copytree(os.path.join(HERE, "ots"), os.path.join(d, "ots"))
    return d


def _outcome(d, cmd, summary):
    """Run one harness command in d. Returns ("ran", failed_lines) only when it finished normally: exit 0 or 1, a final summary line
    "N/M <summary>", M equal to the number of PASS/FAIL lines, N equal to the PASS count, and exit 1 exactly when a line failed.
    Anything else (a traceback, another exit code, a hang, a missing or inconsistent summary) is ("crashed", reason): a crash shows
    nothing about whether a check caught the change, so it is never counted as a kill or a caught witness (review 5 replay, Pavlo
    TG 5930: mutants.py:91 counted any nonzero exit as KILLED, mutants.py:145 any stdout containing FAIL as caught)."""
    try:
        r = subprocess.run([sys.executable, "-I", "-B"] + cmd, cwd=d, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "crashed", "timeout"
    lines = r.stdout.splitlines()
    res = [x for x in lines if x.startswith(("PASS ", "FAIL "))]
    m = re.fullmatch(r"(\d+)/(\d+) " + re.escape(summary), lines[-1]) if lines else None
    fails = [x[5:] for x in res if x.startswith("FAIL ")]
    if (r.returncode not in (0, 1) or not m or int(m.group(2)) != len(res) or int(m.group(1)) != len(res) - len(fails)
            or (r.returncode == 1) != bool(fails)):
        return "crashed", f"exit {r.returncode}, last line {lines[-1][:60] if lines else '(none)'!r}"
    return "ran", fails


def _run(d, pins_test):
    """killed / survived / crashed for one mutant: killed only when a check ran to the end and reported a failure."""
    runs = [_outcome(d, ["check.py", "--vectors", "vectors.json"], "vectors pass")]
    if pins_test:
        runs.append(_outcome(d, ["pins.py", "--self-test"], "pins self-test"))
    if any(k == "crashed" for k, _ in runs):
        return "crashed"
    return "killed" if any(f for _, f in runs) else "survived"


def mutants():
    killed = survived = crashed = equiv_ok = 0; problems = []
    for m in MUTANTS:
        f, old, new, what = m[:4]; equivalent = len(m) > 4 and m[4]
        d = _copy()
        try:
            src = open(os.path.join(d, f)).read()
            if src.count(old) != 1:
                problems.append(f"STALE mutant (text not found exactly once in {f}): {what}"); continue
            open(os.path.join(d, f), "w").write(src.replace(old, new))
            res = _run(d, f == "pins.py")
        finally:
            shutil.rmtree(d, ignore_errors=True)
        if res == "crashed":
            crashed += 1; problems.append(f"CRASHED (not counted as killed): {what}"); print("CRASHED  " + what); continue
        dead = res == "killed"
        if equivalent:
            equiv_ok += not dead
            print(("equivalent, survives as expected: " if not dead else "equivalent but KILLED (re-check the note): ") + what)
            if dead:
                problems.append(f"marked equivalent but killed: {what}")
        elif dead:
            killed += 1; print("killed   " + what)
        else:
            survived += 1; problems.append(f"SURVIVED: {what}"); print("SURVIVED " + what)
    n = len([m for m in MUTANTS if not (len(m) > 4 and m[4])])
    print(f"mutants: {killed}/{n} killed, {survived} survived, {crashed} crashed; {equiv_ok} equivalent (expected to survive)")
    return problems


def _witness_caught(kind, fails, name):
    """A tamper is caught only when the run finished and the one tampered vector itself is the line that failed."""
    return kind == "ran" and fails == [name]


def controls():
    """Removal controls for both guards: each fails the harness if its guard is taken out. (1) A mutant that crashes the runner must
    be classed crashed, not killed. (2) A runner that prints a FAIL line without running any check must not count as a caught witness,
    and neither may a finished run whose failing line names another vector."""
    problems = []
    d = _copy()
    try:
        src = open(os.path.join(d, "check.py")).read()
        open(os.path.join(d, "check.py"), "w").write(src.replace("def run_vectors(path):\n", "def run_vectors(path):\n    raise RuntimeError('control')\n", 1))
        if _run(d, False) != "crashed":
            problems.append("control 1: a crashing mutant was not classed crashed")
        open(os.path.join(d, "check.py"), "w").write(src.replace("def run_vectors(path):\n", "def run_vectors(path):\n    print('FAIL x'); return 1\n", 1))
        k, fails = _outcome(d, ["check.py", "--vectors", "vectors.json"], "vectors pass")
        if _witness_caught(k, fails, "x"):
            problems.append("control 2: a FAIL line with no checks run counted as a caught witness")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if _witness_caught("ran", ["another vector"], "this vector"):
        problems.append("control 2b: a failure on another vector counted as this vector's witness")
    print(f"controls: {3 - len(problems)}/3 (crash is not a kill; FAIL text without checks or on another vector is not a caught witness)")
    return problems


def witnesses():
    v = json.load(open(os.path.join(HERE, "vectors.json")))
    caught = missed = 0; problems = []
    for vi, t in enumerate(v["vectors"]):
        if t.get("ots_only"):
            continue
        for di, w in enumerate(t["expect"]):
            tampers = [("date", None if w["date"] else "2026-01-01"), ("checked_from", "1999-01-01"),
                       ("from_genesis", not w["from_genesis"]), ("after_failure", not w["after_failure"])]
            if w["state"] == "confirmed":
                tampers += [("height", w["height"] + 1), ("height", None)]
            for field, bad in tampers:
                v2 = json.loads(json.dumps(v)); v2["vectors"][vi]["expect"][di][field] = bad
                v2["vectors"] = [v2["vectors"][vi]]
                d = _copy()
                try:
                    json.dump(v2, open(os.path.join(d, "vectors.json"), "w"))
                    k, fails = _outcome(d, ["check.py", "--vectors", "vectors.json"], "vectors pass")
                finally:
                    shutil.rmtree(d, ignore_errors=True)
                if _witness_caught(k, fails, t["name"]):
                    caught += 1
                else:
                    missed += 1; problems.append(f"witness NOT caught: {t['name'][:60]} day {di + 1} {field}={bad}")
    print(f"witnesses: {caught}/{caught + missed} tampered expectations caught (date, height, checked_from, from_genesis, after_failure)")
    return problems


if __name__ == "__main__":
    p = controls() + mutants() + witnesses()
    for x in p:
        print("PROBLEM " + x)
    sys.exit(1 if p else 0)
