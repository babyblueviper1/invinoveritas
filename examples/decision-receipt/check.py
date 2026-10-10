#!/usr/bin/env python3
"""Decision-record conformance checker, standard library only, written from SPEC.md (not from the service).

    python3 check.py vectors.json          # exit 0 iff every vector's verdict and reject_reason match
"""
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bip340  # noqa: E402  (stdlib BIP-340, in this directory)

APPROVING = ("approve", "approve_with_concerns")
CLAIM_SCHEMA = "invinoveritas.decision_claim.v1"                     # v0.4: what a decider signs
DECIDER_SLOT_TAG = "invinoveritas.decision_receipt.slot.decider.v1"
CLAIM_FIELDS = ("question_commitment", "options_commitment", "choice_commitment", "context_commitment",
                "gate_policy_commitment")
HEX64, HEX128 = re.compile(r"^[0-9a-f]{64}$"), re.compile(r"^[0-9a-f]{128}$")


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def jcs(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def decider_problem(rec, rv):
    """v0.4: None if a decider-scoped record's binding holds, else the reject reason."""
    pk, slot, claim, sig = rec.get("decider_pubkey"), rec.get("request_slot"), rec.get("decider_claim"), rec.get("decider_sig")
    if not (isinstance(pk, str) and HEX64.match(pk) and isinstance(slot, str) and isinstance(claim, dict)
            and isinstance(sig, str) and HEX128.match(sig)):
        return "decider_binding_missing"
    rid = rv.get("request_id")
    if not isinstance(rid, str) or sha(f"{DECIDER_SLOT_TAG}|{pk}|{rid}") != slot:
        return "slot_mismatch"
    at = claim.get("claimed_at")
    want = {"schema": CLAIM_SCHEMA, "decider_pubkey": pk, "request_slot": slot,
            **{k: rec.get(k) for k in CLAIM_FIELDS}, "claimed_at": at}
    if isinstance(at, bool) or not isinstance(at, int) or claim != want:
        return "claim_mismatch"
    if not bip340.verify(bytes.fromhex(pk), hashlib.sha256(jcs(claim).encode("utf-8")).digest(), bytes.fromhex(sig)):
        return "decider_sig_invalid"
    return None


def check_set(items):
    """(verdict, reason) for an ordered set of {record, reveal, review} items."""
    used = set()
    chosen = {}                                               # v0.3: one choice per decision within a revealed set
    claims = {}                                               # v0.4: one signed claim per (decider, request slot)
    for it in items:
        rec, rv, review = it["record"], it["reveal"], it.get("review")
        c = lambda v: sha(f"{rv['salt']}|{v}")
        opened = {"question_commitment": c(rv["question"]), "options_commitment": c(jcs(rv["options"])),
                  "choice_commitment": c(rv["choice"]), "context_commitment": c(rv["context_sha256"]),
                  "gate_policy_commitment": c(jcs(sorted(rv["irreversible_options"])))}
        policy = rv.get("accepted_review_issuers")           # v0.2: the deployer's committed list of acceptable review issuers
        if "review_issuers_commitment" in rec or policy is not None:
            if policy is None or not isinstance(policy, list):
                return "reject", "commitment_mismatch"
            opened["review_issuers_commitment"] = c(jcs(sorted(policy)))
        if any(rec.get(k) != v for k, v in opened.items()):
            return "reject", "commitment_mismatch"
        if rv["choice"] not in rv["options"]:
            return "reject", "choice_not_in_options"
        gated = rv["choice"] in rv["irreversible_options"]
        if rec.get("gated") is not gated:
            return "reject", "gated_flag_mismatch"
        scope = rec.get("slot_scope")
        if scope == "decider":
            why = decider_problem(rec, rv)
            if why:
                return "reject", why
            if claims.setdefault((rec["decider_pubkey"], rec["request_slot"]), jcs(rec["decider_claim"])) != jcs(rec["decider_claim"]):
                return "reject", "decider_equivocation"
        elif scope not in (None, "account"):
            return "reject", "slot_scope_unknown"
        key = (rv["context_sha256"], rv["question"], jcs(rv["options"]))  # the same decision, whatever the salt
        if chosen.setdefault(key, rv["choice"]) != rv["choice"]:
            return "reject", "conflicting_choice"
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
        if policy is not None and review.get("issuer_pubkey") not in policy:      # v0.2; absent policy = v0 (any issuer)
            return "reject", "review_issuer_not_permitted"
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
