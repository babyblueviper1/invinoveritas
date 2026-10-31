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


import mpt  # noqa: E402  (stdlib trie builder; the checker only verifies)


def build_trie(kv: dict, secure: bool = True):
    root, proof = mpt.build_trie(kv, secure)
    return root, None, proof


def proven_owners_root(account, owners, threshold, block, extra=None, modules=()):
    """A self-consistent synthetic chain state: the Safe's storage (owners linked list at slot 2, threshold at slot 4, modules
    linked list at slot 1, plus `extra` {slot key: value}), its account in a state trie, a header committing to that stateRoot
    at `block`; returns the owners@block trust root with proofs (the proofs cover every slot written)."""
    word = lambda n: n.to_bytes(32, "big")
    chain = [C.SENTINEL] + owners + [C.SENTINEL]
    st = {W.keccak256(word(int(a, 16)) + word(C.SAFE_OWNERS_SLOT)): rlp.encode(int(b, 16)) for a, b in zip(chain, chain[1:])}
    mchain = [C.SENTINEL] + list(modules) + [C.SENTINEL]
    st.update({W.keccak256(word(int(a, 16)) + word(C.SAFE_MODULES_SLOT)): rlp.encode(int(b, 16)) for a, b in zip(mchain, mchain[1:])})
    st[word(C.SAFE_THRESHOLD_SLOT)] = rlp.encode(threshold)
    st.update({k: rlp.encode(v) for k, v in (extra or {}).items()})
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


EXEC_BLOCK = 23000000


def owners_root(block=EXEC_BLOCK):
    return proven_owners_root(SAFE, [a.address.lower() for a in OWNERS], 2, block)


def pin_records(mode, approvers=None, pin=None, account=SAFE, chain_id=1):
    """Storage records that pin `pin` (Echo, PR #1 review 2026-10-31, option a): a Safe message (signedMessages[getMessageHash(abi.encode(pin))]
    = 1, slot 7) or owner approvals (approvedHashes[owner][pin] = 1, slot 8)."""
    word = lambda n: n.to_bytes(32, "big")
    if mode == "safe_message":
        return {W.keccak256(C.safe_message_hash(chain_id, account, pin) + word(C.SAFE_SIGNED_MESSAGES_SLOT)): 1}
    return {W.keccak256(pin + W.keccak256(word(int(a, 16)) + word(C.SAFE_APPROVED_HASHES_SLOT))): 1 for a in approvers}


def reviewer_root(mode="safe_message", approvers=None, modules=(), state_block=EXEC_BLOCK - 1, pin_list_hash=None, pin_account=SAFE,
                  pin_chain=1, record=True, auth=None):
    """reviewer-list@commitment whose pin is RECORDED ON-CHAIN in the state of `state_block`. The returned "_parent" is the
    hash of that state's header: the execution header must carry it as parentHash (the vector's chain is built with it)."""
    lst = {"reviewers": [a.address.lower() for a in REVIEWERS], "threshold": 2}
    lh = C._h(W.keccak256(W.jcs(lst)))
    pin = C.reviewer_list_pin(pin_chain, pin_account, pin_list_hash or lh)
    appr = [a.address.lower() for a in (approvers if approvers is not None else OWNERS[:2])]
    extra = pin_records(mode, appr, pin) if record else {}
    st = proven_owners_root(SAFE, [a.address.lower() for a in OWNERS], 2, state_block, extra=extra, modules=modules)
    st.pop("kind")
    tr = {"kind": "reviewer-list@commitment", "commitment": {"content_hash": lh}, "list": lst,
          "authorization": auth if auth is not None else {"mode": mode, "state": st}, "_parent": st["block_hash"]}
    return tr


def with_parent(tr):
    """(trust root without the generator's helper key, parent hash for the execution header)."""
    tr = copy.deepcopy(tr); return tr, tr.pop("_parent", None)


