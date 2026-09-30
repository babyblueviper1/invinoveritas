#!/usr/bin/env python3
"""Decision-record conformance checker, standard library only, written from SPEC.md (not from the service).

    python3 check.py vectors.json          # exit 0 iff every vector's verdict and reject_reason match
"""
import hashlib
import json
import sys

APPROVING = ("approve", "approve_with_concerns")


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def jcs(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def check_set(items):
    """(verdict, reason) for an ordered set of {record, reveal, review} items."""
    used = set()
    for it in items:
        rec, rv, review = it["record"], it["reveal"], it.get("review")
        c = lambda v: sha(f"{rv['salt']}|{v}")
        opened = {"question_commitment": c(rv["question"]), "options_commitment": c(jcs(rv["options"])),
                  "choice_commitment": c(rv["choice"]), "context_commitment": c(rv["context_sha256"]),
                  "gate_policy_commitment": c(jcs(sorted(rv["irreversible_options"])))}
        if any(rec.get(k) != v for k, v in opened.items()):
            return "reject", "commitment_mismatch"
        if rv["choice"] not in rv["options"]:
            return "reject", "choice_not_in_options"
        gated = rv["choice"] in rv["irreversible_options"]
        if rec.get("gated") is not gated:
            return "reject", "gated_flag_mismatch"
        if not gated or not rec["gate"].get("executable"):
            continue
        if not review:
            return "reject", "executable_without_review"
        if review.get("artifact_hash") != rv["context_sha256"]:
            return "reject", "review_context_mismatch"
        args = {"context_sha256": rv["context_sha256"], "question_sha256": sha(rv["question"]),
                "options_sha256": sha(jcs(rv["options"])), "choice": rv["choice"]}
        if (review.get("action_binding_tool_hash") != "sha256:" + sha("decision_receipt")
                or review.get("action_binding_args_hash") != "sha256:" + sha(jcs(args))):
            return "reject", "review_binding_mismatch"
        if review.get("verdict") not in APPROVING:
            return "reject", "executable_without_approval"
        if review.get("decision_ref") in used:
            return "reject", "review_reused"
        used.add(review.get("decision_ref"))
    return "accept", None


def main(path):
    suite = json.load(open(path))
    bad = 0
    for vec in suite["vectors"]:
        got, why = check_set(vec["records"])
        ok = got == vec["expect"] and why == vec.get("reject_reason")
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {vec['id']:3} {got:6} {why or '':28} {vec['description']}")
    print(f"{len(suite['vectors']) - bad}/{len(suite['vectors'])} vectors agree")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "vectors.json"))
