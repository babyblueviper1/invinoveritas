#!/usr/bin/env python3
"""Real adapter backend for trustless-ai/semantic-abi's `signed_decision_commitment` relation
(github.com/trustless-ai/semantic-abi, adapters/invinoveritas). NOT a reimplementation --
imports and calls the live, production `compute_decision_ref` from services/proof_signing.py
directly, so this can never silently drift from what invinoveritas actually ships.

The protected relation under test: two REJECT verdicts that differ ONLY in epistemic_basis
("evidence_against" vs "insufficient_evidence" -- see services/review_gates.py) must produce
DIFFERENT decision_refs. Before REVIEW_POLICY_VERSION v18 (commit 56e5999d, 2026-09-04),
epistemic_basis was not in DECISION_REF_PREIMAGE_FIELDS at all -- two such verdicts collapsed to
the IDENTICAL decision_ref, a real, shipped, git-verifiable bug. v18 appended epistemic_basis as
the final preimage field, fixing it.

`compute_decision_ref(fields, preimage_fields=None)` already accepts an explicit preimage_fields
override for exactly this kind of historical recompute (its own docstring: "callers recomputing
an older proof should pass that proof's own decision_ref_preimage_fields so the recompute matches
the policy version that was actually in force when it was issued"). This script uses that real
parameter -- PRE_V18_FIELDS is simply DECISION_REF_PREIMAGE_FIELDS with the documented final
element dropped (confirmed via `git show 56e5999d` -- epistemic_basis was appended as the last
tuple element, nothing else in the tuple changed) -- to replay the actual historical preimage
shape, and the live current tuple for the post-v18 case. Same real function, same real
canonicalization (JCS/RFC 8785 via json.dumps(sort_keys=True)), both times.

Usage: python3 invino_signed_decision_commitment.py <pre_v18|post_v18|post_v18_clean>
Prints JSON: {"ref_evidence_against": "...", "ref_insufficient_evidence": "...", "distinct": bool}

Modes pre_v18/post_v18 replay the ADVERSARIAL pair (epistemic_basis genuinely differs -- the
underlying claim is genuinely different, so the true state is always "should be distinguishable",
never "should look the same"). post_v18_clean is the control: the SAME epistemic_basis on both
sides (no tampering) -- a correct mechanism must report these as identical, proving the checker
isn't just always reporting "different" regardless of input.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.proof_signing import DECISION_REF_PREIMAGE_FIELDS, compute_decision_ref  # noqa: E402

PRE_V18_FIELDS = DECISION_REF_PREIMAGE_FIELDS[:-1]
assert DECISION_REF_PREIMAGE_FIELDS[-1] == "epistemic_basis", (
    "DECISION_REF_PREIMAGE_FIELDS shape changed since v18 -- PRE_V18_FIELDS no longer faithfully "
    "replays the historical pre-v18 tuple by dropping the last element. Fix this script's slice "
    "before trusting its output as a historical replay."
)

# A realistic REJECT payload pair -- identical in every field except epistemic_basis. Values are
# representative, not pulled from a real live verdict (no real artifact_hash exists for this
# synthetic pair), which is the correct construction for a fixture: the TEST is whether the
# preimage mechanism distinguishes the two, not whether either payload is itself a real verdict.
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