def block_for(tx_raw: bytes, receipt_raw: bytes, block=EXEC_BLOCK, index=1, prove=None, parent=None):
    """A synthetic block holding the transaction at `index` among two others, with its transaction and receipt tries, and a
    header committing to both roots. Returns the `execution` evidence (header + both inclusion proofs)."""
    filler_tx = lambda n: rlp.encode([n, 10**9, 21000, bytes.fromhex(PAYEE[2:]), 1, b""]) + b""   # legacy shape (unsigned filler)
    filler_rc = lambda n: b"\x02" + rlp.encode([1, 21000 * (n + 1), b"\x00" * 256, []])
    txs = {i: (tx_raw if i == index else filler_tx(i)) for i in range(3)}
    rcs = {i: (receipt_raw if i == index else filler_rc(i)) for i in range(3)}
    troot, tproof = mpt.build_trie({rlp.encode(i): v for i, v in txs.items()}, secure=False)
    rroot, rproof = mpt.build_trie({rlp.encode(i): v for i, v in rcs.items()}, secure=False)
    hdr = rlp.encode([C._hx(parent) if parent else b"\x11" * 32, W.keccak256(rlp.encode([])), b"\x22" * 20, b"\x66" * 32, troot, rroot, b"\x00" * 256, 0, block,
                      30000000, 0, TS, b"", b"\x55" * 32, b"\x00" * 8])
    k = rlp.encode(index if prove is None else prove)   # prove: the index whose inclusion is proven (a control for another tx)
    return {"block": block, "block_hash": C._h(W.keccak256(hdr)), "header_rlp": C._h(hdr), "tx_index": index if prove is None else prove,
            "tx_proof": [C._h(n) for n in tproof(k)], "receipt_proof": [C._h(n) for n in rproof(k)]}


def chain_for(info, digest: bytes, safe_signers, executed=True, event="success", tx_fields=None, nonce=None, layout="1.3.0", status=None, logs=None, parent=None):
    f = dict(info["fields"])
    f.update(tx_fields or {})
    sigs = b"".join(bytes.fromhex(sign(a, digest)[2:]) for a in safe_signers)
    inp = C.EXEC_TX + abi(["address", "uint256", "bytes", "uint8", "uint256", "uint256", "uint256", "address", "address", "bytes"],
                          [f["to"], f["value"], f["data"], f["operation"], 0, 0, 0, W.ZERO, W.ZERO, sigs])
    topic = C.EV_SUCCESS if event == "success" else C.EV_FAILURE
    lg = ([{"address": SAFE, "topics": [topic, "0x" + digest.hex()], "data": "0x" + "00" * 32}] if layout == "1.4.1" else
          [{"address": SAFE, "topics": [topic], "data": "0x" + digest.hex() + "00" * 32}]) if executed else []
    lg = lg if logs is None else logs
    st = (1 if executed else 0) if status is None else status
    rc = {"status": st, "blockNumber": EXEC_BLOCK, "logs": lg}
    return seal({"owners": [a.address.lower() for a in OWNERS], "threshold": 2, "nonce_at_execution": nonce or info["fields"]["nonce"],
                 "tx": {"to": SAFE, "input": "0x" + inp.hex()}, "receipt": rc}, parent=parent)


