"""Conformance vectors for services/vantage_resolution.py against companion spec v0.2.2.

Per §10's mutation-survival gate: every normative MUST maps to at least one mutant a conformant
suite MUST KILL. Each test below names the clause it locks. A test that would still pass with the
guard removed is not a conformance vector -- it is decoration.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.vantage_resolution import (  # noqa: E402
    Agreement, Attestation, Divergence, InsufficientObservation, ResolutionEnvelope, Resolved,
    Verdict, PROFILE_A_ENVELOPE, SERIALIZER_BINDINGS, SPEC_ID, SPEC_VERSION,
    ENVELOPE_SCHEMA, VERDICT_SCHEMA, classify_divergence,
    committed_set_digest, compose_a_plus_optional_b, digest, encode_for, encode_jcs,
    encode_json_utf8_lf, profile_a_surface, profile_b_quorum,
)

SIG_A = "0x" + "a" * 130
SIG_B = "0x" + "b" * 130
SIG_C = "0x" + "c" * 130
SIG_D = "0x" + "d" * 130


def att(signer, value, sig, vantage="client:chrome", peer=None):
    return Attestation(input_hash="0xinput", namespace="ns", value=value, signer=signer,
                       signature=sig, vantage_class=vantage, source_peer=peer)


def _envelope(**over):
    base = dict(
        e1_agreement_object="observation_set",
        e2_membership={"map": "signer->participant"},
        e3_independence={"client_class": "declared"},
        e4_fault_model={"tolerated": ["honest_vantage_conditioned"], "finality_rule": None},
        e5_synchrony={"window_basis": "evaluator_local"},
        e6_evidence_requirements=["base", "ATTEST-RETAIN"],
    )
    base.update(over)
    return ResolutionEnvelope(**base)


# --- §5 canonicalization ----------------------------------------------------

def test_blob_form_is_sorted_key_utf8_with_exactly_one_trailing_lf():
    """The frozen-anchored-blob form. NOT JCS -- naming them the same is the original defect."""
    b = encode_json_utf8_lf({"b": 1, "a": 2})
    assert b == b'{"a":2,"b":1}\n'
    assert b.endswith(b"\n") and not b.endswith(b"\n\n")


def test_the_two_serializers_differ_by_exactly_the_trailing_byte():
    """The interop hazard this consumer surfaced upstream: same object, two forms, two digests.

    Still true and still worth locking -- the resolution was to NAME them distinctly and bind
    per schema, not to make them equal.
    """
    obj = {"artifact": "x", "verdict": "approve"}
    assert encode_json_utf8_lf(obj) == encode_jcs(obj) + b"\n"
    assert hashlib.sha256(encode_jcs(obj)).hexdigest() != \
        hashlib.sha256(encode_json_utf8_lf(obj)).hexdigest()


def test_erc8309_envelope_is_bound_to_jcs_not_the_lf_form():
    """Ratified 2026-08-24: the envelope is a digest compared ACROSS implementations, so it takes
    RFC 8785 JCS -- matching decision_ref. Every JCS library emits no trailing byte; a spec that
    says JCS but adds one breaks all of them by one byte, silently."""
    obj = {"artifact": "x"}
    assert encode_for(ENVELOPE_SCHEMA, obj) == encode_jcs(obj)
    assert not encode_for(ENVELOPE_SCHEMA, obj).endswith(b"\n")
    assert digest(obj) == "sha256:" + hashlib.sha256(encode_jcs(obj)).hexdigest()


def test_frozen_blob_domains_keep_the_lf_form_unchanged():
    """TSEI's freeze contract is the LF form and nothing about it moves -- the split scoped and
    named it, it did not migrate it."""
    obj = {"a": 1}
    for schema in ("tsei.frozen-artifact", "recompute-kit.artifact"):
        assert encode_for(schema, obj) == encode_json_utf8_lf(obj)
        assert encode_for(schema, obj).endswith(b"\n")


def test_preexisting_jcs_domains_are_unchanged():
    """decision_ref and crc.claim were already JCS; the split must not have moved them."""
    for schema in ("decision_ref", "crc.claim"):
        assert SERIALIZER_BINDINGS[schema] == "rfc8785-jcs"


def test_serializer_is_never_inferred_for_an_unbound_schema():
    """Pavlo's rule: bound explicitly per domain/schema, NEVER inferred from purpose or category.

    Inference ("digest-of-object => JCS") leaks, because TSEI's LF artifacts are themselves
    digest inputs -- the heuristic would pull TSEI back into the ambiguity it exists to avoid.
    An unbound schema must fail loudly rather than silently pick.
    """
    with pytest.raises(ValueError, match="never inferred"):
        encode_for("some.new.schema.nobody.bound", {"a": 1})


# --- §2 the three refusals --------------------------------------------------

def test_refusal_1_divergence_is_not_agreement():
    """§2.1 / §6: the divergent state is preserved evidence, not a verdict."""
    s = profile_a_surface([att("s1", "A", SIG_A), att("s2", "B", SIG_B)])
    assert isinstance(s, Divergence)
    assert not isinstance(s, Agreement)
    assert s.to_obj()["state"] == "divergence"


def test_refusal_2_resolved_is_a_distinct_type_from_agreement():
    """§2.2 / V5 / §6 'no false green'. Collapse must be UNREPRESENTABLE (§2), not discouraged:
    Resolved is not a subclass of Agreement and exposes no path to become one."""
    assert not issubclass(Resolved, Agreement)
    assert not issubclass(Agreement, Resolved)
    r = Resolved(policy="p", committed_set_digest="sha256:x", committed_set_ref="ipfs://y",
                 conditions={})
    assert r.to_obj()["state"] == "resolved"
    assert "agreement" not in json.dumps(r.to_obj())


def test_refusal_3_judgment_is_not_execution():
    """§2.3 / §10: a signed verdict is not a claim that the action occurred as approved."""
    v = compose_a_plus_optional_b([att("s1", "A", SIG_A)], _envelope(), as_of={"t": 1})
    assert v.execution_binding == "external"


# --- §3 fault taxonomy ------------------------------------------------------

def test_same_signer_equivocation_is_byzantine_evidence():
    """§3: one signer, conflicting values for one observation identity."""
    assert classify_divergence([att("s1", "A", SIG_A), att("s1", "B", SIG_B)]) == \
        "same_signer_equivocation"


def test_multi_signer_divergence_is_not_flagged_as_equivocation():
    """§3, test-locked in ccip-router#3 (3ce2a76): MUST stay silent on multi-signer divergence."""
    assert classify_divergence([att("s1", "A", SIG_A), att("s2", "B", SIG_B)]) != \
        "same_signer_equivocation"


