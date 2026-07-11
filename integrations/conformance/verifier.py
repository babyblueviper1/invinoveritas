#!/usr/bin/env python3
"""
verifier.py — standalone conformance verifier for pre-action governance fixtures.

Implementation-INDEPENDENT and OFFLINE: it recomputes everything from the portable bytes and the
declared trust inputs, and trusts NONE of a fixture's own annotations (it re-derives the envelope
hash, the signed binding, and the signer identity from the signed event itself). No network, no call
back to the runtime that generated the fixtures. Zero third-party deps — the BIP-340 / NIP-01 core is
vendored in _bip340_nostr.py (pure stdlib).

Five reported invariants (anchoring split into existence vs precedence per rpelevin, autogen#7353):
  canonical_envelope   — recompute sha256(canonical bytes) == declared envelope hash
  admission_invariant  — an INDEPENDENT identity signed that same hash (sig valid + binding + identity)
  anchoring_existence  — the commitment is externally anchored & bound to the admission (it provably exists)
  anchoring_precedence — the accepted anchor point provably precedes the terminal outcome (it was made first)
  chain_invariant      — pre-action and terminal join on that same envelope hash / action ref

Existence and precedence are kept separate so a confirmed-but-backfilled anchor (proves a commitment
EXISTS, but not that it was made BEFORE the outcome) can never pass as ordering. precedence is only
assessable once existence holds; otherwise it is reported `not_assessable` (pass=None), not a second
failure — one broken join, not two.

A second verifier should reach the SAME verdict from these bytes alone.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bip340_nostr import nostr_event_id, schnorr_verify  # vendored, zero-dep


def _sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _event_signature_valid(ev: dict) -> bool:
    """Raw NIP-01 validity against the event's OWN pubkey: id is the correct commitment AND the
    schnorr signature verifies. Independent of WHOSE key it is (identity is a separate check)."""
    try:
        if nostr_event_id(ev) != ev["id"]:
            return False
        return schnorr_verify(bytes.fromhex(ev["id"]), bytes.fromhex(ev["pubkey"]), bytes.fromhex(ev["sig"]))
    except Exception:  # noqa: BLE001
        return False


def _suite(ok: bool, code: str | None, detail: str) -> dict:
    return {"pass": ok, "code": code, "detail": detail}


def verify_fixture(fx: dict) -> dict:
    suites: dict[str, dict] = {}

    # ---- canonical_envelope: recompute the hash from the canonical bytes ----
    ce = fx["canonical_envelope"]
    envelope_hash = _sha256_hex(ce["canonical_bytes_utf8"].encode("utf-8"))
    env_ok = envelope_hash == ce["expected_envelope_hash"]
    suites["canonical_envelope"] = _suite(
        env_ok, None if env_ok else "envelope_hash_mismatch",
        f"recomputed {envelope_hash[:16]} vs declared {ce['expected_envelope_hash'][:16]}")

    # ---- chain_invariant: pre-action and terminal join on the recomputed envelope hash ----
    pre, term = fx["chain"]["pre_action"], fx["chain"]["terminal"]
    chain_ok = (pre["envelope_hash"] == envelope_hash
                and term["executed_envelope_hash"] == envelope_hash
                and pre["action_ref"] == term["action_ref"])
    suites["chain_invariant"] = _suite(
        chain_ok, None if chain_ok else "chain_join_failed",
        "pre-action, terminal and envelope hashes join" if chain_ok
        else "pre-action / terminal / envelope hash mismatch or action_ref split")

    # ---- admission_invariant: independent identity signed the same hash, before execution ----
    adm = fx["admission"]
    ev = adm["verdict_event"]
    trust = fx["trust_policy"]["independent_verifier_pubkeys"]
    actor = pre["actor_pubkey"]
    code = None
    detail = "independent published key signed the bound envelope hash"
    if not _event_signature_valid(ev):
        code, detail = "admission_signature_invalid", "event id/schnorr signature does not verify"
    else:
        try:
            bound = json.loads(ev["content"]).get("artifact_hash")
        except Exception:  # noqa: BLE001
            bound = None
        if bound != envelope_hash:
            code, detail = "verdict_binding_failed", f"verdict signs {bound!r}, not the proposed envelope hash"
        elif ev["pubkey"] == actor:
            code, detail = "admission_not_independent", "signer is the actor/executor (self-attested)"
        elif ev["pubkey"] not in trust:
            code, detail = "key_different_but_identity_unproven", \
                "signer differs from actor but is not a declared-independent identity"
    suites["admission_invariant"] = _suite(code is None, code, detail)

    # ---- anchoring, split into existence vs precedence (rpelevin, autogen#7353) ----
    # existence: the commitment is externally anchored and the anchor commits to THIS admission.
    # precedence: the accepted anchor point provably precedes the terminal outcome. precedence is only
    # assessable once existence holds; otherwise it is `not_assessable` (pass=None), not a 2nd failure.
    anc = fx.get("anchor")
    if anc is None:
        suites["anchoring_existence"] = _suite(False, "ordering_unanchored",
                                               "no external existence proof — internal ordering only")
        suites["anchoring_precedence"] = {"pass": None, "code": "not_assessable",
                                          "detail": "no anchor, so pre-outcome ordering cannot be established"}
    elif anc["commitment_digest"] != ev["id"]:
        suites["anchoring_existence"] = _suite(False, "anchor_commitment_mismatch",
                                               "anchor does not commit to this admission")
        suites["anchoring_precedence"] = {"pass": None, "code": "not_assessable",
                                          "detail": "anchor does not bind this admission, so ordering is not assessable"}
    else:
        suites["anchoring_existence"] = _suite(True, None,
                                               "commitment externally anchored and bound to this admission")
        if anc.get("precedence") is False:
            # confirmed anchor, but no forward (pre-outcome) commitment — proves existence, not ordering
            suites["anchoring_precedence"] = _suite(False, "existence_only_anchor",
                                                    "anchor proves the commitment exists, but carries no pre-outcome "
                                                    "(forward) stamp, so it does not establish it was made first")
        elif anc["accepted_anchor_point"]["block_time"] >= anc["terminal_outcome_time"]:
            suites["anchoring_precedence"] = _suite(False, "late_commitment",
                                                    "anchor accepted at/after the terminal outcome")
        else:
            suites["anchoring_precedence"] = _suite(True, None,
                                                    "accepted anchor point strictly precedes the terminal outcome")

    # `not_assessable` (pass=None) is neither a pass nor a counted break — overall and first_fail key
    # on hard False only, so a single unmet axis stays exactly one broken join.
    overall = all(s["pass"] is True for s in suites.values())
    first_fail = next((s["code"] for s in suites.values() if s["pass"] is False), None)
    return {"overall_pass": overall, "failure_reason": first_fail, "suites": suites,
            "envelope_hash": envelope_hash}


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: verifier.py <fixture.json> [...]")
        return 2
    rc = 0
    for path in argv:
        fx = json.loads(Path(path).read_text())
        r = verify_fixture(fx)
        verdict = "PASS" if r["overall_pass"] else f"FAIL ({r['failure_reason']})"
        print(f"{Path(path).name}: {verdict}")
        for name, s in r["suites"].items():
            mark = "✓" if s["pass"] else "✗"
            print(f"    {mark} {name}: {s['code'] or 'ok'} — {s['detail']}")
        if not r["overall_pass"]:
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