def seal(ch, prove=None, parent=None):
    """Make the chain evidence authenticated and consistent with ch["tx"] / ch["receipt"] as they now stand: the EIP-1559
    transaction carrying that call (its signature is not part of any v0 check), its typed receipt, both proven in a block."""
    tx, rc = ch["tx"], ch["receipt"]
    tx_raw = b"\x02" + rlp.encode([1, 7, 10**9, 3 * 10**10, 300000, bytes.fromhex(tx["to"][2:]), 0, bytes.fromhex(tx["input"][2:]), [], 1, 1, 1])
    rc_raw = b"\x02" + rlp.encode([rc["status"], 150000, b"\x00" * 256,
                                   [[bytes.fromhex(l["address"][2:]), [bytes.fromhex(t[2:]) for t in l["topics"]], bytes.fromhex(l["data"][2:])] for l in rc["logs"]]])
    tx["hash"] = rc["transactionHash"] = C._h(W.keccak256(tx_raw))
    ch["execution"] = block_for(tx_raw, rc_raw, prove=prove, parent=parent)
    return ch


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
    def rlv(name, tr, appr, expect, extra=None):
        """a reviewer-list vector: the execution header's parentHash is the pin state's header hash (option a)"""
        t, par = with_parent(tr)
        add(name, {"flow": fl, "review": {"trust_root": t, "approvals": approvals(fl, appr)}, "chain": chain_for(info, dg, two, parent=par)}, expect, extra)
    # positive: a content-addressed reviewer list, separate from the signers -> independent review. Its pin is RECORDED ON-CHAIN
    # in the parent state (Echo, PR #1 review 2026-10-31, option a): as a Safe message (no module enabled), and as owner approvals
    rlv("pos_reviewer_list_content_addressed", reviewer_root(), REVIEWERS, P4, {"reviewed.independent_review": True})
    rlv("pos_reviewer_list_owner_approvals", reviewer_root(mode="owner_approvals"), REVIEWERS, P4, {"reviewed.independent_review": True})
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
    rlv("neg04a_list_not_committed", loose, REVIEWERS, {**P4, "reviewed": "NOT_ESTABLISHED"})
    tamper = reviewer_root(); tamper["list"] = {"reviewers": [REVIEWERS[0].address.lower(), OUTSIDER.address.lower()], "threshold": 2}
    rlv("neg04a2_list_content_hash_mismatch", tamper, [REVIEWERS[0], OUTSIDER], {**P4, "reviewed": "NOT_ESTABLISHED"})
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
    ch9 = chain_for(info, dg, two); ch9.pop("receipt"); ch9.pop("execution")
    add("neg09_no_receipt", {"flow": fl, "review": {"trust_root": owners_root(), "approvals": approvals(fl, two)}, "chain": ch9},
        {**P4, "executed": "NOT_ESTABLISHED"})
    # an intent outside v0 (an unknown member) is refused, never encoded approximately
    xi = dict(intent_transfer()); xi["memo"] = "x"
    ih = W.intent_hash(xi)
    flx = {"intent": xi, "encoder_spec_cid": CID, "payload": fl["payload"],
           "claimed": {**fl["claimed"], "intentHash": C._h(ih), "encoderPipelineHash": C._h(W.encoder_pipeline_hash(CID, ih))}}
    add("neg_intent_unknown_member", {"flow": flx}, {"encoded": "FAIL", "reviewed": "NOT_ESTABLISHED", "signed": "NOT_ESTABLISHED", "executed": "NOT_ESTABLISHED"})
    # ---- Pavlo (WG 5962) + Echo (PR #1 review 2026-10-31, option a): trust-root AUTHORITY, and a pin RECORDED ON-CHAIN before the execution block.
    # Each is reviewed: NOT_ESTABLISHED, never PASS.
    NE4 = {**P4, "reviewed": "NOT_ESTABLISHED"}
    nolist = reviewer_root(); nolist.pop("authorization")
    rlv("neg04c_list_without_authorization", nolist, REVIEWERS, NE4)
    # the backdating case: off-chain owner signatures on a pin that STATES an earlier block, no on-chain record
    lst = {"reviewers": [a.address.lower() for a in REVIEWERS], "threshold": 2}
    stated = {"account": SAFE, "listHash": C._h(W.keccak256(W.jcs(lst))), "pinnedAtBlock": EXEC_BLOCK - 100}
    back = {"stated": stated, "signatures": [sign(a, W.keccak256(W.jcs(stated))) for a in OWNERS[:2]]}
    rlv("neg04l_backdated_signatures_no_onchain_record", reviewer_root(auth=back), REVIEWERS, NE4, {"reviewed.reason": "reviewer_list_prior_binding_unproven"})
    # the pin recorded in the execution block itself: absent from the E-1 state
    rlv("neg04f_pin_recorded_in_the_execution_block", reviewer_root(record=False), REVIEWERS, NE4, {"reviewed.reason": "reviewer_list_pin_not_recorded"})
    # the pin proven against a header that is not block E's parent (a later state that does hold the record)
    t_late, _ = with_parent(reviewer_root(state_block=EXEC_BLOCK + 5))
    add("neg04m_pin_state_not_the_execution_parent", {"flow": fl, "review": {"trust_root": t_late, "approvals": approvals(fl, REVIEWERS)},
        "chain": chain_for(info, dg, two)}, NE4, {"reviewed.reason": "reviewer_list_pin_not_in_the_parent_state"})
    # a valid on-chain pin, but no execution evidence: "before the execution block" cannot be established
    t_ne, _ = with_parent(reviewer_root())
    add("neg04r_pin_without_execution_evidence", {"flow": fl, "review": {"trust_root": t_ne, "approvals": approvals(fl, REVIEWERS)}},
        {"encoded": "PASS", "reviewed": "NOT_ESTABLISHED", "signed": "NOT_ESTABLISHED", "executed": "NOT_ESTABLISHED"})
    # a Safe-message record with a module enabled (a module executes without owner signatures)
    rlv("neg04n_safe_message_with_module_enabled", reviewer_root(modules=[ATTACKER]), REVIEWERS, NE4, {"reviewed.reason": "reviewer_list_pin_module_possible"})
    # owner approvals below the proven threshold, and approvals from a non-owner
    rlv("neg04e_owner_approvals_below_threshold", reviewer_root(mode="owner_approvals", approvers=[OWNERS[0]]), REVIEWERS, NE4)
    rlv("neg04d_owner_approvals_from_a_non_owner", reviewer_root(mode="owner_approvals", approvers=[OWNERS[0], OUTSIDER]), REVIEWERS, NE4)
    # a pin for another list, another account, another chain
    rlv("neg04o_pin_for_another_list", reviewer_root(pin_list_hash=C._h(W.keccak256(b"another list"))), REVIEWERS, NE4)
    rlv("neg04p_pin_for_another_account", reviewer_root(pin_account=ATTACKER), REVIEWERS, NE4)
    rlv("neg04q_pin_for_another_chain", reviewer_root(pin_chain=10), REVIEWERS, NE4)
    # the pin state supplied without proofs (an owner set and a record stated, not proven)
    rlv("neg04k_pin_state_not_proven", reviewer_root(auth={"mode": "safe_message", "state": {"block": EXEC_BLOCK - 1,
        "owners": [a.address.lower() for a in OWNERS], "threshold": 2}}), REVIEWERS, NE4)
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
    cto = chain_for(info, dg, two); cto["tx"]["to"] = ATTACKER; seal(cto)
    add("neg07f_tx_sent_to_another_address", {"flow": fl, "chain": cto}, {**P4, "reviewed": "NOT_ESTABLISHED", "signed": "FAIL"})
    cnot = chain_for(info, dg, two); cnot["tx"]["input"] = "0xa9059cbb" + cnot["tx"]["input"][10:]; seal(cnot)
    add("neg07g_not_execTransaction", {"flow": fl, "chain": cnot}, {**P4, "reviewed": "NOT_ESTABLISHED", "signed": "FAIL"})
    cbad = chain_for(info, dg, two)
    raw = bytes.fromhex(cbad["tx"]["input"][2:]); sigs_at = len(raw) - ((-130) % 32) - 130
    i0 = raw.find(bytes.fromhex(sign(two[0], dg)[2:]))
    raw = raw[:i0 + 64] + b"\x00" + raw[i0 + 65:]   # v = 0: a contract signature, outside v0
    cbad["tx"]["input"] = "0x" + raw.hex(); seal(cbad)
    add("neg07h_signature_outside_v0", {"flow": fl, "chain": cbad}, {**P4, "reviewed": "NOT_ESTABLISHED", "signed": "FAIL"})
    cst = chain_for(info, dg, two, status=0)
    add("neg08c_status_zero_with_success_log", {"flow": fl, "chain": cst}, {**P4, "reviewed": "NOT_ESTABLISHED", "executed": "FAIL"})
    cno = chain_for(info, dg, two, logs=[])
    add("neg08d_success_status_no_safe_event", {"flow": fl, "chain": cno}, {**P4, "reviewed": "NOT_ESTABLISHED", "executed": "FAIL"})
    # ---- Echo/Pavlo (WG 5966-5967): executed is PASS only when authenticated
    P4R = {**P4, "reviewed": "NOT_ESTABLISHED"}
    c1 = chain_for(info, dg, two); c1["receipt"]["transactionHash"] = C._h(W.keccak256(b"another transaction"))
    add("neg10a_tx_hash_differs_from_receipt", {"flow": fl, "chain": c1}, {**P4R, "executed": "NOT_ESTABLISHED"})
    c2 = chain_for(info, dg, two); c2.pop("execution"); c2["receipt"]["blockHash"] = C._h(W.keccak256(b"an arbitrary block"))
    add("neg10b_receipt_without_inclusion_proof", {"flow": fl, "chain": c2}, {**P4R, "executed": "NOT_ESTABLISHED"})
    c3 = chain_for(info, dg, two); c3.pop("tx")
    add("neg10c_tx_removed_success_receipt_kept", {"flow": fl, "chain": c3}, {**P4R, "signed": "NOT_ESTABLISHED", "executed": "NOT_ESTABLISHED"})
    c4 = chain_for(info, dg, two); c4["execution"]["block_hash"] = C._h(W.keccak256(b"an arbitrary block"))
    add("neg10d_header_not_the_block_hash", {"flow": fl, "chain": c4}, {**P4R, "executed": "NOT_ESTABLISHED"})
    c5 = chain_for(info, dg, two); c5["execution"]["block"] = EXEC_BLOCK + 1
    add("neg10e_header_number_differs", {"flow": fl, "chain": c5}, {**P4R, "executed": "NOT_ESTABLISHED"})
    c6 = chain_for(info, dg, two); c6["execution"]["receipt_proof"] = c6["execution"]["receipt_proof"][:-1]
    add("neg10f_receipt_proof_node_removed", {"flow": fl, "chain": c6}, {**P4R, "executed": "NOT_ESTABLISHED"})
    c7 = seal(chain_for(info, dg, two), prove=0)   # a valid inclusion proof, but of another transaction in the same block
    add("neg10g_proof_of_another_transaction", {"flow": fl, "chain": c7}, {**P4R, "executed": "NOT_ESTABLISHED"})
    c8 = chain_for(info, dg, two); other = seal(chain_for(info, dg, two, tx_fields={"value": 1}))
    c8["execution"] = other["execution"]   # a proven, successful execution of a DIFFERENT call to the same Safe,
    c8["tx"].pop("hash"); c8["receipt"].pop("transactionHash")   # supplied without hashes, so only the bytes can bind it
    add("neg10h_proven_tx_is_not_the_checked_one", {"flow": fl, "chain": c8}, {**P4R, "executed": "NOT_ESTABLISHED"})
    return V


