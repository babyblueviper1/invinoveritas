#!/usr/bin/env python3
"""
live_check.py — run the pre-action governance conformance invariants against a LIVE endpoint.

The fixture verifier (../verifier.py) checks portable static fixtures. This runs the same invariants
against a real governance response, so an implementer can point the suite at a running endpoint and see
where the invariants hold and where gaps remain. Reported invariants: canonical_envelope,
admission_invariant, anchoring_existence, anchoring_precedence, chain_invariant — anchoring is split
into existence (the commitment provably exists) vs precedence (it was provably made before the outcome)
so a confirmed-but-backfilled anchor can never pass as ordering (rpelevin, autogen#7353).

Mapping-driven and implementation-independent: a small mapping JSON says how to obtain the governance
block and where each field lives. The crypto is the vendored, zero-dep BIP-340 core (and NIP-01 for
the Nostr-event scheme). No third-party deps.

    python3 live_check.py adapters/safeagent.mapping.json

Supported signature schemes (mapping `sig_scheme`):
  - `bip340-hash`  : BIP-340 schnorr signature directly over the 32-byte envelope hash (e.g. SafeAgent)
  - `nostr-event`  : the admission record is a NIP-01 event; verify id + schnorr (invinoveritas)
  - `ed25519-jcs`  : Ed25519 over canonical JCS bytes (e.g. PMI) — verified if an ed25519 lib is present,
                     otherwise reported as `unverified_here` (scheme recognized, needs an ed25519 verifier)
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _bip340_nostr import nostr_event_id, schnorr_verify  # vendored, zero-dep


def _b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _verify_jws_legs(jws, canonical_bytes, candidate_pubkeys):
    """Verify a JWS general serialization (RFC 7515) fixture-alone: each signature leg is checked over
    its signing input `BASE64URL(protected) + "." + BASE64URL(payload)` under a known Ed25519 key, and
    the payload must decode to the canonical envelope bytes (else the legs sign something other than the
    certified envelope). Returns (verified_legs, total_legs, payload_ok). General by construction — any
    multi-signer verifier using JWS general serialization (e.g. AgentOracle's AgentTrust+AO composition)
    is scored on its STRONGER read instead of being under-credited because we didn't reconstruct the JWS
    signing input. ed25519 only (nacl); zero-dep otherwise.
    Returns (verified_legs, total_legs, payload_ok, verified_pubkeys) — verified_pubkeys lets the caller
    name which signers passed (and by elimination which failed/were unavailable) for the audit record."""
    try:
        from nacl.signing import VerifyKey
    except ImportError:
        return 0, 0, None, []
    sigs = jws.get("signatures") or []
    payload_b64 = jws.get("payload", "")
    payload_ok = bool(payload_b64) and _b64u(payload_b64) == (
        canonical_bytes.encode("utf-8") if isinstance(canonical_bytes, str) else canonical_bytes)
    keys = [(k, bytes.fromhex(k)) for k in candidate_pubkeys if k]
    verified = 0
    verified_pubkeys = []
    for s in sigs:
        si = ((s.get("protected", "") + "." + payload_b64)).encode()
        raw = _b64u(s.get("signature", ""))
        for khex, kb in keys:
            try:
                VerifyKey(kb).verify(si, raw)
                verified += 1
                verified_pubkeys.append(khex)
                break
            except Exception:  # noqa: BLE001 — try the next candidate key
                continue
    return verified, len(sigs), payload_ok, verified_pubkeys


# claim-level ordering (incl. rpelevin/giskard09's third level) + each evidence mode's contract requirement
_CLAIM_RANK = {"admission_multisig_unverifiable": 0, "admission_independent": 1, "admission_multisig_recomputable": 2}
_MODE_CONTRACT_FIELD = {"embedded_fixture": "key_recomputed", "pinned_registry": "external_evidence",
                        "external_resolution": "external_evidence", "cached_prior": "external_evidence"}


def classify_evidence_mode(declared_hint, derived_mode, key_recomputed, external_evidence, base_claim):
    """Referee-derived, CONTRACT-AWARE evidence-mode cross-check (rpelevin + giskard09, autogen#7353).

    A producer hint is disclosure, never control flow. The referee derives the mode from what it verified
    and checks whether the DECLARED mode's CONTRACT is satisfiable by what is actually present — a hint can
    match the label yet contradict the contract (declares embedded_fixture while the key is not recomputable;
    declares pinned_registry while no external evidence hashes exist referee-side). On contradiction the
    referee-derived value wins and the row falls to the strongest claim actually verifiable: admission_
    independent if the key is at least recomputable, else admission_multisig_unverifiable.
    Returns {cross_check, evidence_mode, claim_level, blocked_reason}."""
    if not declared_hint:
        return {"cross_check": "producer_hint_missing", "evidence_mode": derived_mode,
                "claim_level": base_claim, "blocked_reason": None}
    if declared_hint not in _MODE_CONTRACT_FIELD:
        return {"cross_check": "producer_hint_unverifiable", "evidence_mode": derived_mode,
                "claim_level": base_claim,
                "blocked_reason": f"producer hint {declared_hint!r} is not a known evidence mode"}
    req = _MODE_CONTRACT_FIELD[declared_hint]
    contract_ok = key_recomputed if req == "key_recomputed" else external_evidence
    if contract_ok and declared_hint == derived_mode:
        return {"cross_check": "producer_hint_matches_referee", "evidence_mode": derived_mode,
                "claim_level": base_claim, "blocked_reason": None}
    # contradiction: declared mode's contract unmet (or label disagrees) -> referee-derived value wins.
    fallback = "admission_independent" if key_recomputed else "admission_multisig_unverifiable"
    claim = fallback if _CLAIM_RANK[fallback] <= _CLAIM_RANK.get(base_claim, 2) else base_claim
    reason = (f"producer declared {declared_hint!r} but its contract is unmet referee-side "
              f"({'key not recomputable from fixture' if req == 'key_recomputed' else 'external evidence absent'}); "
              "referee-derived value wins")
    return {"cross_check": "producer_hint_contradicts_referee",
            "evidence_mode": f"{declared_hint}_unverifiable" if not contract_ok else derived_mode,
            "claim_level": claim, "blocked_reason": reason}


def _dig(obj, path):
    """Follow a list-of-keys path into a nested dict/list. Returns None if absent."""
    if path is None:
        return obj
    if isinstance(path, str):
        path = [path]
    cur = obj
    for k in path:
        if isinstance(cur, dict):
            cur = cur.get(k)
        elif isinstance(cur, list) and isinstance(k, int):
            cur = cur[k] if -len(cur) <= k < len(cur) else None
        else:
            return None
    return cur


def _inject_nonce(body):
    """Replace the literal __NONCE__ in any string body value with a unique token, so endpoints that
    deduplicate identical claims still issue a fresh governance block on each run."""
    if not isinstance(body, dict):
        return body
    import uuid
    nonce = uuid.uuid4().hex[:12]
    return {k: (v.replace("__NONCE__", nonce) if isinstance(v, str) else v) for k, v in body.items()}


def _http(method, url, headers=None, body=None, timeout=25):
    data = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers or {})
    # default User-Agent: some hosts UA-filter and 403 a bare urllib client (e.g. PMI/sixu-ai)
    hdrs.setdefault("User-Agent", "preaction-governance-conformance/referee")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # Governance endpoints commonly embed the SIGNED governance block in a non-2xx body (e.g. PMI
        # serves it with HTTP 400 "agent_did is required"). Parse the error body so the invariants can
        # still be checked; re-raise only if there's no JSON body to read.
        raw = e.read().decode() if e.fp else ""
        try:
            return json.loads(raw)
        except Exception:
            raise e from None


def _jcs(obj) -> bytes:
    """Canonical JSON bytes (sorted keys, no whitespace, UTF-8). RFC 8785-compatible for the
    string/integer/boolean field set; note differences only arise on non-integer numbers."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _suite(state, code, detail, mechanism=None, key_source=None):
    # state: pass|fail|pending|not_provided|not_assessable|unverified_here
    # mechanism (anchoring suites only): WHICH external clock satisfied the axis — e.g. "Bitcoin OTS",
    # "on-chain (Arbitrum)" — so the board shows that one invariant survives across mechanisms.
    # key_source (admission only): HOW the verification key(s) were obtained / how complete the signer
    # set is from the fixture alone — e.g. "embedded", "1/2 keys in fixture" — so a multi-signer claim
    # never overclaims fixture-completeness (rpelevin, autogen#7353).
    s = {"state": state, "code": code, "detail": detail}
    if mechanism:
        s["mechanism"] = mechanism
    if key_source:
        s["key_source"] = key_source
    return s


def _verify_admission(scheme, envelope_hash, pubkey, signature, event):
    """Return (sig_valid: bool|None, detail). None = recognized-but-not-verifiable-here."""
    s = (scheme or "").lower()
    try:
        if s.startswith("bip340"):  # bip340-hash, bip340-schnorr — schnorr directly over the envelope hash
            return schnorr_verify(bytes.fromhex(envelope_hash), bytes.fromhex(pubkey), bytes.fromhex(signature)), \
                "BIP-340 schnorr over the envelope hash"
        if s == "nostr-event":
            if not event:
                return False, "nostr-event scheme but no event object provided"
            if nostr_event_id(event) != event.get("id"):
                return False, "nostr event id does not recompute"
            return schnorr_verify(bytes.fromhex(event["id"]), bytes.fromhex(event["pubkey"]),
                                  bytes.fromhex(event["sig"])), "NIP-01 id recompute + schnorr"
        if s.startswith("ed25519"):
            try:
                from nacl.signing import VerifyKey  # optional
            except ImportError:
                return None, "ed25519-jcs recognized; needs an ed25519 verifier (e.g. PyNaCl) to check here"
            vk = VerifyKey(bytes.fromhex(pubkey))
            sig_b = bytes.fromhex(signature)
            # Implementations differ on what message the hash-signature covers: the RAW 32 bytes of the
            # envelope hash, or the 64-char HEX STRING of it (e.g. PMI/moyan signs the hex string). Both
            # are a deterministic commitment to the same hash, so accept either and report which matched —
            # the adapter accommodates the convention so implementers need no local patch.
            for enc_label, msg in (("raw hash bytes", bytes.fromhex(envelope_hash)),
                                   ("hex-string of the hash", envelope_hash.encode("utf-8"))):
                try:
                    vk.verify(msg, sig_b)
                    return True, f"Ed25519 over the {enc_label} (via PyNaCl)"
                except Exception:  # noqa: BLE001 — try the next encoding
                    continue
            return False, "Ed25519 signature did not verify over the raw hash bytes or its hex string"
        return False, f"unknown sig_scheme: {scheme}"
    except Exception as e:  # noqa: BLE001
        return False, f"signature check error: {e}"


def run(mapping: dict) -> dict:
    fields = mapping.get("fields", {})

    # 1) obtain the governance block (live fetch or from a saved file)
    if "fetch" in mapping:
        f = mapping["fetch"]
        body = _inject_nonce(f.get("body"))  # unique per run so dedup'ing endpoints issue a fresh claim
        resp = _http(f.get("method", "GET"), f["url"], f.get("headers"), body)
        gov = _dig(resp, f.get("governance_path"))
    else:
        resp = json.loads(Path(mapping["response_file"]).read_text())
        gov = _dig(resp, mapping.get("governance_path"))
    if gov is None:
        # no governance block: not a verdict on the invariants, just nothing to check
        return {"endpoint": mapping.get("name"), "overall": "no_governance_block",
                "suites": {}, "raw_status": resp.get("status") if isinstance(resp, dict) else None,
                "detail": "response carried no governance block (e.g. SKIP/duplicate/error) — nothing to verify"}

    envelope_hash = _dig(gov, fields.get("envelope_hash"))
    pubkey = _dig(gov, fields.get("pubkey"))
    signature = _dig(gov, fields.get("signature"))
    scheme = (_dig(gov, fields["sig_scheme"]) if fields.get("sig_scheme") else None) or mapping.get("sig_scheme")
    event = _dig(gov, fields.get("event")) if fields.get("event") else None
    # `anchor_declared` = the mapping names an anchor slot at all. Distinguishes a verifier with no
    # anchoring concept (existence FAIL) from one whose anchor sibling exists in-schema but is absent on
    # this particular call (existence PENDING — AgentOracle's "absent-not-null" grammar: the on-chain
    # anchor only populates for fully-signed calls, not bare referee probes).
    anchor_declared = "anchor_endpoint" in fields
    anchor_ep = _dig(gov, fields.get("anchor_endpoint")) if anchor_declared else None
    canonical_bytes = _dig(gov, fields.get("canonical_bytes")) if fields.get("canonical_bytes") else None
    trust = mapping.get("trust_policy", {}).get("independent_verifier_pubkeys", [])
    actor_pubkey = mapping.get("actor_pubkey")
    raw_claim = mapping.get("raw_claim")
    # Some endpoints commit to the whole response MINUS the signature/governance block (e.g. PMI/moyan:
    # envelope_hash = sha256(JCS(response excluding `governance`)) — excluding it avoids self-reference).
    exclude = mapping.get("envelope_excludes")

    suites = {}

    # canonical_envelope: recompute SHA-256(canonical bytes) == declared hash.
    # Preferred path: the endpoint exposes its EXACT canonical UTF-8 bytes (e.g. SafeAgent's
    # canonical_bytes_utf8) — we hash those bytes verbatim, making the binding implementation-independent
    # (no assumption that our JCS matches the issuer's). Fallback: re-canonicalize a returned raw claim.
    if exclude is not None and isinstance(resp, dict):
        # commitment over the response with the named keys removed, JCS-canonicalized
        reduced = {k: v for k, v in resp.items() if k not in exclude}
        recomputed = hashlib.sha256(_jcs(reduced)).hexdigest()
        ok = recomputed == envelope_hash
        suites["canonical_envelope"] = _suite("pass" if ok else "fail",
                                              None if ok else "envelope_hash_mismatch",
                                              f"SHA-256(JCS(response excluding {exclude})) {recomputed[:16]} "
                                              f"vs declared {str(envelope_hash)[:16]}")
    elif canonical_bytes is not None:
        raw = canonical_bytes.encode("utf-8") if isinstance(canonical_bytes, str) else _jcs(canonical_bytes)
        recomputed = hashlib.sha256(raw).hexdigest()
        ok = recomputed == envelope_hash
        suites["canonical_envelope"] = _suite("pass" if ok else "fail",
                                              None if ok else "envelope_hash_mismatch",
                                              f"recomputed SHA-256 of declared canonical bytes {recomputed[:16]} "
                                              f"vs declared {str(envelope_hash)[:16]}")
    elif raw_claim is not None:
        recomputed = hashlib.sha256(_jcs(raw_claim)).hexdigest()
        ok = recomputed == envelope_hash
        suites["canonical_envelope"] = _suite("pass" if ok else "fail",
                                              None if ok else "envelope_hash_mismatch",
                                              f"recomputed {recomputed[:16]} vs declared {str(envelope_hash)[:16]}")
    elif (scheme or "").lower() == "nostr-event" and event:
        # In the Nostr-event scheme the canonical envelope IS the signed event, and its commitment hash
        # is the event id = SHA-256 over the canonical NIP-01 serialization [0,pubkey,created_at,kind,
        # tags,content]. Recompute it from the published fields: if it matches the declared id (== the
        # envelope_hash for this scheme), the canonical bytes faithfully bind the hash — no separate
        # canonical_bytes field needed, the event content IS the canonical payload.
        recomputed = nostr_event_id(event)
        declared = event.get("id")
        ok = recomputed == declared
        suites["canonical_envelope"] = _suite("pass" if ok else "fail",
                                              None if ok else "envelope_hash_mismatch",
                                              f"Nostr event id recomputes from canonical [0,pubkey,created_at,kind,"
                                              f"tags,content]: {str(recomputed)[:16]} vs declared {str(declared)[:16]}")
    else:
        suites["canonical_envelope"] = _suite("not_provided", None,
                                              "raw claim not returned by the endpoint; envelope hash is asserted, "
                                              "not recomputed (expose the canonical claim to enable this check)")

    # admission_invariant: independent identity signed the envelope hash
    # ── key-source transparency (rpelevin, autogen#7353) ────────────────────────────────────────
    # Make explicit how complete the signer set is FROM THE FIXTURE ALONE: the primary key is embedded
    # (it came from the governance block / event and we verified the signature over it). For a multi-
    # signer claim, count how many co-signers also expose their verification key in the fixture, so the
    # board never displays an N-signer row as fully recomputable when only the primary is. Generalizes:
    # single embedded key -> "embedded"; N-signer with a missing co-signer key -> "k/N keys in fixture".
    # Honesty bar: count signatures the referee ACTUALLY RE-VERIFIED, not keys merely present — claiming
    # "2 keys embedded" off an unverified co-signer would itself be the multisig_overclaim rpelevin warns
    # about. The primary verified below; for each co-signer we re-verify its signature over the same
    # envelope hash with a supported scheme. A co-signer whose key is embedded but whose signature rides a
    # different signing input (e.g. a JWS signing-input we don't reconstruct) is reported embedded-but-not-
    # re-verified-here, not silently counted.
    co = _dig(gov, fields.get("co_signers", "co_signers"))
    co = co if isinstance(co, list) else []
    co_pubkeys = [c.get("pubkey") or c.get("public_key") for c in co if isinstance(c, dict)]
    co_embedded = sum(1 for k in co_pubkeys if k)
    # JWS general-serialization path (RFC 7515): if the response carries a top-level `jws` (payload +
    # signatures) AND the payload decodes to the canonical bytes, verify every leg over its signing input
    # so a multi-signer composition is credited on its STRONGER read (all signers fixture-verifiable),
    # not under-counted for a signing input we'd otherwise skip. Falls back to per-co-signer over-the-hash.
    used_jws, verified, total_signers = False, None, 1 + len(co)
    jws = resp.get(mapping.get("jws_path", "jws")) if isinstance(resp, dict) else None
    verified_pubkeys, jws_payload_ok = [], None
    if isinstance(jws, dict) and jws.get("signatures"):
        v, n, jws_payload_ok, verified_pubkeys = _verify_jws_legs(jws, canonical_bytes, [pubkey] + co_pubkeys)
        if jws_payload_ok and n:
            verified, total_signers, used_jws = v, n, True
    if not used_jws:
        co_verified = 0
        for c in co:
            if not isinstance(c, dict):
                continue
            cpk = c.get("pubkey") or c.get("public_key")
            csig = c.get("jws_signature") or c.get("signature")
            if cpk and csig:
                ok, _ = _verify_admission(c.get("sig_scheme") or scheme, envelope_hash, cpk, csig, None)
                if ok:
                    co_verified += 1
        verified = 1 + co_verified  # primary verified just below
    if total_signers <= 1:
        key_source, multisig_gap = "embedded", None
    elif verified >= total_signers:
        key_source, multisig_gap = f"{total_signers} signers verified", None
    else:
        key_source = f"{verified}/{total_signers} signers verified"
        absent = total_signers - 1 - co_embedded
        gap_reason = (f"{absent} co-signer key(s) absent (missing_cosigner_key)" if absent > 0
                      else f"{total_signers - verified} co-signer signature(s) not independently re-verified here")
        multisig_gap = (f"; admission passes on the independent primary signer, but the {total_signers}-signer "
                        f"property is not fully recomputable from the fixture ({gap_reason})")

    # ── audit-grade record behind the green cell (rpelevin, autogen#7353) ───────────────────────
    # embedded-key tamper check: when a signer DECLARES a pubkey_hash, sha256(its pubkey bytes) must
    # match it, else the disclosed key isn't the one the hash commits to (embedded_key_hash_mismatch).
    # General — any verifier that publishes pubkey_hash gets this for free.
    _hash_candidates = co + ([{"pubkey": pubkey, "pubkey_hash": _dig(gov, fields["pubkey_hash"])}]
                             if fields.get("pubkey_hash") else [])
    kh_checked = kh_mismatch = 0
    for _c in _hash_candidates:
        if not isinstance(_c, dict):
            continue
        _ph, _pk = _c.get("pubkey_hash"), (_c.get("pubkey") or _c.get("public_key"))
        if _ph and _pk:
            kh_checked += 1
            try:
                if hashlib.sha256(bytes.fromhex(_pk)).hexdigest() != _ph:
                    kh_mismatch += 1
            except Exception:  # noqa: BLE001 — malformed hex counts as a mismatch
                kh_mismatch += 1
    key_hash = "verified" if kh_checked and not kh_mismatch else ("mismatch" if kh_mismatch else "n/a")
    if kh_mismatch:
        multisig_gap = (multisig_gap or "") + (f"; {kh_mismatch} embedded key(s) do not hash to the declared "
                                               "pubkey_hash (embedded_key_hash_mismatch)")
    # board_claim_level: the HIGHEST claim the referee actually earned (rpelevin's three-level cut)
    claim_level = ("admission_multisig_recomputable" if total_signers > 1 and verified >= total_signers
                   else "admission_independent")
    # name the signers that did NOT verify fixture-alone (failed leg or key unavailable), for the record.
    # JWS path: a co-signer whose key is not among verified_pubkeys; identify it by issuer/kid.
    def _sid(c):
        return c.get("issuer") or c.get("kid") or (c.get("pubkey") or c.get("public_key") or "?")[:16]
    failed_or_unavailable = []
    if used_jws:
        for c in co:
            cpk = (c.get("pubkey") or c.get("public_key")) if isinstance(c, dict) else None
            if not cpk or cpk not in verified_pubkeys:
                failed_or_unavailable.append(_sid(c) if isinstance(c, dict) else "?")
    elif verified < total_signers:
        failed_or_unavailable = [_sid(c) for c in co if isinstance(c, dict)
                                 and not (c.get("pubkey") or c.get("public_key"))]

    # ── evidence-mode field-presence contract (rpelevin, autogen#7353) ──────────────────────────
    # The evidence_mode determines which fields must be present vs absent, which in turn CAPS the highest
    # claim level the row may show: mode -> field presence -> verifier result -> allowed claim level. We
    # EMIT and ENFORCE the contract so the mode is self-checking, not merely satisfied. Only embedded_fixture
    # is in use; pinned_registry / cached_prior / external_resolution are specified and ACTIVATE — each with
    # its required hashes (evidence_hash, resolution_time, key_record_hash) — the moment a row resolves a key
    # out-of-band. Those fields are never emitted empty: their absence means "no external fetch", not "unknown".
    # evidence_mode is REFEREE-DERIVED, never trusted from the producer. Trusting a producer-declared mode
    # would be the fixture_declares_result_referee_does_not_recompute negative — and would make the referee
    # role a rubber stamp any party could replicate by reading claims, which is exactly what keeps the role
    # hard to commoditize. We derive it from what the adapter actually DID: an out-of-band key fetch happened
    # or it didn't. (No row resolves keys externally yet -> embedded_fixture; pinned_registry/external_
    # resolution activate when the adapter actually fetches a key and carries its evidence_hash.)
    external_key_resolution = False
    evidence_mode = "external_resolution" if external_key_resolution else "embedded_fixture"
    _CEILING = {"embedded_fixture": "admission_multisig_recomputable",
                "pinned_registry": "admission_multisig_recomputable",
                "external_resolution": "admission_multisig_recomputable",
                "cached_prior": "admission_independent"}
    _RANK = {"admission_independent": 1, "admission_multisig_recomputable": 2}
    claim_ceiling = _CEILING.get(evidence_mode, "admission_independent")
    key_hash_recomputed = bool(pubkey)     # primary_public_key_hash is recomputed from fixture bytes below
    external_fields_present = False         # embedded rows emit no evidence_hash / resolution_time
    # cap the claim at what the DERIVED mode allows (evidence_mode_claim_mismatch guard) before any hint
    if _RANK.get(claim_level, 9) > _RANK[claim_ceiling]:
        claim_level = claim_ceiling
    # A producer MAY disclose its own evidence_mode as a hint; the referee CROSS-CHECKS, never copies. The
    # check is CONTRACT-AWARE (rpelevin + giskard09): a hint that matches the label but whose contract the
    # referee can't satisfy is `contradicts` -> referee-derived value wins, row falls to the strongest claim
    # actually verifiable (admission_independent, or admission_multisig_unverifiable if no key recomputes).
    producer_mode_hint = _dig(gov, fields.get("evidence_mode", "evidence_mode"))
    _cls = classify_evidence_mode(producer_mode_hint, evidence_mode, key_hash_recomputed,
                                  external_fields_present, claim_level)
    cross_check = _cls["cross_check"]
    evidence_mode = _cls["evidence_mode"]
    claim_level = _cls["claim_level"]
    blocked_reason = _cls["blocked_reason"]
    contract_holds = (not external_fields_present and key_hash_recomputed
                      and verified <= total_signers
                      and cross_check != "producer_hint_contradicts_referee")
    if blocked_reason:
        multisig_gap = (multisig_gap or "") + f"; {blocked_reason}"

    # the machine-readable record behind the compact sub-label: precise enough that another verifier can
    # reproduce WHY the level was earned (rpelevin). Hashes make it reproducible; evidence_mode is explicit
    # and self-checking so ABSENCE is meaningful, not a hidden null.
    _cb = canonical_bytes.encode("utf-8") if isinstance(canonical_bytes, str) else canonical_bytes
    admission_audit = {
        "board_claim_level": claim_level,
        "signer_count": {"verified": verified, "declared": total_signers,
                         "failed_or_unavailable_signer_ids": failed_or_unavailable},
        "signature_input": {
            "encoding": "jws_general_serialization" if used_jws
                        else f"{(scheme or 'sig').replace('-', '_')}_over_envelope_hash",
            "payload_decodes_to_canonical": True if used_jws else None,
        },
        "payload_binding": {
            "canonical_bytes_hash": hashlib.sha256(_cb).hexdigest() if _cb else None,
            "envelope_hash": envelope_hash,
        },
        "key_material": {
            "primary_public_key_hash": hashlib.sha256(bytes.fromhex(pubkey)).hexdigest() if pubkey else None,
            "embedded_key_hash_check": key_hash,  # verified | mismatch | n/a
            "co_signers": [{"signer": _sid(c), "key_source": c.get("key_source"),
                            "pubkey_hash": c.get("pubkey_hash")}
                           for c in co if isinstance(c, dict)],
        },
        # evidence_mode + its enforced field-presence contract: the mode caps the allowed claim level, and
        # `holds` asserts the row's fields are consistent with the mode (external fields absent under
        # embedded_fixture, key hash recomputed, claim within ceiling). Absence is meaningful, not a null.
        "evidence_mode": evidence_mode,
        "evidence_mode_source": "referee_derived",  # NEVER copied from the producer; cross-checked below
        "evidence_contract": {
            "claim_level_ceiling": claim_ceiling,
            "external_evidence_fields_present": external_fields_present,
            "key_hash_recomputed_from_fixture": key_hash_recomputed,
            "producer_mode_hint": producer_mode_hint,    # what the producer disclosed (if any) — disclosure, not control
            "cross_check": cross_check,                  # matches | contradicts | missing | unverifiable (first-class)
            "blocked_reason": blocked_reason,            # null, or why the displayed claim was capped/denied
            "holds": contract_holds,
        },
    }

    sig_valid, sig_detail = _verify_admission(scheme, envelope_hash, pubkey, signature, event)
    if sig_valid is None:
        suites["admission_invariant"] = _suite("unverified_here", "scheme_not_verifiable_here", sig_detail)
    elif not sig_valid:
        suites["admission_invariant"] = _suite("fail", "admission_signature_invalid", sig_detail)
    elif trust and pubkey not in trust:
        suites["admission_invariant"] = _suite("fail", "key_different_but_identity_unproven",
                                              "signature valid, but signer pubkey is not in the declared independent set",
                                              key_source=key_source)
    elif actor_pubkey and pubkey == actor_pubkey:
        suites["admission_invariant"] = _suite("fail", "admission_not_independent", "signer is the actor",
                                              key_source=key_source)
    else:
        suites["admission_invariant"] = _suite("pass", None,
                                              f"{sig_detail}; signer resolves to a declared-independent identity"
                                              + (multisig_gap or ""), key_source=key_source)
    # attach the audit record behind the cell (sub-label stays compact; /conformance.json carries the trail)
    if suites["admission_invariant"]["state"] in ("pass", "fail"):
        suites["admission_invariant"]["audit"] = admission_audit

    # ── anchoring, split into existence vs precedence (rpelevin, autogen#7353) ──────────────────
    # A confirmed anchor can prove a commitment EXISTED by some external point; that is not the same as
    # proving it was made BEFORE the outcome. The board reports the two as separate results so existence
    # can never masquerade as ordering:
    #   anchoring_existence  — the commitment is externally confirmed by the declared mechanism
    #   anchoring_precedence — the accepted anchor point provably precedes the terminal outcome
    # precedence is only assessable once existence holds; otherwise it is `not_assessable`, not a 2nd fail.
    outcome_time = mapping.get("terminal_outcome_time")
    if not anchor_ep:
        if anchor_declared:
            # anchor sibling exists in-schema but is absent on this call (not populated for a bare probe)
            suites["anchoring_existence"] = _suite("pending", "anchor_absent_this_call",
                                                  "anchor sibling declared in-schema but not populated on this call "
                                                  "(absent-not-null) — needs a fully-signed request to anchor")
            suites["anchoring_precedence"] = _suite("pending", "existence_not_yet_established",
                                                   "no anchor populated on this call, so pre-outcome ordering is not assertable here")
        else:
            suites["anchoring_existence"] = _suite("fail", "ordering_unanchored", "no external anchor referenced")
            suites["anchoring_precedence"] = _suite("not_assessable", "no_anchor",
                                                   "no external anchor, so pre-outcome ordering cannot be established")
    else:
        # resolve a relative anchor path (e.g. PMI returns "/api/arbiter/anchor") against the fetch origin
        if isinstance(anchor_ep, str) and anchor_ep.startswith("/") and "fetch" in mapping:
            from urllib.parse import urlsplit
            sp = urlsplit(mapping["fetch"]["url"])
            anchor_ep = f"{sp.scheme}://{sp.netloc}{anchor_ep}"
        try:
            astate = _http("GET", anchor_ep) if isinstance(anchor_ep, str) and anchor_ep.startswith("http") else anchor_ep
        except Exception as e:  # noqa: BLE001
            astate = {"status": f"unreachable: {e}"}
        if not isinstance(astate, dict):
            astate = {"status": str(astate)}
        # Some endpoints nest the Bitcoin anchor (e.g. invinoveritas /ledger commitment proofs carry it
        # under commitment_proof.ots_anchor). Descend to the OTS/anchor sub-block if present so the same
        # invariant logic applies to flat (SafeAgent) and nested (invinoveritas) shapes alike.
        if "commitment_proof" in astate and isinstance(astate["commitment_proof"], dict):
            astate = astate["commitment_proof"]
        # descend into the anchor sub-block, mechanism-agnostic: ots_anchor (Bitcoin), or the convergent
        # `anchor` / `timestamp_anchor` sibling (on-chain L2 / CT-log / OTS all use the same shape).
        _anchor_kind = None
        for _sub in ("ots_anchor", "timestamp_anchor", "anchor"):
            if isinstance(astate.get(_sub), dict):
                _anchor_kind = _sub
                astate = astate[_sub]
                break
        # accept either a bare `status` or an explicit `anchor_status` (submitted/confirmed distinction)
        raw_status = astate.get("anchor_status") or astate.get("status", "")
        st = str(raw_status).lower()
        ordering_assertable = astate.get("ordering_assertable")
        method = astate.get("method") or astate.get("mechanism") or ""
        tier = astate.get("tier")
        # precedence flag: True = a forward commitment (made before the outcome was known); False = a
        # confirm-only / backfilled stamp (existence proven, ordering not). Mechanism-agnostic — Bitcoin
        # OTS, on-chain L2 block time, or a CT-style log all carry the same flag. (None = unspecified.)
        precedence = astate.get("precedence")
        # block time of the external anchor, under any standard field name (Bitcoin or on-chain L2)
        _ap = astate.get("accepted_anchor_point") if isinstance(astate.get("accepted_anchor_point"), dict) else {}
        block_time = (astate.get("bitcoin_block_time") or astate.get("anchor_block_time")
                      or astate.get("block_time") or astate.get("block_timestamp")
                      or astate.get("timestamp") or _ap.get("block_time"))
        _tag = (f" [method={method}]" if method else "") + (f" [tier={tier}]" if tier else "")
        # mechanism: WHICH external clock this anchor uses, surfaced as a first-class result field so the
        # board shows that one invariant survives across mechanisms (Bitcoin OTS vs on-chain L2 vs CT-log).
        _src = " ".join(str(x) for x in (method, tier, astate.get("source"), _ap.get("source"),
                                         astate.get("recompute_cmd"), _anchor_kind) if x).lower()
        # existence requires a clock EXTERNAL to the signer. An internal arbitration point with a self-minted
        # timestamp (e.g. PMI's same-key arbiter-anchor) is NOT existence — only an external mechanism counts.
        _external_mech = any(w in _src for w in ("bitcoin", "ots", "opentimestamps", "on-chain", "onchain",
                                                 "arbitrum", "mycelium", "ct-log", "transparency", "l2", "ethereum"))
        if "bitcoin" in _src or "ots" in _src or "opentimestamps" in _src:
            mechanism = "Bitcoin OTS"
        elif "arbitrum" in _src or "mycelium" in _src or "on-chain" in _src or "onchain" in _src:
            chain = "Arbitrum" if "arbitrum" in _src or "mycelium" in _src else None
            mechanism = f"on-chain ({chain})" if chain else "on-chain"
        elif method or tier:
            mechanism = method or tier
        else:
            mechanism = None

        # existence is confirmed when the mechanism says so explicitly ("confirmed"), OR when a real
        # EXTERNAL block time is populated and no status word marks it still in flight. On-chain anchors
        # (Arbitrum/Mycelium) populate a tx + block_time on confirmation without ever emitting the word
        # "confirmed" — a present block_time from an external clock IS the confirmation. An internal
        # arbitration timestamp (no external mechanism) is deliberately NOT enough. (S210)
        _in_flight = any(w in st for w in ("submitted", "pending", "not_submitted", "unconfirmed", "unreachable"))
        confirmed = ("confirmed" in st) or (block_time is not None and not _in_flight and _external_mech)

        # existence: is the commitment externally confirmed by the declared mechanism?
        if confirmed:
            suites["anchoring_existence"] = _suite("pass", None,
                                                  f"externally confirmed{_tag}"
                                                  + (f", block_time {block_time}" if block_time else ""), mechanism)
        else:
            suites["anchoring_existence"] = _suite("pending", "anchor_not_yet_confirmed",
                                                  f"anchor_status={raw_status!r}, ordering_assertable={ordering_assertable} — "
                                                  "submitted but not yet confirmed by an external clock independent of the signer",
                                                  mechanism)

        # precedence: does the accepted anchor point provably precede the terminal outcome?
        if not confirmed:
            suites["anchoring_precedence"] = _suite("pending", "existence_not_yet_established",
                                                   "anchor not yet confirmed, so 'committed before the outcome' is correctly "
                                                   "not yet assertable", mechanism)
        elif precedence is False:
            # confirmed for INTEGRITY, but no forward stamp — proves existence, not ordering
            suites["anchoring_precedence"] = _suite("fail", "existence_only_anchor",
                                                   f"externally confirmed (block_time {block_time}){_tag} but precedence=false — "
                                                   "the commitment's existence is proven, but it is not established as made "
                                                   "BEFORE the outcome (no forward stamp), so 'ordered' is not asserted", mechanism)
        elif block_time and outcome_time:
            ok = block_time < outcome_time
            suites["anchoring_precedence"] = _suite("pass" if ok else "fail",
                                                   None if ok else "late_commitment",
                                                   f"anchor block_time {block_time} strictly-< outcome {outcome_time}{_tag}"
                                                   + ("; precedence=true" if precedence else ""), mechanism)
        elif precedence:
            suites["anchoring_precedence"] = _suite("pass", None,
                                                   f"confirmed forward stamp (precedence=true, block_time {block_time}){_tag} — "
                                                   "committed before the outcome", mechanism)
        else:
            suites["anchoring_precedence"] = _suite("pending", "precedence_not_determinable",
                                                   f"anchor confirmed (existence proven){_tag} but no forward-stamp flag or "
                                                   "terminal_outcome_time to establish pre-outcome ordering", mechanism)

    # ── chain_invariant: the terminal record joins back to the same proposed action ─────────────
    # Reported explicitly (rpelevin): pass when the endpoint exposes a terminal action ref equal to the
    # proposed one; fail when they diverge; not_provided where the endpoint is pre-action only and exposes
    # no terminal join — honest by design (the board publishes which invariants each mechanism satisfies).
    proposed_ref = _dig(gov, fields.get("proposed_action_ref")) if fields.get("proposed_action_ref") else None
    terminal_ref = _dig(gov, fields.get("terminal_action_ref")) if fields.get("terminal_action_ref") else None
    if proposed_ref is None and terminal_ref is None:
        suites["chain_invariant"] = _suite("not_provided", None,
                                          "endpoint is pre-action only; no terminal record exposed to join back to the "
                                          "proposed action (existence/precedence/admission are the assertable axes here)")
    elif proposed_ref is not None and terminal_ref is not None:
        ok = proposed_ref == terminal_ref
        suites["chain_invariant"] = _suite("pass" if ok else "fail",
                                          None if ok else "chain_join_broken",
                                          f"terminal action ref {'==' if ok else '!='} proposed action ref")
    else:
        suites["chain_invariant"] = _suite("not_provided", None,
                                          "only one side of the action chain exposed; cannot recompute the join")

    overall = "pass" if all(s["state"] == "pass" for s in suites.values()) else \
        ("fail" if any(s["state"] == "fail" for s in suites.values()) else "partial")
    return {"endpoint": mapping.get("name"), "overall": overall, "suites": suites,
            "envelope_hash": envelope_hash, "signer_pubkey": pubkey, "sig_scheme": scheme}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: live_check.py <mapping.json>")
        return 2
    mapping = json.loads(Path(argv[0]).read_text())
    r = run(mapping)
    if r["overall"] == "no_governance_block":
        print(f"{r['endpoint']}: NO GOVERNANCE BLOCK — {r.get('detail')} (status={r.get('raw_status')})")
        return 2
    icon = {"pass": "✓", "fail": "✗", "pending": "⏳", "not_provided": "—", "not_assessable": "·",
            "unverified_here": "?", "partial": "◑"}
    print(f"{r['endpoint']}: {r['overall'].upper()}  (signer {str(r['signer_pubkey'])[:16]}…, scheme {r['sig_scheme']})")
    for name, s in r["suites"].items():
        print(f"  {icon.get(s['state'],'?')} {name}: {s['state']} — {s['detail']}")
    return 0 if r["overall"] in ("pass", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
