#!/usr/bin/env python3
"""Mutation controls for check.py (PROFILE.md "Test cases": every check must be load-bearing; a crash is a crash, not a kill).

For each line in check.py tagged `# CHECK:<id>`, write a mutant whose condition is replaced by False (the check deleted), run
every vector, and classify it: KILLED (some vector's verdicts change -- a false green or a wrong verdict exposed), SURVIVED (no
vector notices: the check is not load-bearing or the vectors miss it), CRASHED (the mutant raised: counted separately, never as
a kill). Exit 0 only if every mutant is killed, none crashed, and the unmutated checker matches every vector.
usage: python3 mutants.py
"""
import importlib.util
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "check.py")).read()
VEC = json.load(open(os.path.join(HERE, "vectors.json")))["vectors"]
TAG = re.compile(r"^(\s*)if (.+?): (.+?)  # CHECK:(\w+)\s*$")


def load(src, name):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "check.py")
    open(p, "w").write(src)
    sys.path.insert(0, HERE)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def verdicts(m):
    out = []
    for v in VEC:
        try:
            r = m.check(v["fixture"])
            out.append({k: r[k]["verdict"] for k in ("encoded", "reviewed", "signed", "executed")})
        except Exception as e:
            out.append({"crash": type(e).__name__})
    return out


def main():
    lines = SRC.splitlines(keepends=True)
    base = verdicts(load(SRC, "check_base"))
    want = [v["expect"] for v in VEC]
    base_ok = base == want
    print(f"unmutated checker: {sum(a == b for a, b in zip(base, want))}/{len(VEC)} vectors match")
    killed = survived = crashed = 0
    for i, ln in enumerate(lines):
        m = TAG.match(ln)
        if not m:
            continue
        cid = m.group(4)
        mut = lines[:i] + [f"{m.group(1)}if False: {m.group(3)}  # MUTANT:{cid}\n"] + lines[i + 1:]
        try:
            got = verdicts(load("".join(mut), f"check_mut_{cid}"))
        except Exception as e:
            crashed += 1; print(f"  CRASHED   {cid} ({type(e).__name__})"); continue
        if any("crash" in g for g in got):
            crashed += 1; print(f"  CRASHED   {cid} (a vector raised)"); continue
        flips = [VEC[j]["name"] for j in range(len(VEC)) if got[j] != want[j]]
        if flips:
            killed += 1; print(f"  KILLED    {cid:20} by {', '.join(flips[:3])}{' ...' if len(flips) > 3 else ''}")
        else:
            survived += 1; print(f"  SURVIVED  {cid}")
    total = killed + survived + crashed
    print(f"{killed}/{total} mutants killed, {survived} survived, {crashed} crashed")
    sys.exit(0 if base_ok and survived == 0 and crashed == 0 and total > 0 else 1)


if __name__ == "__main__":
    main()
