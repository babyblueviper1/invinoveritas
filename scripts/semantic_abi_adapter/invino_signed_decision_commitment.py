#!/usr/bin/env python3
"""Standalone, runnable backend for trustless-ai/semantic-abi's `signed_decision_commitment`
relation (github.com/trustless-ai/semantic-abi, adapters/invinoveritas).

PROVENANCE (read before trusting this file): `compute_decision_ref` and
`DECISION_REF_PREIMAGE_FIELDS` below are a VERBATIM, hash-citable copy of the real,
production functions in invinoveritas's private repo, services/proof_signing.py, at commit
56e5999d13dbcf4720a67a4a079123301f9d290e (that file's own sha256 at that commit:
feaa396241a9332080fc4fb686b10e6ca6d442eb4a5f3454a88e36748942cffe -- ask babyblueviper1 to
reproduce this hash if you want independent confirmation the copy below wasn't altered; the
private repo is not itself network-fetchable, unlike the nenrin_ring_reimpl adapter case, so a
hash citation is the honest substitute here, not a live import). This is a VENDORED COPY, not a
network call and not a reimplementation from a spec -- the distinction matters for how much
trust to place in it: it establishes "this is genuinely what the production code does" only as
strongly as the hash citation above can be independently checked.

THE PROTECTED RELATION UNDER TEST: two REJECT verdicts differing ONLY in epistemic_basis
("evidence_against" | "insufficient_evidence" -- a deterministic-engine finding vs. a mere
confidence-floor escalation, semantically distinct situations) MUST produce DIFFERENT
decision_refs -- an agent consuming only the lightweight decision_ref (not the full signed
event) needs to be able to tell them apart. That's an ADVERSARIAL pair: the underlying claim
genuinely differs regardless of which code version processes it, so the true (oracle) state for
this pair is always VIOLATED -- what changes across versions is whether the mechanism correctly
OBSERVES that. A separate CLEAN pair (same epistemic_basis both sides, no tampering) is the
control: oracle=PRESERVED, since nothing should ever distinguish identical input.

THE REAL HISTORICAL BUG: before REVIEW_POLICY_VERSION v18 (commit 56e5999d, 2026-09-04),
epistemic_basis was not in DECISION_REF_PREIMAGE_FIELDS at all -- the adversarial pair collapsed
to the IDENTICAL decision_ref (undetected violation). v18 appended epistemic_basis as the tuple's
final element, fixing it. PRE_V18_FIELDS below is simply DECISION_REF_PREIMAGE_FIELDS with that
documented final element dropped (confirmed via `git show 56e5999d` -- epistemic_basis was
appended, nothing else in the tuple changed) -- a faithful replay of the actual historical
preimage shape, not a guess.

Usage: python3 invino_signed_decision_commitment.py <pre_v18|post_v18|post_v18_clean>
Prints JSON: {"ref_evidence_against": "...", "ref_insufficient_evidence": "...", "distinct": bool}
"""
from __future__ import annotations

import hashlib
import json
import sys

# ---- verbatim copy, services/proof_signing.py @ 56e5999d (see provenance note above) ----

DECISION_REF_PREIMAGE_FIELDS = ("artifact_hash", "artifact_type", "policy_version", "verdict", "source_class",
                                "vantage_limitation", "related_decision_ref", "intended_audience",
                                "confidentiality_tier", "disclosed_summary", "intended_verifier",
                                "policy_commitment", "verified_at", "registry_as_of",
                                "registry_snapshot_sha256", "action_binding_tool_hash",
                                "action_binding_args_hash", "action_binding_agent_id",
                                "action_binding_nonce", "freshness_beacon_hash", "epistemic_basis")


def compute_decision_ref(fields: dict, preimage_fields: tuple[str, ...] | None = None) -> str:
    """decision_ref = sha256(JCS({...})) -- see DECISION_REF_PREIMAGE_FIELDS for the field list.
    `preimage_fields` defaults to the current policy's field list; passing an older proof's own
    decision_ref_preimage_fields recomputes against the policy version in force when it issued."""
    fields_to_use = preimage_fields or DECISION_REF_PREIMAGE_FIELDS
    preimage = {k: fields.get(k) for k in fields_to_use}
    canon = json.dumps(preimage, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()

# ---- end verbatim copy ----

PRE_V18_FIELDS = DECISION_REF_PREIMAGE_FIELDS[:-1]
assert DECISION_REF_PREIMAGE_FIELDS[-1] == "epistemic_basis"

# A realistic REJECT payload -- synthetic on purpose (no real artifact_hash exists for this
# fixture): the test is whether the preimage mechanism distinguishes/preserves correctly, not
# whether the payload is a real verdict.
_BASE_FIELDS = {
    "artifact_hash": "sha256:fixture0000000000000000000000000000000000000000000000000000000000",
    "artifact_type": "onchain_action",
    "policy_version": "invinoveritas.review.v18",
    "verdict": "reject",
    "source_class": "agent_reported",
    "vantage_limitation": None,
    "related_decision_ref": None,
    "intended_audience": None,
    "confidentiality_tier": None,
    "disclosed_summary": None,
    "intended_verifier": None,
    "policy_commitment": "sha256:fixturepolicy00000000000000000000000000000000000000000000000000",
    "verified_at": "2026-09-05T00:00:00.000000+00:00",
    "registry_as_of": None,
    "registry_snapshot_sha256": None,
    "action_binding_tool_hash": None,
    "action_binding_args_hash": None,
    "action_binding_agent_id": None,
    "action_binding_nonce": None,
    "freshness_beacon_hash": None,
}


def _pair_refs(preimage_fields: tuple[str, ...], basis_b: str) -> dict:
    fields_a = {**_BASE_FIELDS, "epistemic_basis": "evidence_against"}
    fields_b = {**_BASE_FIELDS, "epistemic_basis": basis_b}
    ref_a = compute_decision_ref(fields_a, preimage_fields=preimage_fields)
    ref_b = compute_decision_ref(fields_b, preimage_fields=preimage_fields)
    return {
        "ref_evidence_against": ref_a,
        "ref_insufficient_evidence": ref_b,
        "distinct": ref_a != ref_b,
    }


def main() -> None:
    modes = ("pre_v18", "post_v18", "post_v18_clean")
    if len(sys.argv) != 2 or sys.argv[1] not in modes:
        print(f"usage: invino_signed_decision_commitment.py <{'|'.join(modes)}>", file=sys.stderr)
        sys.exit(2)
    mode = sys.argv[1]
    if mode == "pre_v18":
        print(json.dumps(_pair_refs(PRE_V18_FIELDS, "insufficient_evidence")))
    elif mode == "post_v18":
        print(json.dumps(_pair_refs(DECISION_REF_PREIMAGE_FIELDS, "insufficient_evidence")))
    else:  # post_v18_clean -- no tampering, same epistemic_basis both sides
        print(json.dumps(_pair_refs(DECISION_REF_PREIMAGE_FIELDS, "evidence_against")))


if __name__ == "__main__":
    main()