def test_honest_vantage_conditioned_divergence_is_not_a_fault():
    """§3: profiles MUST NOT count honest vantage-conditioned divergence toward Byzantine bounds."""
    got = classify_divergence(
        [att("s1", "A", SIG_A, "client:chrome"), att("s2", "B", SIG_B, "client:curl")],
        declared_conditioning={"vantage_classes": ["client:chrome", "client:curl"]})
    assert got == "honest_vantage_conditioned"


def test_undeclared_class_divergence_is_unexplained_not_silently_honest():
    """§3: 'unexplained' is a Byzantine CANDIDATE -- investigate, don't assume either way."""
    got = classify_divergence(
        [att("s1", "A", SIG_A, "client:chrome"), att("s2", "B", SIG_B, "network:asn999")],
        declared_conditioning={"vantage_classes": ["client:chrome"]})
    assert got == "unexplained"


# --- §4.2 eligibility -------------------------------------------------------

def test_unsigned_0x_record_is_structurally_ineligible():
    """§4.2 / §11: 'presence is not verification' -- the "0x" case is the live instance."""
    assert att("s1", "A", "0x").structurally_eligible() is False
    assert att("s1", "A", "").structurally_eligible() is False


def test_malformed_length_signature_is_ineligible():
    """§4.2: structural eligibility requires a well-formed non-empty 65-byte value."""
    assert att("s1", "A", "0xdeadbeef").structurally_eligible() is False
    assert att("s1", "A", SIG_A).structurally_eligible() is True


def test_ineligible_rows_never_enter_the_v2_commitment():
    """§4.2: eligibility recomputed at commitment time -- the store is evidence, not authority."""
    d_all = committed_set_digest([att("s1", "A", SIG_A), att("s2", "A", "0x")])
    d_only = committed_set_digest([att("s1", "A", SIG_A)])
    assert d_all == d_only, "an unsigned row must not change the committed set"