def main():
    # cross-check the stdlib primitives first (the checker must agree with an independent implementation)
    for n in (0, 1, 135, 136, 137, 500):
        b = os.urandom(n)
        assert W.keccak256(b) == keccak(b), "keccak"
    # option (a) primitives (Echo PR #1 review 2026-10-31): the pin, the Safe message hash and both storage-slot formulas, against eth_abi
    lh = "0x" + os.urandom(32).hex(); own = OWNERS[0].address.lower()
    pin = keccak(abi(["bytes32", "uint256", "address", "bytes32"], [keccak(text=C.REVIEWER_LIST_PIN_TYPE), 1, SAFE, bytes.fromhex(lh[2:])]))
    assert C.reviewer_list_pin(1, SAFE, lh) == pin, "reviewer_list_pin"
    dom = keccak(abi(["bytes32", "uint256", "address"], [keccak(text="EIP712Domain(uint256 chainId,address verifyingContract)"), 1, SAFE]))
    mh = keccak(b"\x19\x01" + dom + keccak(abi(["bytes32", "bytes32"], [keccak(text="SafeMessage(bytes message)"), keccak(pin)])))
    assert C.safe_message_hash(1, SAFE, pin) == mh, "safe_message_hash"
    assert list(pin_records("safe_message", pin=pin)) == [keccak(abi(["bytes32", "uint256"], [mh, 7]))], "signedMessages slot"
    assert list(pin_records("owner_approvals", [own], pin)) == [keccak(abi(["bytes32", "bytes32"], [pin, keccak(abi(["address", "uint256"], [own, 8]))]))], "approvedHashes slot"
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
