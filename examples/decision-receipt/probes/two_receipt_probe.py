# Two receipts for one decision (decision-receipt). Found 2026-10-10 by Toshikatsu Oga (HORIZON SHIELD / NENRIN). MIT, use as is.
# Run: python3 -I two_receipt_probe.py <path to examples/decision-receipt>
# Before v0.3 (c39feb6): accept, accept, accept. From v0.3 (deda27ff): accept, accept, reject conflicting_choice. Shared public fields: none.
import hashlib, json, sys, importlib.util
spec = importlib.util.spec_from_file_location("chk", sys.argv[1] + "/check.py"); chk = importlib.util.module_from_spec(spec); spec.loader.exec_module(chk)
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
jcs = lambda v: json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
CTX = sha("rm -rf /srv/build/cache | tool_call_id=call_7 | nonce=" + "11" * 32)
Q, OPTS = "hermes-agent approval: allow this dangerous tool call?", ["approve", "deny"]
c = lambda salt, v: sha(f"{salt}|{v}")
rec = lambda salt, choice: {"record": {"question_commitment": c(salt, Q), "options_commitment": c(salt, jcs(OPTS)), "choice_commitment": c(salt, choice), "context_commitment": c(salt, CTX), "gate_policy_commitment": c(salt, jcs([])), "gated": False, "gate": {"status": "not_gated", "executable": True}}, "reveal": {"salt": salt, "question": Q, "options": OPTS, "choice": choice, "context_sha256": CTX, "irreversible_options": []}, "review": None}
a, d = rec("a1" * 32, "approve"), rec("d2" * 32, "deny")
print("approve alone:", chk.check_set([a]))
print("deny alone:   ", chk.check_set([d]))
print("both as one set:", chk.check_set([a, d]))
print("public fields shared by the two records:", sorted(k for k in a["record"] if a["record"][k] == d["record"][k] and k.endswith("commitment")))