def test_cryptographic_eligibility_is_recomputed_not_inherited():
    """§4.2 normative: a structurally-eligible row still fails if not cryptographically eligible."""
    atts = [att("s1", "A", SIG_A), att("s2", "A", SIG_B)]
    assert committed_set_digest(atts, cryptographically_eligible={SIG_A}) != \
        committed_set_digest(atts)


def test_source_peer_is_excluded_from_identity_by_enumeration():
    """§4.2: transport metadata cannot redefine record identity."""
    a = att("s1", "A", SIG_A, peer="peer1")
    b = att("s1", "A", SIG_A, peer="peer2")
    assert committed_set_digest([a]) == committed_set_digest([b])


# --- V2 ---------------------------------------------------------------------

def test_v2_is_a_set_commitment_never_a_count():
    """§5 V2: 'A set commitment, never a count.' Two different sets of equal size must differ."""
    assert committed_set_digest([att("s1", "A", SIG_A), att("s2", "A", SIG_B)]) != \
        committed_set_digest([att("s1", "A", SIG_C), att("s2", "A", SIG_D)])


def test_v2_is_order_independent():
    """§5 V2: digest over the SORTED signatures -- ingest order must not change the commitment."""
    a, b = att("s1", "A", SIG_A), att("s2", "A", SIG_B)
    assert committed_set_digest([a, b]) == committed_set_digest([b, a])


# --- §5 envelope guards -----------------------------------------------------

def test_window_over_signed_timestamps_is_rejected():
    """§5 E5: backdating and late arrival collapse -- the window MUST be evaluator-local."""
    with pytest.raises(ValueError, match="E5"):
        _envelope(e5_synchrony={"window_basis": "signed_timestamp"})


def test_global_independence_claim_is_rejected():
    """§5 E3 / §8: independence is declared per class, never globally."""
    with pytest.raises(ValueError, match="E3"):
        _envelope(e3_independence={"global": True})


def test_no_finality_unless_declared():
    """§5 E4 / §6a: 'No evaluation carries finality unless the profile declares a finality rule.'"""
    v = compose_a_plus_optional_b([att("s1", "A", SIG_A)], _envelope(), as_of={"t": 1})
    assert v.is_final(_envelope()) is False
    assert v.is_final(_envelope(
        e4_fault_model={"tolerated": [], "finality_rule": "2-of-3 commit"})) is True


# --- §7.0 Profile A ---------------------------------------------------------

def test_profile_a_resolves_nothing():
    """§7.0: A emits the §6 taxonomy MINUS resolved, under every input."""
    for atts in ([att("s1", "A", SIG_A)],
                 [att("s1", "A", SIG_A), att("s2", "B", SIG_B)],
                 []):
        assert not isinstance(profile_a_surface(atts), Resolved)


def test_profile_a_envelope_claims_nothing():
    """§7.0: no membership judgment, no independence assumption, no fault tolerance, base only."""
    e = PROFILE_A_ENVELOPE
    assert e.e1_agreement_object == "observation_set"
    assert e.e3_independence["claimed"] is False
    assert e.e4_fault_model["finality_rule"] is None
    assert e.e6_evidence_requirements == ["base"]


def test_agreement_only_on_genuine_observation_level_agreement():
    """§6: agreement is over the committed set, not manufactured."""
    assert isinstance(profile_a_surface([att("s1", "A", SIG_A), att("s2", "A", SIG_B)]), Agreement)


# --- §9 insufficient-observation -------------------------------------------

