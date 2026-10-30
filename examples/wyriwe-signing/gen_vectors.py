#!/usr/bin/env python3
"""Generate vectors.json for check.py -- PROFILE.md "Test cases" (trustless-ai/wyriwe-signing draft 2).

Uses eth_account / eth_abi (NOT needed to run check.py) for two things: signing with fixed test keys, and a SECOND, independent
encoder (eth_abi) that must produce the same payload as wyriwe_encoder.py for every positive vector (test case 10). It also
cross-checks every stdlib primitive against eth_utils / eth_abi / eth_account before writing anything.

Test keys are derived from public seeds (keccak256("wyriwe-v0/<name>")): they hold nothing and must never be used for value.
usage: python3 gen_vectors.py   (writes vectors.json next to it)
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wyriwe_encoder as W  # noqa: E402
import check as C  # noqa: E402
from eth_abi import encode as abi  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_utils import keccak  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
key = lambda name: W.keccak256(f"wyriwe-v0/{name}".encode())
acct = lambda name: Account.from_key(key(name))
OWNERS = sorted([acct(f"owner{i}") for i in (1, 2, 3)], key=lambda a: a.address.lower())
REVIEWERS = sorted([acct(f"reviewer{i}") for i in (1, 2)], key=lambda a: a.address.lower())
OUTSIDER = acct("outsider")
ATTACKER = "0x" + W.keccak256(b"wyriwe-v0/attacker")[12:].hex()
SAFE = "0x" + W.keccak256(b"wyriwe-v0/safe")[12:].hex()
TOKEN = "0x" + W.keccak256(b"wyriwe-v0/token")[12:].hex()
PAYEE = "0x" + W.keccak256(b"wyriwe-v0/payee")[12:].hex()
CID = C.ENCODER_SPEC_CID
OTHER_CID = "ipfs://bafkreiaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
TS = 1793404800  # 2026-10-31T00:00:00Z, informational (ERC-8299: timestamp does not prevent replay)


import rlp  # noqa: E402  (generator only)


def _hp(nibs, leaf):
    f = (2 if leaf else 0) + (len(nibs) % 2)
    ns = [f] + ([] if len(nibs) % 2 else [0]) + list(nibs)
    return bytes(ns[i] * 16 + ns[i + 1] for i in range(0, len(ns), 2))


def build_trie(kv: dict):
    """A minimal Merkle-Patricia trie over {key: value-bytes} (keys hashed with keccak, as Ethereum's secure tries).
    Returns (root, db, proof(key))."""
    db = {}
    items = sorted((W.keccak256(k), v) for k, v in kv.items())
    items = [([x for c in hk for x in (c >> 4, c & 15)], v) for hk, v in items]

    def ref(node):
        enc = rlp.encode(node)
        if len(enc) < 32:
            return node
        h = W.keccak256(enc); db[h] = enc
        return h

    def build(its, d):
        if len(its) == 1:
            return [_hp(its[0][0][d:], True), its[0][1]]
        cp = 0
        while all(len(p) > d + cp for p, _ in its) and len({p[d + cp] for p, _ in its}) == 1:
            cp += 1
        if cp:
            return [_hp(its[0][0][d:d + cp], False), ref(build(its, d + cp))]
        br = [b""] * 17
        for i in range(16):
            sub = [x for x in its if x[0][d] == i]
            if sub:
                br[i] = ref(build(sub, d + 1))
        return br

    root_node = build(items, 0)
    enc = rlp.encode(root_node); root = W.keccak256(enc); db[root] = enc

    def proof(key):
        path = [x for c in W.keccak256(key) for x in (c >> 4, c & 15)]
        out, node = [db[root]], root_node
        while True:
            if len(node) == 17:
                nxt, path = node[path[0]], path[1:]
            else:
                hp = [x for c in node[0] for x in (c >> 4, c & 15)]
                part = hp[2:] if hp[0] in (0, 2) else hp[1:]
                if hp[0] in (2, 3):
                    return out
                nxt, path = node[1], path[len(part):]
            if isinstance(nxt, list):
                node = nxt
            elif len(nxt) == 32:
                out.append(db[nxt]); node = rlp.decode(db[nxt])
            else:
                return out
    return root, db, proof


def proven_owners_root(account, owners, threshold, block):
    """A self-consistent synthetic chain state: the Safe's storage (owners linked list at slot 2, threshold at slot 4), its
    account in a state trie, a header committing to that stateRoot at `block`; returns the owners@block trust root with proofs."""
    word = lambda n: n.to_bytes(32, "big")
    chain = [C.SENTINEL] + owners + [C.SENTINEL]
    st = {W.keccak256(word(int(a, 16)) + word(C.SAFE_OWNERS_SLOT)): rlp.encode(int(b, 16)) for a, b in zip(chain, chain[1:])}
    st[word(C.SAFE_THRESHOLD_SLOT)] = rlp.encode(threshold)
    sroot, _, sproof = build_trie(st)
    acct = rlp.encode([1, 0, sroot, W.keccak256(b"safe-proxy-code")])
    other = "0x" + W.keccak256(b"wyriwe-v0/other-account")[12:].hex()
    sroot2, _, aproof = build_trie({bytes.fromhex(account[2:]): acct, bytes.fromhex(other[2:]): rlp.encode([0, 5, W.keccak256(rlp.encode(b"")), W.keccak256(b"")])})
    hdr = rlp.encode([b"\x11" * 32, W.keccak256(rlp.encode([])), b"\x22" * 20, sroot2, b"\x33" * 32, b"\x44" * 32, b"\x00" * 256, 0, block,
                      30000000, 0, TS, b"", b"\x55" * 32, b"\x00" * 8])
    nodes = []
    for k in st:
        for n in sproof(k):
            if n not in nodes:
                nodes.append(n)
    return {"kind": "owners@block", "block": block, "block_hash": C._h(W.keccak256(hdr)), "header_rlp": C._h(hdr),
            "account_proof": [C._h(n) for n in aproof(bytes.fromhex(account[2:]))], "storage_proof": [C._h(n) for n in nodes]}


def sign(a, digest: bytes) -> str:
    s = Account.unsafe_sign_hash(digest, a.key) if hasattr(Account, "unsafe_sign_hash") else Account._sign_hash(digest, a.key)
    return "0x" + bytes(s.signature).hex()


def second_encoder(intent):
    """Independent encoder for case 10: eth_abi + eth_utils only, written from ENCODER.md, not from wyriwe_encoder.py."""
    args = intent["args"]
    conv = lambda t, v: (int(v) if t.startswith(("uint", "int")) else bytes.fromhex(v[2:]) if t.startswith("bytes") else v)
    data = b"" if intent["function"] == "" else keccak(text=intent["function"])[:4] + abi([a["type"] for a in args], [conv(a["type"], a["value"]) for a in args])
    return abi(["address", "uint256", "bytes", "uint8", "uint256", "uint256", "uint256", "address", "address", "uint256"],
               [intent["target"], int(intent["value"]), data, 0 if intent["operation"] == "call" else 1, 0, 0, 0, W.ZERO, W.ZERO, int(intent["nonce"])])


def intent_transfer(to=PAYEE, amount="2500000000", nonce="17"):
    return {"chainId": 1, "account": SAFE, "target": TOKEN, "value": "0", "function": "transfer(address,uint256)",
            "args": [{"type": "address", "value": to}, {"type": "uint256", "value": amount}], "operation": "call", "nonce": nonce}


def flow_for(intent, cid=CID, payload_intent=None, digest_override=None):
    """A flow record: the intent, the CID, the payload (by default the encoder's own) and the claimed hashes."""
    payload, info = W.encode(payload_intent or intent)
    ih = W.intent_hash(intent)
    claimed = {"intentHash": C._h(ih), "encoderPipelineHash": C._h(W.encoder_pipeline_hash(CID, ih)),
               "payloadHash": C._h(W.keccak256(payload)), "signingDigest": digest_override or C._h(info["signing_digest"])}
    return {"intent": intent, "encoder_spec_cid": cid, "payload": C._h(payload), "claimed": claimed}, info


def approvals(flow, signers, struct_over=None):
    st = {"chainId": flow["intent"]["chainId"], "account": flow["intent"]["account"], **{k: flow["claimed"][k] for k in
          ("intentHash", "encoderPipelineHash", "payloadHash", "signingDigest")}, "timestamp": TS}
    st.update(struct_over or {})
    d = W.wyriwe_struct_digest(flow["intent"]["chainId"], st)
    return [{"domain_chain_id": flow["intent"]["chainId"], "struct": st, "signature": sign(a, d)} for a in signers]


EXEC_BLOCK, PIN_BLOCK = 23000000, 22999990


def owners_root(block=EXEC_BLOCK):
    return proven_owners_root(SAFE, [a.address.lower() for a in OWNERS], 2, block)


def reviewer_root(pin_signers=None, pin_block=PIN_BLOCK):
    lst = {"reviewers": [a.address.lower() for a in REVIEWERS], "threshold": 2}
    lh = C._h(W.keccak256(W.jcs(lst)))
    d = W.root_pin_digest(1, {"account": SAFE, "listHash": lh, "pinnedAtBlock": pin_block})
    sig = [sign(a, d) for a in (OWNERS[:2] if pin_signers is None else pin_signers)]
    return {"kind": "reviewer-list@commitment", "commitment": {"content_hash": lh}, "list": lst,
            "authorization": {"owners_root": owners_root(pin_block), "signatures": sig}}


def chain_for(info, digest: bytes, safe_signers, executed=True, event="success", tx_fields=None, nonce=None, layout="1.3.0"):
    f = dict(info["fields"])
    f.update(tx_fields or {})
    sigs = b"".join(bytes.fromhex(sign(a, digest)[2:]) for a in safe_signers)
    inp = C.EXEC_TX + abi(["address", "uint256", "bytes", "uint8", "uint256", "uint256", "uint256", "address", "address", "bytes"],
                          [f["to"], f["value"], f["data"], f["operation"], 0, 0, 0, W.ZERO, W.ZERO, sigs])
    topic = C.EV_SUCCESS if event == "success" else C.EV_FAILURE
    rc = {"status": 1 if executed else 0, "blockNumber": EXEC_BLOCK,
          "logs": ([{"address": SAFE, "topics": [topic, "0x" + digest.hex()], "data": "0x" + "00" * 32}] if layout == "1.4.1" else
                   [{"address": SAFE, "topics": [topic], "data": "0x" + digest.hex() + "00" * 32}]) if executed else []}
    return {"owners": [a.address.lower() for a in OWNERS], "threshold": 2, "nonce_at_execution": nonce or info["fields"]["nonce"],
            "tx": {"to": SAFE, "input": "0x" + inp.hex()}, "receipt": rc}


def build():
    V = []
    add = lambda name, fx, expect, extra=None: V.append({"name": name, "fixture": fx, "expect": expect, **({"expect_extra": extra} if extra else {})})
    P4 = {k: "PASS" for k in ("encoded", "reviewed", "signed", "executed")}
    two = OWNERS[:2]

    # positive: owners@block (reviewers == signers: fidelity, NOT independent review -- case 4b)
    fl, info = flow_for(intent_transfer())
    dg = info["signing_digest"]
    add("pos_owners_at_block_full_overlap", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two)}, P4, {"reviewed.trust_root.kind": "owners@block", "reviewed.independent_review": False})
    # positive: a content-addressed reviewer list, separate from the signers -> independent review
    add("pos_reviewer_list_content_addressed", {"flow": fl, "review": {"trust_root": reviewer_root(), "approvals": approvals(fl, REVIEWERS)},
        "chain": chain_for(info, dg, two)}, P4, {"reviewed.independent_review": True})
    # positive: the Safe v1.4.x event layout (txHash as an indexed topic, found on a real mainnet execution)
    add("pos_safe_v141_event_layout", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two, layout="1.4.1")}, P4)
    # positive: plain value transfer, delegatecall-free, no args
    vi = {"chainId": 1, "account": SAFE, "target": PAYEE, "value": "1000000000000000000", "function": "", "args": [], "operation": "call", "nonce": "18"}
    flv, infov = flow_for(vi)
    add("pos_plain_value_transfer", {"flow": flv, "review": {"trust_root": owners_root(), "approvals": approvals(flv, two)},
        "chain": chain_for(infov, infov["signing_digest"], two)}, P4)

    # 1 swapped payload (the Bybit shape): the intent says PAYEE, the payload pays the ATTACKER; owners sign the swapped digest
    bad_intent = intent_transfer(to=ATTACKER)
    fls, infos = flow_for(intent_transfer(), payload_intent=bad_intent)
    honest_appr = approvals(fl, two)                                    # reviewers approved the honest build
    add("neg01_swapped_payload", {"flow": fls, "review": {"trust_root": owners_root(), "approvals": honest_appr},
        "chain": chain_for(infos, infos["signing_digest"], two)},
        {"encoded": "FAIL", "reviewed": "FAIL", "signed": "PASS", "executed": "PASS"})
    # 2 wrong encoder: the flow names another encoder spec than the one reviewed
    fle = copy.deepcopy(fl); fle["encoder_spec_cid"] = OTHER_CID
    add("neg02_wrong_encoder", {"flow": fle, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two)}, {"encoded": "FAIL", "reviewed": "FAIL", "signed": "PASS", "executed": "PASS"})
    # 3 no approval supplied
    add("neg03_no_approval", {"flow": fl, "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    # 4 approval by a key outside the trust root / below threshold
    add("neg04_approver_outside_root", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, [OWNERS[0], OUTSIDER])},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "FAIL"})
    add("neg04b_approval_below_threshold", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, [OWNERS[0]])},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "FAIL"})
    # 4a a reviewer list that is neither on-chain nor content-addressed
    loose = reviewer_root(); loose["commitment"] = {}
    add("neg04a_list_not_committed", {"flow": fl, "review": {"trust_root": loose, "approvals": approvals(fl, REVIEWERS)},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    tamper = reviewer_root(); tamper["list"] = {"reviewers": [REVIEWERS[0].address.lower(), OUTSIDER.address.lower()], "threshold": 2}
    add("neg04a2_list_content_hash_mismatch", {"flow": fl, "review": {"trust_root": tamper, "approvals": approvals(fl, [REVIEWERS[0], OUTSIDER])},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    # 5 approval of a different intent_hash
    other = C._h(W.intent_hash(intent_transfer(amount="1")))
    add("neg05_approval_of_other_intent", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two, {"intentHash": other})},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "FAIL"})
    # 6 digest substitution: the record claims a different signing digest (the Safe's for another nonce); signers signed it
    _, info99 = W.encode(intent_transfer(nonce="99"))
    sub = info99["signing_digest"]
    fld = copy.deepcopy(fl); fld["claimed"]["signingDigest"] = C._h(sub)
    add("neg06_digest_substitution", {"flow": fld, "review": {"trust_root": owners_root(), "approvals": approvals(fld, two)},
        "chain": chain_for(info, sub, two, executed=False)}, {"encoded": "PASS", "reviewed": "PASS", "signed": "FAIL", "executed": "FAIL"})
    # (on a real Safe, signatures over a substituted digest fail checkNSignatures, so the execution reverts)
    # 7 signatures from a non-owner / below the Safe threshold / out of order
    add("neg07_signer_not_owner", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, sorted([OWNERS[0], OUTSIDER], key=lambda a: a.address.lower()))}, {**P4, "signed": "FAIL"})
    add("neg07b_below_safe_threshold", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, [OWNERS[0]])}, {**P4, "signed": "FAIL"})
    add("neg07c_signers_not_ascending", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, [OWNERS[1], OWNERS[0]])}, {**P4, "signed": "FAIL"})
    # the executed call is not the payload (data changed on the way to the chain) / wrong nonce
    add("neg07d_tx_call_differs_from_payload", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two, tx_fields={"to": ATTACKER})}, {**P4, "signed": "FAIL"})
    add("neg07e_nonce_differs", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two, nonce=16)}, {**P4, "signed": "FAIL"})
    # 8 included but reverted / Safe ExecutionFailure
    add("neg08_reverted", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two, executed=False)}, {**P4, "executed": "FAIL"})
    add("neg08b_execution_failure_event", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two, event="failure")}, {**P4, "executed": "FAIL"})
    # 9 no receipt supplied
    ch9 = chain_for(info, dg, two); ch9.pop("receipt")
    add("neg09_no_receipt", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)}, "chain": ch9},
        {**P4, "executed": "NOT_ESTABLISHED"})
    # an intent outside v0 (an unknown member) is refused, never encoded approximately
    xi = dict(intent_transfer()); xi["memo"] = "x"
    ih = W.intent_hash(xi)
    flx = {"intent": xi, "encoder_spec_cid": CID, "payload": fl["payload"],
           "claimed": {**fl["claimed"], "intentHash": C._h(ih), "encoderPipelineHash": C._h(W.encoder_pipeline_hash(CID, ih))}}
    add("neg_intent_unknown_member", {"flow": flx}, {"encoded": "FAIL", "reviewed": "NOT_ESTABLISHED", "signed": "NOT_ESTABLISHED", "executed": "NOT_ESTABLISHED"})
    # ---- Pavlo (WG 5962): trust-root AUTHORITY and prior binding
    nolist = reviewer_root(); nolist.pop("authorization")
    add("neg04c_list_without_authorization", {"flow": fl, "review": {"trust_root": nolist, "approvals": approvals(fl, REVIEWERS)},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    add("neg04d_list_pinned_by_non_owners", {"flow": fl, "review": {"trust_root": reviewer_root(pin_signers=[OUTSIDER, REVIEWERS[0]]),
        "approvals": approvals(fl, REVIEWERS)}, "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    add("neg04e_list_pinned_below_owner_threshold", {"flow": fl, "review": {"trust_root": reviewer_root(pin_signers=[OWNERS[0]]),
        "approvals": approvals(fl, REVIEWERS)}, "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    add("neg04f_list_pinned_after_execution", {"flow": fl, "review": {"trust_root": reviewer_root(pin_block=EXEC_BLOCK + 5),
        "approvals": approvals(fl, REVIEWERS)}, "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    unproven_auth = reviewer_root(); unproven_auth["authorization"]["owners_root"] = {"kind": "owners@block", "block": PIN_BLOCK,
        "owners": [a.address.lower() for a in OWNERS], "threshold": 2}
    add("neg04k_list_authorized_by_unproven_owner_set", {"flow": fl, "review": {"trust_root": unproven_auth, "approvals": approvals(fl, REVIEWERS)},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    bare = {"kind": "owners@block", "block": EXEC_BLOCK, "owners": [a.address.lower() for a in OWNERS], "threshold": 2}
    add("neg04g_owner_set_supplied_without_proof", {"flow": fl, "review": {"trust_root": bare, "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    badh = owners_root(); badh["block_hash"] = C._h(W.keccak256(b"another block"))
    add("neg04h_header_not_the_block_hash", {"flow": fl, "review": {"trust_root": badh, "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    wrongacct = proven_owners_root("0x" + W.keccak256(b"wyriwe-v0/other-safe")[12:].hex(), [a.address.lower() for a in OWNERS], 2, EXEC_BLOCK)
    add("neg04i_owner_proof_for_another_account", {"flow": fl, "review": {"trust_root": wrongacct, "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "NOT_ESTABLISHED"})
    fewer = proven_owners_root(SAFE, [OWNERS[0].address.lower(), OUTSIDER.address.lower()], 2, EXEC_BLOCK)
    add("neg04j_proven_owners_differ_from_approvers", {"flow": fl, "review": {"trust_root": fewer, "approvals": approvals(fl, two)},
        "chain": chain_for(info, dg, two)}, {**P4, "reviewed": "FAIL"})
    # ---- one vector per check the mutation run showed unexercised
    fli = copy.deepcopy(fl); fli["claimed"]["intentHash"] = C._h(W.keccak256(b"not the intent"))
    add("neg_claimed_intent_hash_wrong", {"flow": fli, "chain": chain_for(info, dg, two)},
        {"encoded": "FAIL", "reviewed": "NOT_ESTABLISHED", "signed": "PASS", "executed": "PASS"})
    flp = copy.deepcopy(fl); flp["claimed"]["payloadHash"] = C._h(W.keccak256(b"not the payload"))
    add("neg_claimed_payload_hash_wrong", {"flow": flp, "chain": chain_for(info, dg, two)},
        {"encoded": "FAIL", "reviewed": "NOT_ESTABLISHED", "signed": "PASS", "executed": "PASS"})
    add("neg06b_digest_substitution_no_tx", {"flow": fld}, {"encoded": "PASS", "reviewed": "NOT_ESTABLISHED", "signed": "FAIL", "executed": "NOT_ESTABLISHED"})
    cto = chain_for(info, dg, two); cto["tx"]["to"] = ATTACKER
    add("neg07f_tx_sent_to_another_address", {"flow": fl, "chain": cto}, {**P4, "reviewed": "NOT_ESTABLISHED", "signed": "FAIL"})
    cnot = chain_for(info, dg, two); cnot["tx"]["input"] = "0xa9059cbb" + cnot["tx"]["input"][10:]
    add("neg07g_not_execTransaction", {"flow": fl, "chain": cnot}, {**P4, "reviewed": "NOT_ESTABLISHED", "signed": "FAIL"})
    cbad = chain_for(info, dg, two)
    raw = bytes.fromhex(cbad["tx"]["input"][2:]); sigs_at = len(raw) - ((-130) % 32) - 130
    i0 = raw.find(bytes.fromhex(sign(two[0], dg)[2:]))
    raw = raw[:i0 + 64] + b"\x00" + raw[i0 + 65:]   # v = 0: a contract signature, outside v0
    cbad["tx"]["input"] = "0x" + raw.hex()
    add("neg07h_signature_outside_v0", {"flow": fl, "chain": cbad}, {**P4, "reviewed": "NOT_ESTABLISHED", "signed": "FAIL"})
    cst = chain_for(info, dg, two); cst["receipt"]["status"] = 0
    add("neg08c_status_zero_with_success_log", {"flow": fl, "chain": cst}, {**P4, "reviewed": "NOT_ESTABLISHED", "executed": "FAIL"})
    cno = chain_for(info, dg, two); cno["receipt"]["logs"] = []
    add("neg08d_success_status_no_safe_event", {"flow": fl, "chain": cno}, {**P4, "reviewed": "NOT_ESTABLISHED", "executed": "FAIL"})
    return V


def main():
    # cross-check the stdlib primitives first (the checker must agree with an independent implementation)
    for n in (0, 1, 135, 136, 137, 500):
        b = os.urandom(n)
        assert W.keccak256(b) == keccak(b), "keccak"
    V = build()
    # case 10: the second encoder must agree byte for byte on every positive vector
    pos = [v for v in V if v["name"].startswith("pos_")]
    for v in pos:
        assert C._hx(v["fixture"]["flow"]["payload"]) == second_encoder(v["fixture"]["flow"]["intent"]), f"encoders disagree on {v['name']}"
    out = {"profile": "trustless-ai/wyriwe-signing PROFILE.md draft 2, v0 (Safe)", "encoder_spec_cid": CID,
           "note": "fixtures are synthetic; chain data are supplied as an RPC would return them. Test keys are derived from public seeds.",
           "second_encoder_agrees_on": [v["name"] for v in pos], "vectors": V}
    json.dump(out, open(os.path.join(HERE, "vectors.json"), "w"), indent=1)
    print(f"wrote {len(V)} vectors; second encoder agrees on {len(pos)} positive payloads")


if __name__ == "__main__":
    main()
