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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bip340  # noqa: E402

SALT = "5a" * 32
CTX = "deploy build 4f2a to the canary pool; error budget 0.4% left; last canary 3 days ago"


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def jcs(v):
    # RFC 8785 for arrays/objects of ASCII strings (all these vectors use) is compact, sorted-key JSON.
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def c(v, salt=SALT):
    return sha(f"{salt}|{v}")


def binding_args(rv):
    return {"context_sha256": rv["context_sha256"], "question_sha256": sha(rv["question"]),
            "options_sha256": sha(jcs(rv["options"])), "choice": rv["choice"]}


def record(rv, gate):
    out = _record(rv, gate)
    if "accepted_review_issuers" in rv:      # v0.2 only; v0 vectors never carry it, so they regenerate byte-identical
        out["review_issuers_commitment"] = c(jcs(sorted(rv["accepted_review_issuers"])), rv["salt"])
    return out


def _record(rv, gate):
    s = rv["salt"]                           # every v0/v0.2 vector uses SALT; v0.3 adds records with their own salts
    return {"question_commitment": c(rv["question"], s), "options_commitment": c(jcs(rv["options"]), s),
            "choice_commitment": c(rv["choice"], s), "context_commitment": c(rv["context_sha256"], s),
            "gate_policy_commitment": c(jcs(sorted(rv["irreversible_options"])), s),
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
    V4 = "--v04" in sys.argv
    if "--v02" in sys.argv or "--v03" in sys.argv or V4:
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
    if "--v03" in sys.argv or V4:
        # v0.3: one choice per decision within a revealed set. Found by Toshikatsu Oga (HORIZON SHIELD / NENRIN),
        # 2026-10-09: with a fresh salt per record, an approve record and a deny record for the same tool call share
        # no public field, so a holder can keep both and reveal whichever helps. These vectors are his case.
        tctx = sha("tool call: transfer 500 USDC to 0x1111111111111111111111111111111111111111")
        call = {"question": "Allow this tool call?", "options": ["approve", "deny"], "context_sha256": tctx,
                "irreversible_options": []}
        appr = dict(call, salt="a1" * 32, choice="approve")
        deny = dict(call, salt="d0" * 32, choice="deny")
        free = {"status": "not_gated", "executable": True}
        v("p7", "v0.3 (Oga): approve record for a tool call, revealed alone", [
            {"record": record(appr, free), "reveal": appr, "review": None}], "accept")
        v("p8", "v0.3 (Oga): deny record for the same tool call, other salt, revealed alone (a checker cannot see the other record)", [
            {"record": record(deny, free), "reveal": deny, "review": None}], "accept")
        v("n13", "v0.3 (Oga): approve and deny records for one tool call (same context, question, options; different salts) in one set", [
            {"record": record(appr, free), "reveal": appr, "review": None},
            {"record": record(deny, free), "reveal": deny, "review": None}], "reject", "conflicting_choice")
        gcall = dict(call, irreversible_options=["approve"])
        gappr = dict(gcall, salt="a2" * 32, choice="approve")
        gdeny = dict(gcall, salt="d2" * 32, choice="deny")
        gok = {"status": "cleared", "executable": True, "review_decision_ref": review(gappr, ref="r7")["decision_ref"]}
        v("n14", "v0.3 (Oga): a reviewed, executable approve and a deny for the same gated tool call in one set", [
            {"record": record(gdeny, free), "reveal": gdeny, "review": None},
            {"record": record(gappr, gok), "reveal": gappr, "review": review(gappr, ref="r7")}], "reject", "conflicting_choice")
        other_q = dict(call, salt="e3" * 32, question="Notify the account owner?", choice="deny")
        v("p9", "v0.3: two different questions on the same context, different choices, are two decisions", [
            {"record": record(appr, free), "reveal": appr, "review": None},
            {"record": record(other_q, free), "reveal": other_q, "review": None}], "accept")
    if V4:
        # v0.4: decider-scoped slots. The decider signs one claim per request_id with its own BIP-340 key; the slot is
        # sha256(tag | decider_pubkey | request_id), whichever account pays. Oga's two-account case (2026-10-10) is n18.
        SK1 = hashlib.sha256(b"invinoveritas decision-receipt test decider 1").digest()
        SK2 = hashlib.sha256(b"invinoveritas decision-receipt test decider 2").digest()
        TAG, SCHEMA, T = "invinoveritas.decision_receipt.slot.decider.v1", "invinoveritas.decision_claim.v1", 1791600000
        dctx = sha("tool call: delete branch release-2026-10 | call_id=call_42")
        d4 = {"question": "Allow this tool call?", "options": ["approve", "deny"], "context_sha256": dctx,
              "irreversible_options": []}
        dA = dict(d4, salt="b1" * 32, choice="approve")
        dD = dict(d4, salt="b2" * 32, choice="deny")
        dA2 = dict(d4, salt="b3" * 32, choice="approve")
        free = {"status": "not_gated", "executable": True}

        def claim_for(rec, pk, slot, at=T):
            return {"schema": SCHEMA, "decider_pubkey": pk, "request_slot": slot,
                    **{k: rec[k] for k in ("question_commitment", "options_commitment", "choice_commitment",
                                           "context_commitment", "gate_policy_commitment")}, "claimed_at": at}

        def dec(rv, sk, rid, reveal_rid=None, sign_with=None, claim_rec=None):
            rec = record(rv, free)
            pk = bip340.pubkey(sk).hex()
            slot = sha(f"{TAG}|{pk}|{rid}")
            cl = claim_for(claim_rec or rec, pk, slot)
            sig = bip340.sign(sign_with or sk, hashlib.sha256(jcs(cl).encode("utf-8")).digest()).hex()
            rec.update(slot_scope="decider", decider_pubkey=pk, request_slot=slot, decider_claim=cl, decider_sig=sig)
            return {"record": rec, "reveal": dict(rv, request_id=reveal_rid or rid), "review": None}

        def acct(rv, slot_hex):
            rec = dict(record(rv, free), slot_scope="account", request_slot=slot_hex)
            return {"record": rec, "reveal": dict(rv, request_id="call_42"), "review": None}

        v("p10", "v0.4: decider-scoped receipt, claim signed by the decider key, slot derived from decider_pubkey and request_id",
          [dec(dA, SK1, "call_42")], "accept")
        v("n15", "v0.4: decider claim signed by a different key than decider_pubkey", [dec(dA, SK1, "call_42", sign_with=SK2)],
          "reject", "decider_sig_invalid")
        v("n16", "v0.4: request_slot derived from another request_id than the revealed one",
          [dec(dA, SK1, "call_43", reveal_rid="call_42")], "reject", "slot_mismatch")
        v("n17", "v0.4: the signed claim commits to another choice than the record (deny claim, approve record)",
          [dec(dA, SK1, "call_42", claim_rec=record(dD, free))], "reject", "claim_mismatch")
        v("n18", "v0.4 (Oga's two-account case): approve and deny for one request_id under one decider key, paid from two accounts",
          [dec(dA, SK1, "call_42"), dec(dD, SK1, "call_42")], "reject", "decider_equivocation")
        v("n19", "v0.4: two signed claims for one request_id with the same choice and different salts (one claim per request_id)",
          [dec(dA, SK1, "call_42"), dec(dA2, SK1, "call_42")], "reject", "decider_equivocation")
        v("p11", "v0.4: two receipts under one decider key for two request_ids, same choice", [
            dec(dA, SK1, "call_42"), dec(dA2, SK1, "call_44")], "accept")
        v("p12", "v0.4 (Oga's two-account case, account-scoped): approve receipt from account A; its slot looks unique",
          [acct(dA, "a" * 64)], "accept")
        v("p13", "v0.4 (Oga's two-account case, account-scoped): deny receipt for the same request_id from account B; a different "
                 "slot, also unique, and nothing public links it to p12", [acct(dD, "c" * 64)], "accept")
        v("n20", "v0.4: a slot_scope this suite does not define", [
            {"record": dict(record(dA, free), slot_scope="global", request_slot="e" * 64), "reveal": dA, "review": None}],
          "reject", "slot_scope_unknown")
        v("n21", "v0.4: slot_scope decider without a decider signature", [
            {"record": dict(record(dA, free), slot_scope="decider", request_slot="e" * 64), "reveal": dict(dA, request_id="call_42"),
             "review": None}], "reject", "decider_binding_missing")
    suite = "decision-record-v0.4" if V4 else "decision-record-v0.3" if "--v03" in sys.argv else "decision-record-v0.2" if "--v02" in sys.argv else "decision-record-v0"
    json.dump({"suite": suite, "commitment": "sha256(salt + '|' + value)",
               "review_tool": "decision_receipt", "vectors": V}, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