def test_insufficient_observation_carries_inspected_set_commitment():
    """§9: 'Not found' without an inspected-set commitment is NONCONFORMANT.

    Strengthened after mutant M7 SURVIVED an earlier version of this vector: asserting only
    `startswith("sha256:")` accepts a hardcoded constant that commits to nothing, which is
    precisely the defect §9 exists to forbid. The commitment must actually bind the inspected
    content, so this now pins it against a real recomputation and against distinguishability.
    """
    from services.vantage_resolution import inspected_set_digest

    s = profile_a_surface([])
    assert isinstance(s, InsufficientObservation)
    o = s.to_obj()
    assert o["inspected_set_digest"] == inspected_set_digest([]), "must recompute"
    assert o["inspected_count"] == 0

    # a non-empty inspection that still falls short must commit to what WAS seen, and must be
    # distinguishable from the empty inspection -- a constant digest fails both.
    seen = [att("s1", "A", "0x"), att("s2", "B", "0x")]
    s2 = profile_a_surface(seen, min_observations=3)
    assert isinstance(s2, InsufficientObservation)
    assert s2.inspected_set_digest == inspected_set_digest(seen)
    assert s2.inspected_set_digest != o["inspected_set_digest"], (
        "different inspected sets MUST NOT share a commitment")
    assert s2.inspected_count == 2


# --- §7.1 Profile B: the named attack --------------------------------------

def test_quorum_counts_distinct_signers_not_attestations():
    """§7.1 NORMATIVE, and the exploit it exists to stop: one signer re-signing the same message
    under a fresh nonce mints genuinely distinct attestations the base rightly retains. Counting
    attestations would let ONE vantage manufacture its own quorum."""
    resigned = [att("s1", "A", SIG_A), att("s1", "A", SIG_B), att("s1", "A", SIG_C)]
    out = profile_b_quorum(resigned, k=3, envelope=_envelope(), committed_set_ref="ipfs://x")
    assert not isinstance(out, Resolved), "3 re-signs by ONE signer must not reach k=3"

    genuine = [att("s1", "A", SIG_A), att("s2", "A", SIG_B), att("s3", "A", SIG_C)]
    out2 = profile_b_quorum(genuine, k=3, envelope=_envelope(), committed_set_ref="ipfs://x")
    assert isinstance(out2, Resolved)
    assert out2.conditions["distinct_signers"] == 3


def test_quorum_failure_falls_back_to_profile_a_never_to_agreement():
    """§6 'no false green': a failed resolution must not surface as agreement."""
    atts = [att("s1", "A", SIG_A), att("s2", "B", SIG_B)]
    out = profile_b_quorum(atts, k=2, envelope=_envelope(), committed_set_ref="ipfs://x")
    assert isinstance(out, Divergence)
    assert not isinstance(out, Agreement)


def test_resolved_carries_digest_inline_and_set_by_reference():
    """§6 Q2: digest inline + full set by reference, with a retrievability obligation."""
    genuine = [att("s1", "A", SIG_A), att("s2", "A", SIG_B)]
    out = profile_b_quorum(genuine, k=2, envelope=_envelope(), committed_set_ref="ipfs://cid")
    assert isinstance(out, Resolved)
    o = out.to_obj()
    assert o["committed_set_digest"].startswith("sha256:")
    assert o["committed_set_ref"] == "ipfs://cid"


def test_resolving_profile_without_a_retrievable_ref_is_rejected():
    """§6 Q2: retrievability MUST be mechanically demonstrable; no ref means it cannot be."""
    with pytest.raises(ValueError, match="Q2"):
        compose_a_plus_optional_b([att("s1", "A", SIG_A), att("s2", "A", SIG_B)],
                                  _envelope(), as_of={"t": 1}, quorum_k=2,
                                  committed_set_ref="")


def test_profile_b_requires_attest_retain_declared():
    """§7.1 E6: Profile B requires ATTEST-RETAIN in the envelope's evidence requirements."""
    with pytest.raises(ValueError, match="E6"):
        compose_a_plus_optional_b([att("s1", "A", SIG_A)],
                                  _envelope(e6_evidence_requirements=["base"]),
                                  as_of={"t": 1}, quorum_k=1, committed_set_ref="ipfs://x")


# --- §6a evaluation identity ------------------------------------------------

def test_supersession_does_not_mutate_the_prior_claim():
    """§6a: immutable but supersedable. The superseded claim stays verifiable under its own
    binding; supersession neither rewrites nor invalidates it."""
    old = compose_a_plus_optional_b([att("s1", "A", SIG_A)], _envelope(), as_of={"t": 1})
    old_id, old_obj = old.evaluation_id(), json.loads(json.dumps(old.to_obj()))
    new = compose_a_plus_optional_b([att("s1", "A", SIG_A), att("s2", "A", SIG_B)],
                                    _envelope(), as_of={"t": 2})
    superseding = old.supersede_with(new)
    assert superseding.supersedes == old_id
    assert old.to_obj() == old_obj, "the prior evaluation MUST NOT be mutated"
    assert superseding.evaluation_id() != old_id


