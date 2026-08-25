#!/usr/bin/env python3
"""Reference runner for the three-party action-binding vectors. Stdlib only, no network.

Reports WHICH check rejected each negative, not merely that one did. That distinction is the
whole point of the fixture: a vector rejected for the wrong reason proves nothing about the
property it was written to test, and looks identical in an aggregate count.

Usage:  python check.py [vectors.json]
Exit 0 iff every positive is accepted AND every negative is rejected FOR ITS DECLARED REASON.
"""
import hashlib
import json
import os
import sys

H = lambda b: hashlib.sha256(b).hexdigest()


def jcs(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def is_hex64(s):
    return isinstance(s, str) and len(s) == 64 and all(c in "0123456789abcdef" for c in s.lower())


def check(rec, domain, resolvable):
    """-> (ok, reason). Order matters: the seam check runs BEFORE the structural one.

    That ordering is deliberate and is the fixture's sharpest requirement. N5 carries the seam
    defect AND a malformed action_ref; a runner that validates structure first rejects it as a
    parse error and never demonstrates it can see the seam at all. Checking the semantic property
    first forces the runner to prove the capability the vector is testing.
    """
    body = jcs({"agent_id": rec["agent_id"], "action_type": rec["action_type"],
                "scope": rec["scope"]})

    if rec.get("args_digest") != H(jcs(rec["args"])):
        return False, "cross-coordinate-mismatch"

    if not is_hex64(rec.get("action_ref", "")):
        return False, "malformed-action-ref"

    ar = rec["action_ref"]
    if ar == H(body):
        return False, "missing-domain-separation"
    if ar == H(domain + H(body).encode()):
        return False, "domain-tag-not-prefixed"
    if ar != H(domain + body):
        return False, "action-ref-does-not-recompute"

    if not resolvable(rec.get("evidence_ref") or {}):
        return False, "evidence-not-retrievable"

    return True, None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "vectors.json")
    v = json.load(open(path))
    domain = bytes.fromhex(v["domain_tag_hex"])

    # Offline stand-in for retrievability. A real verifier queries the chain; the vector set only
    # needs the DISTINCTION between resolvable and not, so the fixture stays hermetic.
    known = {"0x" + "11" * 32}
    resolvable = lambda e: e.get("tx_hash") in known

    fails = []
    for p in v["positives"]:
        ok, why = check(p["record"], domain, resolvable)
        print(f"  POSITIVE {p['id']:34} {'ACCEPT' if ok else 'REJECT(' + str(why) + ')'}")
        if not ok:
            fails.append(f"{p['id']}: positive rejected as {why}")

    for n in v["negatives"]:
        ok, why = check(n["record"], domain, resolvable)
        exp = n["expected_reject_reason"]
        verdict = "ACCEPTED" if ok else why
        match = (not ok) and why == exp
        print(f"  NEGATIVE {n['id']:34} {verdict:32} expected={exp:28} {'OK' if match else 'MISMATCH'}")
        if ok:
            fails.append(f"{n['id']}: negative ACCEPTED")
        elif not match:
            fails.append(f"{n['id']}: rejected as '{why}', expected '{exp}' -- rejected for the "
                         f"WRONG REASON, which is not evidence for this property")

    print()
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
        return 1
    print(f"all {len(v['positives'])} positives accepted; all {len(v['negatives'])} negatives "
          f"rejected FOR THEIR DECLARED REASON")
    return 0


if __name__ == "__main__":
    sys.exit(main())
