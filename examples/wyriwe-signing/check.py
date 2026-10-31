#!/usr/bin/env python3
"""Outside recompute for the ERC-8299 signing-input profile, v0 (Safe) -- PROFILE.md section 9 (trustless-ai/wyriwe-signing).

Python standard library only. Given a flow (intent, encoder CID, payload, the claimed hashes), optional review approvals with
their trust root, and optional chain data (the Safe's owners and threshold at execution, the execTransaction call, its
receipt), it returns FOUR SEPARATE verdicts -- encoded, reviewed, signed, executed -- each PASS, FAIL (with the step and reason)
or NOT_ESTABLISHED (its evidence was not supplied). A verdict is never inferred from another one.

Offline by design: chain reads are supplied as data, so the result is recomputable from the fixture alone. Supplied RPC data is
never trusted as evidence on its own: owners@block and `executed` PASS only on proofs the checker verifies itself (a header it
hashes, Merkle-Patricia proofs under its roots); unproven chain data gives NOT_ESTABLISHED with the reason. What is checked
against what is in README.md.

usage: python3 check.py FIXTURE.json            # print the four verdicts
       python3 check.py --vectors vectors.json  # run every vector, compare with its expected verdicts
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wyriwe_encoder as W  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ENCODER_SPEC_CID = "ipfs://bafkreig5ix5inb75zrkfn4frg4ctb6judsvcc3urhtnm4llwuvb2uvrlu4"   # ENCODER.md (CIDv1, raw, sha2-256)
ENCODERS = {ENCODER_SPEC_CID: W.encode}                    # the encoders this checker can run, by pinned spec CID
EXEC_TX = W.keccak256(b"execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)")[:4]
EV_SUCCESS = "0x" + W.keccak256(b"ExecutionSuccess(bytes32,uint256)").hex()
EV_FAILURE = "0x" + W.keccak256(b"ExecutionFailure(bytes32,uint256)").hex()
PASS, FAIL, NE = "PASS", "FAIL", "NOT_ESTABLISHED"


def _v(verdict, step=None, reason=None, **extra):
    d = {"verdict": verdict}
    if step is not None:
        d["step"] = step
    if reason is not None:
        d["reason"] = reason
    d.update(extra)
    return d


def _h(b: bytes) -> str:
    return "0x" + b.hex()


def _hx(s) -> bytes:
    return bytes.fromhex(s[2:]) if isinstance(s, str) and s.startswith("0x") else b""


def _decode_payload(p: bytes):
    """The v0 payload (ABI of the SafeTx fields, ENCODER.md section 5) back into fields; None if malformed."""
    if len(p) < 320 + 32:
        return None
    w = [p[32 * i:32 * i + 32] for i in range(10)]
    off = int.from_bytes(w[2], "big")
    if off != 320 or off + 32 > len(p):
        return None
    n = int.from_bytes(p[off:off + 32], "big")
    if off + 32 + n > len(p) or len(p) != off + 32 + n + ((-n) % 32):
        return None
    a = lambda x: "0x" + x[12:].hex()
    return {"to": a(w[0]), "value": int.from_bytes(w[1], "big"), "data": p[off + 32:off + 32 + n], "operation": int.from_bytes(w[3], "big"),
            "safeTxGas": int.from_bytes(w[4], "big"), "baseGas": int.from_bytes(w[5], "big"), "gasPrice": int.from_bytes(w[6], "big"),
            "gasToken": a(w[7]), "refundReceiver": a(w[8]), "nonce": int.from_bytes(w[9], "big")}


def _decode_exec(inp: bytes):
    """execTransaction(...) calldata -> (the nine SafeTx fields it carries, the signatures bytes); None if not that call."""
    if len(inp) < 4 + 320:
        return None
    b = inp[4:]
    w = [b[32 * i:32 * i + 32] for i in range(10)]
    rd = lambda o: b[o + 32:o + 32 + int.from_bytes(b[o:o + 32], "big")] if o + 32 <= len(b) else b""
    a = lambda x: "0x" + x[12:].hex()
    f = {"to": a(w[0]), "value": int.from_bytes(w[1], "big"), "data": rd(int.from_bytes(w[2], "big")), "operation": int.from_bytes(w[3], "big"),
         "safeTxGas": int.from_bytes(w[4], "big"), "baseGas": int.from_bytes(w[5], "big"), "gasPrice": int.from_bytes(w[6], "big"),
         "gasToken": a(w[7]), "refundReceiver": a(w[8])}
    return f, rd(int.from_bytes(w[9], "big"))


def _safe_signers(digest: bytes, sigs: bytes):
    """Owner addresses recovered from Safe signatures over digest, in order; v 27/28 = EIP-712, v 31/32 = eth_sign. Contract (v 0)
    and approved-hash (v 1) signatures are outside v0: reported, never counted."""
    out = []
    for i in range(0, len(sigs) - len(sigs) % 65, 65):
        s = sigs[i:i + 65]
        v = s[64]
        if v in (27, 28):
            out.append(W.ecrecover(digest, s))
        elif v in (31, 32):
            out.append(W.ecrecover(W.keccak256(b"\x19Ethereum Signed Message:\n32" + digest), s[:64] + bytes([v - 4])))
        else:
            out.append(None)
    return out


# ---------------------------------------------------------------- authenticated chain state (PROFILE.md section 6, Pavlo WG 5962)
def _rlp(b: bytes, i: int = 0):
    """RLP decode -> (item, next index); an item is bytes or a list."""
    p = b[i]
    if p < 0x80:
        return b[i:i + 1], i + 1
    if p < 0xb8:
        n = p - 0x80; return b[i + 1:i + 1 + n], i + 1 + n
    if p < 0xc0:
        ln = p - 0xb7; n = int.from_bytes(b[i + 1:i + 1 + ln], "big"); return b[i + 1 + ln:i + 1 + ln + n], i + 1 + ln + n
    if p < 0xf8:
        n, j = p - 0xc0, i + 1
    else:
        ln = p - 0xf7; n = int.from_bytes(b[i + 1:i + 1 + ln], "big"); j = i + 1 + ln
    end, out = j + n, []
    while j < end:
        it, j = _rlp(b, j); out.append(it)
    return out, end


def rlp_decode(b: bytes):
    it, j = _rlp(b)
    if j != len(b):
        raise ValueError("trailing bytes after RLP item")
    return it


def _nibbles(b: bytes):
    return [x for c in b for x in (c >> 4, c & 15)]


def mpt_get(root: bytes, key: bytes, proof, secure: bool = True):
    """Verify a Merkle-Patricia proof (a node list, as eth_getProof returns) of key under root; return the value bytes, or b""
    for a proven absence. Raises ValueError on any node that does not hash to its reference or does not follow the path.
    secure=True: the state and storage tries (keys hashed); False: the transaction and receipt tries (key = rlp(index))."""
    nodes = {W.keccak256(n): n for n in proof}
    path, ref = _nibbles(W.keccak256(key) if secure else key), root
    while True:
        if isinstance(ref, list):
            node = ref
        else:
            if len(ref) == 0:
                return b""
            raw = nodes.get(ref) if len(ref) == 32 else None
            if raw is None:
                raise ValueError("proof is missing a node or a node does not hash to its reference")
            node = rlp_decode(raw)
        if len(node) == 17:
            if not path:
                return node[16]
            ref, path = node[path[0]], path[1:]
            continue
        if len(node) != 2:
            raise ValueError("malformed trie node")
        hp = _nibbles(node[0]); flag = hp[0]
        part = hp[2:] if flag in (0, 2) else hp[1:]
        if path[:len(part)] != part:
            return b""
        path = path[len(part):]
        if flag in (2, 3):
            if path:
                return b""
            return node[1]
        ref = node[1]


SAFE_OWNERS_SLOT, SAFE_THRESHOLD_SLOT, SENTINEL = 2, 4, "0x" + "00" * 19 + "01"


def safe_owners_proven(tr: dict, account: str):
    """owners@block, authenticated: the header hashes to block_hash and carries `block`; the Safe's account proof verifies
    against the header's stateRoot; storage proofs of the owners linked list (slot 2) and threshold (slot 4) verify against
    the Safe's storageRoot. Returns (owners, threshold) READ FROM THE PROOFS; raises ValueError otherwise. The canonicity of
    block_hash itself is not something an offline checker can know: it is reported for the consumer to confirm."""
    hdr = _hx(tr.get("header_rlp"))
    if not hdr or _h(W.keccak256(hdr)) != tr.get("block_hash"):
        raise ValueError("header does not hash to block_hash")
    h = rlp_decode(hdr)
    if int.from_bytes(h[8], "big") != tr.get("block"):
        raise ValueError("header number differs from block")
    acct = mpt_get(h[3], bytes.fromhex(account[2:]), [_hx(n) for n in tr.get("account_proof") or []])
    if not acct:
        raise ValueError("account not proven under stateRoot")
    sroot = rlp_decode(acct)[2]
    sp = [_hx(n) for n in tr.get("storage_proof") or []]
    slot = lambda k: int.from_bytes(rlp_decode(v), "big") if (v := mpt_get(sroot, k, sp)) else 0
    word = lambda n: n.to_bytes(32, "big")
    owners, cur = [], SENTINEL
    for _ in range(64):
        nxt = slot(W.keccak256(word(int(cur, 16)) + word(SAFE_OWNERS_SLOT)))
        if nxt == 0:
            raise ValueError("owners linked list broken in the proof")
        cur = "0x" + nxt.to_bytes(20, "big").hex()
        if cur == SENTINEL:
            break
        owners.append(cur)
    else:
        raise ValueError("owners linked list does not terminate")
    thr = slot(word(SAFE_THRESHOLD_SLOT))
    if not owners or not (1 <= thr <= len(owners)):
        raise ValueError("no owners or threshold out of range")
    return owners, thr


def _header(blk: dict):
    """A block header the checker hashes itself: it must hash to block_hash and carry `block`. Returns the decoded fields."""
    hdr = _hx(blk.get("header_rlp"))
    if not hdr or _h(W.keccak256(hdr)) != blk.get("block_hash"): raise ValueError("header does not hash to block_hash")  # CHECK:exec_header
    h = rlp_decode(hdr)
    if int.from_bytes(h[8], "big") != blk.get("block"): raise ValueError("header number differs from block")  # CHECK:exec_number
    return h


def execution_proven(ex: dict):
    """executed, authenticated (Echo/Pavlo, WG 5966-5967): the transaction bytes and its receipt are both proven under the
    transactionsRoot and receiptsRoot of a header the checker hashes, at the same index. Returns (tx bytes, status, logs) READ
    FROM THE PROOFS; raises ValueError otherwise. As for owners@block, block_hash is reported for the consumer to confirm."""
    h = _header(ex)
    i = ex.get("tx_index")
    if not isinstance(i, int) or i < 0:
        raise ValueError("no tx_index")
    key = W.rlp_encode(i)
    txb = mpt_get(h[4], key, [_hx(n) for n in ex.get("tx_proof") or []], secure=False)
    rcb = mpt_get(h[5], key, [_hx(n) for n in ex.get("receipt_proof") or []], secure=False)
    if not txb or not rcb:
        raise ValueError("transaction or receipt not included at tx_index")
    r = rlp_decode(rcb[1:] if rcb[0] < 0x80 else rcb)   # typed receipt: type byte || rlp
    logs = [{"address": _h(a), "topics": [_h(t) for t in ts], "data": _h(d)} for a, ts, d in r[3]]
    return txb, int.from_bytes(r[0], "big"), logs


def _tx_to_input(txb: bytes):
    """(to, input) of a canonical transaction: legacy rlp, or a typed envelope (1, 2, 3, 4)."""
    if txb[0] >= 0xc0:
        f = rlp_decode(txb); return _h(f[3]), f[5]
    f = rlp_decode(txb[1:])
    return (_h(f[4]), f[6]) if txb[0] == 1 else (_h(f[5]), f[7])


def _exec_outcome(status, logs, acct, dg):
    """None when this receipt shows the account executed this digest; otherwise the reason."""
    if status != 1: return "transaction_reverted"  # CHECK:status
    # the Safe's event carries the digest as topics[1] (v1.4.x: `bytes32 indexed txHash`) or as the first data word (v1.3.0)
    ev_hash = lambda l: (l.get("topics") or [])[1][2:] if len(l.get("topics") or []) > 1 else (l.get("data") or "")[2:66]
    mine = [l for l in logs if (l.get("address") or "").lower() == acct and ev_hash(l) == dg[2:]]
    # a Safe ExecutionFailure has no ExecutionSuccess, so one check covers both (the reason says which)
    if not any((l.get("topics") or [None])[0] == EV_SUCCESS for l in mine): return "safe_ExecutionFailure" if any((l.get("topics") or [None])[0] == EV_FAILURE for l in mine) else "no_ExecutionSuccess_for_this_digest"  # CHECK:exec_success
    return None


def check(fx: dict) -> dict:
    flow = fx.get("flow") or {}
    intent, cid, claimed = flow.get("intent"), flow.get("encoder_spec_cid"), flow.get("claimed") or {}
    payload = _hx(flow.get("payload"))
    res = {}

    # ---- encoded: steps 1-3
    def encoded():
        try:
            ih = W.intent_hash(intent)
        except Exception as e:
            return _v(FAIL, 1, f"intent_unhashable: {e}")
        if _h(ih) != claimed.get("intentHash"): return _v(FAIL, 1, "intent_hash_mismatch")  # CHECK:intent_hash
        if not isinstance(cid, str) or _h(W.encoder_pipeline_hash(cid, ih)) != claimed.get("encoderPipelineHash"): return _v(FAIL, 2, "encoder_pipeline_hash_mismatch")  # CHECK:pipeline_hash
        enc = ENCODERS.get(cid)
        if enc is None:
            return _v(NE, 3, "encoder_not_available_to_this_checker")
        try:
            want, _ = enc(intent)
        except W.EncodeError as e:
            return _v(FAIL, 3, f"intent_not_encodable: {e}")
        if payload != want: return _v(FAIL, 3, "payload_differs_from_encoder_output")  # CHECK:payload_bytes
        if _h(W.keccak256(payload)) != claimed.get("payloadHash"): return _v(FAIL, 3, "payload_hash_mismatch")  # CHECK:payload_hash
        return _v(PASS)
    res["encoded"] = encoded()

    # ---- signed: steps 5-6 (from the PAYLOAD, independent of the encoder verdict)
    signers = None

    def signed():
        nonlocal signers
        f = _decode_payload(payload)
        if f is None or not isinstance(intent, dict):
            return _v(FAIL, 5, "payload_not_a_v0_safe_payload")
        try:
            digest = W.safe_tx_hash(intent["chainId"], intent["account"], f)
        except Exception as e:
            return _v(FAIL, 5, f"digest_not_derivable: {e}")
        if _h(digest) != claimed.get("signingDigest"): return _v(FAIL, 5, "signing_digest_mismatch")  # CHECK:signing_digest
        ch = fx.get("chain") or {}
        tx = ch.get("tx")
        if not tx:
            return _v(NE, 6, "no_transaction_supplied")
        if (tx.get("to") or "").lower() != intent["account"]: return _v(FAIL, 6, "transaction_not_to_the_account")  # CHECK:tx_to
        inp = _hx(tx.get("input"))
        dec = _decode_exec(inp)
        if dec is None:
            return _v(FAIL, 6, "transaction_input_malformed")
        if inp[:4] != EXEC_TX: return _v(FAIL, 6, "not_an_execTransaction_call")  # CHECK:exec_call
        call, sigs = dec
        if any(call[k] != f[k] for k in call): return _v(FAIL, 6, "transaction_call_differs_from_payload")  # CHECK:call_fields
        if str(f["nonce"]) != str(ch.get("nonce_at_execution")): return _v(FAIL, 6, "nonce_differs")  # CHECK:nonce
        owners = [o.lower() for o in ch.get("owners") or []]
        thr = ch.get("threshold")
        if not owners or not isinstance(thr, int) or thr < 1:
            return _v(NE, 6, "owners_or_threshold_not_supplied")
        rec = _safe_signers(digest, sigs)
        signers = [r for r in rec if r]
        last = ""
        for r in rec:
            # an invalid or non-v0 signature recovers no address, so the owner test rejects it too (one check, two reasons)
            if r not in owners: return _v(FAIL, 6, "signature_invalid_or_outside_v0" if r is None else "signer_not_an_owner", signers=signers)  # CHECK:sig_owner
            if (r or "") <= last: return _v(FAIL, 6, "signers_not_strictly_ascending", signers=signers)  # CHECK:sig_order
            last = r or ""
        if len(rec) < thr: return _v(FAIL, 6, "below_threshold", signers=signers)  # CHECK:sig_threshold
        return _v(PASS, signers=signers)
    res["signed"] = signed()

    # ---- reviewed: step 4
    def reviewed():
        rv = fx.get("review")
        if not rv or not rv.get("approvals"):
            return _v(NE, 4, "no_approval_supplied")
        tr = rv.get("trust_root") or {}
        kind = tr.get("kind")
        if kind == "owners@block":
            try:
                keys, thr = safe_owners_proven(tr, intent["account"]); err = None
            except Exception as e:
                keys, thr, err = [k.lower() for k in tr.get("owners") or []], tr.get("threshold") or 1, str(e)
            if err is not None: return _v(NE, 4, f"owner_set_not_authenticated: {err}", trust_root={"kind": kind})  # CHECK:owners_proof
            tid = f"owners@{tr.get('block')} (block_hash {tr.get('block_hash')}: confirm it is canonical)"
        elif kind == "reviewer-list@commitment":
            lst, com = tr.get("list") or {}, tr.get("commitment") or {}
            if "content_hash" not in com:
                return _v(NE, 4, "reviewer_list_not_content_addressed (on-chain registries have no v0 storage layout)", trust_root={"kind": kind})
            # the owners' authorization below is over the hash of the list AS GIVEN, so a list that was changed after it was
            # pinned fails there; a content_hash that differs is reported, not a separate check
            lh = _h(W.keccak256(W.jcs(lst)))
            # authority + prior binding (Pavlo, WG 5962): the account's PROVEN owners pinned this list hash, before execution
            au = tr.get("authorization") or {}
            try:
                aowners, athr = safe_owners_proven(au.get("owners_root") or {}, intent["account"]); aerr = None
            except Exception as e:
                o_r = au.get("owners_root") or {}
                aowners, athr, aerr = [k.lower() for k in o_r.get("owners") or []], o_r.get("threshold") or 1, str(e)
            if aerr is not None: return _v(NE, 4, f"reviewer_list_authority_not_established: {aerr}", trust_root={"kind": kind})  # CHECK:list_authority
            pin = (au.get("owners_root") or {}).get("block") or 0
            st = {"account": intent["account"], "listHash": lh, "pinnedAtBlock": pin}
            d = W.root_pin_digest(intent["chainId"], st)
            who = {W.ecrecover(d, _hx(sg)) for sg in au.get("signatures") or []} & set(aowners)
            if len(who) < athr: return _v(NE, 4, "reviewer_list_not_authorized_by_the_owners", trust_root={"kind": kind})  # CHECK:list_pin_sigs
            try:
                exb = _header((fx.get("chain") or {}).get("execution") or {}) and fx["chain"]["execution"]["block"]
            except Exception:
                exb = None   # the execution block is only known from an authenticated header
            if not isinstance(exb, int) or not pin < exb: return _v(NE, 4, "reviewer_list_not_bound_before_execution", trust_root={"kind": kind})  # CHECK:list_prior
            tid = f"content:{lh} pinned by owners@{pin}"
            keys, thr = [k.lower() for k in lst.get("reviewers") or []], lst.get("threshold")
            if not keys or not isinstance(thr, int) or thr < 1:
                return _v(NE, 4, "reviewer_list_incomplete", trust_root={"kind": kind, "id": tid})
        else:
            return _v(NE, 4, "no_recomputable_trust_root", trust_root={"kind": kind})
        try:
            ih, ph = _h(W.intent_hash(intent)), _h(W.encoder_pipeline_hash(cid, W.intent_hash(intent)))
        except Exception:
            return _v(FAIL, 4, "intent_unhashable")
        want = {"chainId": intent["chainId"], "account": intent["account"], "intentHash": ih, "encoderPipelineHash": ph,
                "payloadHash": claimed.get("payloadHash"), "signingDigest": claimed.get("signingDigest")}
        ok, why = [], []
        for ap in rv["approvals"]:
            st = ap.get("struct") or {}
            if any(st.get(k) != v for k, v in want.items()): why.append("approves_different_input"); continue  # CHECK:approval_input
            try:
                who = W.ecrecover(W.wyriwe_struct_digest(ap.get("domain_chain_id", intent["chainId"]), st), _hx(ap.get("signature")))
            except Exception:
                who = None
            # an unrecoverable signature yields no address, so the trust-root membership test below also rejects it (one check)
            if who not in keys: why.append("approval_signature_invalid" if who is None else "approver_outside_trust_root"); continue  # CHECK:approval_root
            if who not in ok:
                ok.append(who)
        overlap = sorted(set(ok) & set(signers)) if signers is not None else None
        rep = {"trust_root": {"kind": kind, "id": tid}, "approvers": ok, "overlap_with_signers": overlap if overlap is not None else "unknown",
               "independent_review": None if overlap is None else (kind != "owners@block" and not overlap)}
        if len(ok) < thr: return _v(FAIL, 4, "below_threshold" + (f" ({', '.join(sorted(set(why)))})" if why else ""), **rep)  # CHECK:approval_threshold
        return _v(PASS, **rep)
    res["reviewed"] = reviewed()

    # ---- executed: step 7. PASS only when authenticated; supplied RPC data alone is never execution evidence
    def executed():
        ch = fx.get("chain") or {}
        rc, tx, ex = ch.get("receipt"), ch.get("tx"), ch.get("execution")
        dg = claimed.get("signingDigest") or ""
        acct = intent.get("account") if isinstance(intent, dict) else None
        if not ex:
            if not rc:
                return _v(NE, 7, "no_receipt_supplied")
            ok = _exec_outcome(rc.get("status"), rc.get("logs") or [], acct, dg) is None
            return _v(NE, 7, "rpc_data_consistent_unauthenticated" if ok else "rpc_data_unauthenticated")
        try:
            txb, status, logs = execution_proven(ex)
        except Exception as e:
            return _v(NE, 7, f"execution_not_authenticated: {e}")
        th = _h(W.keccak256(txb))
        rep = {"block": ex.get("block"), "block_hash": ex.get("block_hash") + " (confirm it is canonical)", "tx_hash": th}
        if not tx:
            return _v(NE, 7, "no_transaction_supplied", **rep)
        # the transaction signed() judged must be the one proven in the block: its hash, as supplied, and its bytes
        if tx.get("hash", th) != th or (rc or {}).get("transactionHash", th) != th: return _v(NE, 7, "transaction_hash_mismatch", **rep)  # CHECK:tx_hash
        if _tx_to_input(txb) != ((tx.get("to") or "").lower(), _hx(tx.get("input"))): return _v(NE, 7, "proven_transaction_is_not_the_checked_one", **rep)  # CHECK:tx_bytes
        why = _exec_outcome(status, logs, acct, dg)
        return _v(FAIL, 7, why, **rep) if why else _v(PASS, **rep)
    res["executed"] = executed()
    return res


def pins_ok() -> bool:
    """ENCODER.md names the reference implementation's sha256, and ENCODER_SPEC_CID is the CIDv1 of ENCODER.md: check both."""
    import base64, hashlib, re as _re
    try:
        spec = open(os.path.join(HERE, "ENCODER.md"), "rb").read()
        impl = hashlib.sha256(open(os.path.join(HERE, "wyriwe_encoder.py"), "rb").read()).hexdigest()
    except OSError:
        print("pins: ENCODER.md / wyriwe_encoder.py not next to check.py -- not checked"); return True
    cid = "ipfs://b" + base64.b32encode(bytes([1, 0x55, 0x12, 0x20]) + hashlib.sha256(spec).digest()).decode().lower().rstrip("=")
    named = _re.search(rb"reference implementation: \*\*`([0-9a-f]{64})`\*\*", spec)
    ok = cid == ENCODER_SPEC_CID and named is not None and named.group(1).decode() == impl
    print(f"pins: ENCODER.md CID {'==' if cid == ENCODER_SPEC_CID else '!='} ENCODER_SPEC_CID; wyriwe_encoder.py sha256 "
          f"{'==' if named and named.group(1).decode() == impl else '!='} the one ENCODER.md names")
    return ok


def run_vectors(path: str) -> int:
    vs = json.load(open(path))["vectors"]
    bad = 0
    for v in vs:
        try:
            got = check(v["fixture"])
            g = {k: got[k]["verdict"] for k in ("encoded", "reviewed", "signed", "executed")}
        except Exception as e:
            g = {"crash": f"{type(e).__name__}: {e}"}
        ok = g == v["expect"]
        for path, want in (v.get("expect_extra") or {}).items():   # e.g. "reviewed.independent_review": false
            cur = got if "crash" not in g else {}
            for part in path.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            ok = ok and cur == want
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {v['name']:44} {g}" + ("" if ok else f"  expected {v['expect']}"))
    print(f"{len(vs) - bad}/{len(vs)} vectors match")
    return 1 if bad or not pins_ok() else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--vectors":
        sys.exit(run_vectors(sys.argv[2]))
    if len(sys.argv) == 2:
        print(json.dumps(check(json.load(open(sys.argv[1]))), indent=1))
        sys.exit(0)
    print(__doc__)
    sys.exit(2)