def test_evaluation_id_binds_the_committed_evidence_set():
    """§6a: identity binds the exact committed evidence-set digest at production time."""
    a = compose_a_plus_optional_b([att("s1", "A", SIG_A)], _envelope(), as_of={"t": 1})
    b = compose_a_plus_optional_b([att("s1", "A", SIG_A), att("s2", "A", SIG_B)],
                                  _envelope(), as_of={"t": 1})
    assert a.evaluation_id() != b.evaluation_id()


# --- §10 reference-consumer role -------------------------------------------

def test_composition_discloses_what_b_inherited_from_a():
    """§7.0's composition argument: every downstream layer can disclose what it inherited."""
    v = compose_a_plus_optional_b(
        [att("s1", "A", SIG_A, "client:chrome"), att("s2", "B", SIG_B, "network:asn1")],
        _envelope(), as_of={"t": 1},
        declared_conditioning={"vantage_classes": ["client:chrome"]})
    assert any("unexplained_divergence" in d for d in v.disclosed_limitations)


def test_uncrecomputed_cryptographic_eligibility_is_disclosed_not_silent():
    """§4.2 + §10 disclosed-limitation verdicts: never let a weaker check read as a stronger one."""
    v = compose_a_plus_optional_b([att("s1", "A", SIG_A)], _envelope(), as_of={"t": 1})
    assert any("cryptographic_eligibility_not_recomputed" in d for d in v.disclosed_limitations)


def test_verdict_carries_v1_through_v5():
    """§5: every verdict MUST carry V1-V5."""
    v = compose_a_plus_optional_b([att("s1", "A", SIG_A)], _envelope(), as_of={"t": 1, "reg": "r"})
    o = v.to_obj()
    assert o["v1"]["policy"] and o["v1"]["policy_version"] == SPEC_VERSION
    assert o["v2_committed_set_digest"].startswith("sha256:")
    assert o["v3_as_of"] == {"t": 1, "reg": "r"}
    assert "declared" in o["v4_vantage_classes"] and "observed" in o["v4_vantage_classes"]
    assert o["v5"]["state"] in ("agreement", "divergence", "insufficient-observation", "resolved")


def test_verdict_is_canonically_serializable_and_recomputable():
    """§5: consumers recompute the envelope/verdict byte-for-byte."""
    v = compose_a_plus_optional_b([att("s1", "A", SIG_A)], _envelope(), as_of={"t": 1})
    assert encode_json_utf8_lf(v.to_obj()) == encode_json_utf8_lf(v.to_obj())
    assert v.evaluation_id() == v.evaluation_id()


def test_companion_binds_two_schemas_not_one():
    """§5 envelope AND §4.2 unsigned preimage are BOTH bound, to DIFFERENT serializers.

    Gap found 2026-08-24: this table originally named only the envelope binding, which meant an
    implementation of a spec that has two bindings was itself relying on inference for the second
    -- the exact failure the rule forbids, one level down. §4.2's preimage was bound to the LF
    form (ratified b9fc7e6) before the §5 argument even happened.
    """
    assert SERIALIZER_BINDINGS["erc-8309.envelope"] == "rfc8785-jcs"
    assert SERIALIZER_BINDINGS["erc-8309.verdict"] == "rfc8785-jcs"
    assert SERIALIZER_BINDINGS["ccip.attestation.unsigned.v1"] == "encode-json-utf8-lf"
    obj = {"a": 1}
    assert not encode_for(ENVELOPE_SCHEMA, obj).endswith(b"\n")
    assert encode_for("ccip.attestation.unsigned.v1", obj).endswith(b"\n")
    # SPEC_ID names the DOCUMENT and is deliberately NOT a binding: passing it where a schema is
    # expected must RAISE rather than resolve. That is the six-binding collapse, in one assertion.
    with pytest.raises(ValueError):
        encode_for(SPEC_ID, obj)


