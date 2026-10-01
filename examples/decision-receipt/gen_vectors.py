#!/usr/bin/env python3
"""Generate the decision-record conformance vectors (stdlib only, deterministic).

    python3 gen_vectors.py > vectors.json

A decision record commits, before the action, to what a bounded-choice decider was asked, which options
it had, what it chose, and which options the deployer declared irreversible. Every public field is a
salted commitment: c(v) = sha256(salt + "|" + v). The reveal opens them. See SPEC.md.
"""
import copy
import hashlib
import json
import sys

SALT = "5a" * 32
CTX = "deploy build 4f2a to the canary pool; error budget 0.4% left; last canary 3 days ago"


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def jcs(v):
    # RFC 8785 for arrays/objects of ASCII strings (all these vectors use) is compact, sorted-key JSON.
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def c(v):
    return sha(f"{SALT}|{v}")


def binding_args(rv):
    return {"context_sha256": rv["context_sha256"], "question_sha256": sha(rv["question"]),
            "options_sha256": sha(jcs(rv["options"])), "choice": rv["choice"]}


def record(rv, gate):
    out = _record(rv, gate)
    if "accepted_review_issuers" in rv:      # v0.2 only; v0 vectors never carry it, so they regenerate byte-identical
        out["review_issuers_commitment"] = c(jcs(sorted(rv["accepted_review_issuers"])))
    return out


def _record(rv, gate):
    return {"question_commitment": c(rv["question"]), "options_commitment": c(jcs(rv["options"])),
            "choice_commitment": c(rv["choice"]), "context_commitment": c(rv["context_sha256"]),
            "gate_policy_commitment": c(jcs(sorted(rv["irreversible_options"]))),
            "gated": rv["choice"] in rv["irreversible_options"], "gate": gate}


ISSUER_A = "6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7"   # the invinoveritas verdict key (published at /ledger)
ISSUER_B = "b" * 64


def review(rv, verdict="approve", choice=None, ref="r1", issuer=None):
    args = binding_args(dict(rv, choice=choice or rv["choice"]))
    return {**({"issuer_pubkey": issuer} if issuer else {}), "artifact_hash": rv["context_sha256"], "verdict": verdict, "decision_ref": "sha256:" + sha(ref),
            "action_binding_tool_hash": "sha256:" + sha("decision_receipt"),
            "action_binding_args_hash": "sha256:" + sha(jcs(args))}