def test_unsigned_preimage_uses_the_specs_own_named_canonical_object():
    """§4.2: the preimage is a NAMED canonical object, never delimiter concatenation, which is
    not injective over unconstrained fields. Reproduces the spec's field set under its binding."""
    preimage = {"domain": "ccip.attestation.unsigned.v1", "input_hash": "0xin",
                "namespace": "ns", "key": "k", "value": "v", "timestamp": 1}
    b = encode_for("ccip.attestation.unsigned.v1", preimage)
    assert b.endswith(b"\n") and b.count(b"\n") == 1
    assert b.startswith(b'{"domain":')          # sorted keys put domain first here
    # source_peer / signature are excluded from identity BY ENUMERATION (§4.2)
    assert b"source_peer" not in b and b"signature" not in b


def test_binding_table_is_exactly_the_seven_v033_schema_names():
    """Realignment pin (v0.3.3 §5, transcribed from the document bytes -- not from prose about it).

    The published table carried SIX bindings, collapsing `erc-8309.envelope` and
    `erc-8309.verdict` into one `erc-8309-vantage-authority-companion` entry (found Pavlo, from
    the generated artifacts). That collapse was inference inside the artifact whose own rule is
    "bound explicitly per schema, never inferred". Six = stale, seven = aligned.
    """
    assert set(SERIALIZER_BINDINGS) == {
        "erc-8309.envelope", "erc-8309.verdict",
        "decision_ref", "crc.claim",
        "ccip.attestation.unsigned.v1", "tsei.frozen-artifact", "recompute-kit.artifact",
    }
    assert len(SERIALIZER_BINDINGS) == 7
    assert "erc-8309-vantage-authority-companion" not in SERIALIZER_BINDINGS, \
        "the document id is not a schema binding -- that is the collapse this pin exists to catch"


def test_envelope_and_verdict_are_separate_bindings_not_an_alias():
    """Two schemas that happen to share a serializer are still TWO bindings. If verdict were ever
    resolved via the envelope's entry, the table would be inferring again the moment they diverge."""
    assert ENVELOPE_SCHEMA in SERIALIZER_BINDINGS and VERDICT_SCHEMA in SERIALIZER_BINDINGS
    assert ENVELOPE_SCHEMA != VERDICT_SCHEMA
    obj = {"b": 2, "a": 1}
    assert encode_for(VERDICT_SCHEMA, obj) == encode_for(ENVELOPE_SCHEMA, obj)   # same serializer
    assert not encode_for(VERDICT_SCHEMA, obj).endswith(b"\n")


def test_spec_version_is_pinned_to_the_current_cut_literally():
    """LITERAL, not a self-reference (found Pavlo 2026-08-24). The prior coverage compared emitted
    output to SPEC_VERSION itself, which can only confirm the code agrees with itself -- it can
    never detect that the constant is stale. It sat at "0.2.2" through two cuts for exactly that
    reason. This value flows into the envelope/verdict `version` and the V1 policy version, so a
    stale pin makes every emitted object self-identify as a cut it no longer implements."""
    assert SPEC_VERSION == "0.3.3"


def test_verdict_self_identifies_with_the_verdict_schema_not_the_document_id():
    """Found Pavlo 2026-08-24: the binding table was realigned to §5's seven names while
    Verdict.to_obj() still emitted schema=SPEC_ID. So the table said the document id is not a
    schema, and every verdict on the wire claimed it was one. Aligning the lookup without aligning
    the emitted object leaves the wire format asserting the collapse the realignment removed."""
    v = Verdict(v1_policy="p", v1_policy_version="0.3.3", v2_committed_set_digest="sha256:00",
                v3_as_of={}, v4_vantage_classes={},
                v5_state=InsufficientObservation(inspected_set_digest="sha256:" + "0" * 64,
                                                 inspected_count=0))
    o = v.to_obj()
    assert o["schema"] == "erc-8309.verdict"
    assert o["schema"] != SPEC_ID
    assert o["version"] == "0.3.3"


def test_envelope_self_identifies_with_the_envelope_schema():
    """Same check on the other emitter -- it was already correct, and this pins it so a future
    realignment cannot fix one object and silently leave the other behind."""
    assert PROFILE_A_ENVELOPE.to_obj()["schema"] == "erc-8309.envelope"