def main():
    base = {"salt": SALT, "question": "Next action for this deploy request?",
            "options": ["hold", "deploy_canary", "deploy_all"], "context_sha256": sha(CTX),
            "irreversible_options": ["deploy_canary", "deploy_all"]}
    hold = dict(base, choice="hold")
    canary = dict(base, choice="deploy_canary")
    V = []

    def v(vid, desc, records, expect, reason=None):
        V.append({"id": vid, "description": desc, "records": records, "expect": expect,
                  **({"reject_reason": reason} if reason else {})})

    ok = {"status": "cleared", "executable": True}
    v("p1", "ungated choice, executable without review", [
        {"record": record(hold, {"status": "not_gated", "executable": True}), "reveal": hold, "review": None}], "accept")
    v("p2", "gated choice cleared by an approving review bound to this context and this choice", [
        {"record": record(canary, dict(ok, review_decision_ref=review(canary)["decision_ref"])),
         "reveal": canary, "review": review(canary)}], "accept")
    v("p3", "gated choice without a review, recorded as not executable", [
        {"record": record(canary, {"status": "review_required", "executable": False}), "reveal": canary,
         "review": None}], "accept")
    v("p4", "gated choice, rejecting review, recorded as not executable", [
        {"record": record(canary, {"status": "review_rejected", "executable": False}), "reveal": canary,
         "review": review(canary, "reject")}], "accept")
    v("p5", "two gated records, each cleared by its own review", [
        {"record": record(canary, dict(ok, review_decision_ref=review(canary, ref="r1")["decision_ref"])),
         "reveal": canary, "review": review(canary, ref="r1")},
        {"record": record(canary, dict(ok, review_decision_ref=review(canary, ref="r2")["decision_ref"])),
         "reveal": canary, "review": review(canary, ref="r2")}], "accept")

    r = record(canary, {"status": "cleared", "executable": True})
    bad = copy.deepcopy(canary); bad["choice"] = "rollback_prod"
    v("n1", "the revealed choice is not one of the revealed options", [
        {"record": record(bad, {"status": "not_gated", "executable": True}), "reveal": bad, "review": None}],
      "reject", "choice_not_in_options")
    v("n2", "choice_commitment does not open to the revealed choice", [
        {"record": dict(record(hold, {"status": "not_gated", "executable": True}), choice_commitment=c("deploy_all")),
         "reveal": hold, "review": None}], "reject", "commitment_mismatch")
    v("n3", "gated choice marked executable with no review", [
        {"record": record(canary, {"status": "cleared", "executable": True}), "reveal": canary, "review": None}],
      "reject", "executable_without_review")
    other_ctx = dict(review(canary), artifact_hash=sha("a different context"))
    v("n4", "the review covers different bytes than the decision's context", [
        {"record": r, "reveal": canary, "review": other_ctx}], "reject", "review_context_mismatch")
    v("n5", "the review's action_binding names a different choice", [
        {"record": r, "reveal": canary, "review": review(canary, choice="deploy_all")}],
      "reject", "review_binding_mismatch")
    v("n6", "rejecting review, record marked executable", [
        {"record": r, "reveal": canary, "review": review(canary, "reject")}], "reject", "executable_without_approval")
    v("n7", "one review clears two records", [
        {"record": r, "reveal": canary, "review": review(canary, ref="r1")},
        {"record": r, "reveal": canary, "review": review(canary, ref="r1")}], "reject", "review_reused")
    swapped = dict(canary, irreversible_options=["deploy_all"])     # policy narrowed after the fact
    v("n8", "the revealed irreversible_options do not open gate_policy_commitment", [
        {"record": record(canary, {"status": "not_gated", "executable": True}),
         "reveal": swapped, "review": None}], "reject", "commitment_mismatch")
    v("n9", "record says not gated, but the committed policy gates the choice", [
        {"record": dict(record(canary, {"status": "not_gated", "executable": True}), gated=False),
         "reveal": canary, "review": None}], "reject", "gated_flag_mismatch")
    if "--v02" in sys.argv:
        # v0.2: the deployer commits to who may give the approving review. Same 14 v0 vectors, plus three.
        pol = dict(canary, accepted_review_issuers=[ISSUER_A])
        okp = {"status": "cleared", "executable": True}
        v("p6", "v0.2: gated choice cleared by an approving review from a listed issuer", [
            {"record": record(pol, dict(okp, review_decision_ref=review(pol, issuer=ISSUER_A)["decision_ref"])),
             "reveal": pol, "review": review(pol, issuer=ISSUER_A)}], "accept")
        v("n10", "v0.2: an approving review that covers this input and decision, from an issuer not in the committed list", [
            {"record": record(pol, okp), "reveal": pol, "review": review(pol, issuer=ISSUER_B)}],
          "reject", "review_issuer_not_permitted")
        v("n12", "v0.2: an approving review that names no issuer, under a committed issuer list", [
            {"record": record(pol, okp), "reveal": pol, "review": review(pol)}], "reject", "review_issuer_not_permitted")
        widened = dict(pol, accepted_review_issuers=[ISSUER_A, ISSUER_B])       # list widened after the fact
        v("n11", "v0.2: the revealed accepted_review_issuers do not open review_issuers_commitment", [
            {"record": record(pol, okp), "reveal": widened, "review": review(widened, issuer=ISSUER_B)}],
          "reject", "commitment_mismatch")
    json.dump({"suite": "decision-record-v0.2" if "--v02" in sys.argv else "decision-record-v0", "commitment": "sha256(salt + '|' + value)",
               "review_tool": "decision_receipt", "vectors": V}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
