"""Vantage-Authority Resolution Profiles for ERC-8309 -- reference CONSUMER implementation.

Companion spec: "Vantage-Authority Resolution Profiles for ERC-8309" draft v0.2.2 (Damon Zwicker;
contributors Tiago Merlini, Jimmy Shi, Pavlo, Fede). Cut 2026-08-23.

WHY THIS FILE EXISTS
--------------------
v0.2.2 §10 names "Fede's /review verdict pipeline (reference consumer; validates A-plus-opt-in-B
composition with disclosed-limitation verdicts and `execution_binding = external`)". At the time
of that cut the claim was ASPIRATIONAL: `/review` carried `execution_binding` and
`vantage_limitation` for real, but nothing anywhere in this codebase consumed an ERC-8309 record
state, Profile A, or a divergence set. A grep for 8309/ccip/divergence returned only unrelated
Hyperliquid reconciliation code.

That is the same class of defect §13 just recorded twice (recompute-kit#17 "landed" -> pending
merge; "as amended" -> proposed) -- a status claim asserting something is canonical when it is
not yet -- except about a REFERENCE ROLE rather than a PR. Rather than report it as a correction
and leave the role unfilled, this module makes the claim true.

WHAT IT IMPLEMENTS
------------------
- The §5 resolution envelope (E1-E6) and verdict bindings (V1-V5).
- §6 output-state taxonomy, with the collapsed forms UNREPRESENTABLE (§2), not merely discouraged.
- Profile A (§7.0, normative default -- resolves nothing).
- Profile B (§7.1, opt-in quorum) with the normative signer-counting rule.
- §9's insufficient-observation proof obligation.
- §6a evaluation identity: immutable-but-supersedable, no implied finality.

CANONICALIZATION -- RESOLVED 2026-08-24, AND THIS MODULE'S OWN FINDING IS WHAT RESOLVED IT
------------------------------------------------------------------------------------------
The v0.2.2 §5 text required "sorted-key UTF-8 with a single trailing LF (`encodeJsonUtf8Lf` /
the family's JCS gate)". Those are not the same function: RFC 8785 JCS emits NO trailing byte, so
the same object digests to unrelated hashes. Raised upstream with worked digests rather than
silently picked.

The group did not treat it as an 8309-local typo -- it was a family-wide fork being run on both
sides without ever being named. Ratified outcome (Merlini proposed, Pavlo sharpened, both
aligned; Jimmy pending on the 8309-specific choice):

    The canonical serializer is bound explicitly per domain/schema and named in that schema
    -- never inferred from purpose or category.

    RFC 8785 JCS (no trailing byte) = digest-of-object form. ERC-8309 envelope, decision_ref,
        crc.claim -- anywhere a digest is compared across implementations.
    encodeJsonUtf8Lf (compact + exactly one LF) = frozen-anchored-blob form. TSEI freeze
        artifacts, recompute-kit -- where the bytes THEMSELVES are the anchored artifact.
        It is NOT JCS and no spec text may call it that.

Inference was rejected for a concrete reason worth keeping: "digest-of-object => JCS" leaks,
because TSEI's LF artifacts are themselves digest inputs, so the heuristic would have pulled TSEI
back into the very ambiguity it exists to be out of. Hence SERIALIZER_BINDINGS below is an
explicit table.

"""
from __future__ import annotations

import hashlib
import json

import rfc8785
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional

SPEC_ID = "erc-8309-vantage-authority-companion"
SPEC_VERSION = "0.2.2"

# --- §5 canonicalization ----------------------------------------------------


def encode_json_utf8_lf(obj: Any) -> bytes:
    """The FROZEN-ANCHORED-BLOB form: sorted-key compact UTF-8 JSON + exactly one trailing LF.

    This is NOT JCS and no spec text may call it that (the original §5 phrasing equating the two
    is the defect this whole split came out of). Its place is contexts where the BYTES THEMSELVES
    are the anchored artifact and the LF is part of that byte contract -- TSEI's frozen artifacts,
    recompute-kit. Retained here, correctly named, so the distinction stays visible in code.
    """
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode("utf-8")


def encode_jcs(obj: Any) -> bytes:
    """The DIGEST-OF-OBJECT form: RFC 8785 JCS, no trailing byte.

    Normative wherever a digest of a JSON object is compared ACROSS implementations, because
    every RFC 8785 library emits no trailing byte -- a spec that says "JCS" but adds one breaks
    all of them by exactly one byte, silently, and only at the moment two implementations first
    try to agree. Already the form `decision_ref` and `crc.claim` use.
    """
    return rfc8785.dumps(obj)


# --- serializer binding, per domain/schema (the ratified architecture) ------
#
# Pavlo's rule, adopted 2026-08-24 after this consumer's own §5 finding surfaced that JCS and
# encodeJsonUtf8Lf differ by exactly one byte (0x0a) and had been conflated in the spec text:
#
#     "The canonical serializer is bound explicitly per domain/schema and named in that schema
#      -- never inferred from purpose or category."
#
# Inferring it ("digest-of-object => JCS") leaks, because TSEI's LF artifacts are THEMSELVES
# digest inputs -- that heuristic would quietly pull TSEI back into the ambiguity it exists to be
# out of. So the binding is an explicit table, not a rule applied to a category.
#
# ERC-8309 envelope => JCS is Merlini's proposal (aligned: Merlini, Pavlo, and this side);
# Jimmy is the remaining word at time of writing, so it is bound in ONE place and flips with one
# line if the group lands elsewhere.
SERIALIZER_BINDINGS = {
    "erc-8309-vantage-authority-companion": "rfc8785-jcs",   # §5 envelope + verdict (this module)
    # §4.2 unsigned-attestation preimage. THE COMPANION HAS TWO BINDINGS, NOT ONE -- surfaced by
    # Damon 2026-08-24 while drafting v0.3, and it was a real gap in this table: the spec already
    # bound this to the LF form (ratified at b9fc7e6) long before the §5 argument happened, so an
    # implementation naming only the envelope binding was itself relying on inference for the
    # other one. The document demonstrates the rule on itself -- two schemas, two serializers,
    # both named, zero inference.
    "ccip.attestation.unsigned.v1": "encode-json-utf8-lf",
    "decision_ref": "rfc8785-jcs",                           # pre-existing, unchanged
    "crc.claim": "rfc8785-jcs",                              # pre-existing, unchanged
    "tsei.frozen-artifact": "encode-json-utf8-lf",           # frozen blob; bytes ARE the artifact
    "recompute-kit.artifact": "encode-json-utf8-lf",
}

_ENCODERS = {"rfc8785-jcs": encode_jcs, "encode-json-utf8-lf": encode_json_utf8_lf}


def encode_for(schema: str, obj: Any) -> bytes:
    """Serialize under the serializer BOUND to this schema. Never infers."""
    try:
        return _ENCODERS[SERIALIZER_BINDINGS[schema]](obj)
    except KeyError:
        raise ValueError(
            f"no canonical serializer is bound for schema {schema!r}. Per the ratified rule the "
            f"serializer is bound explicitly per domain/schema and named in that schema -- it is "
            f"never inferred from purpose or category. Add an explicit binding."
        )


def digest(obj: Any, schema: str = SPEC_ID) -> str:
    """Digest under this schema's bound serializer (ERC-8309 envelope: RFC 8785 JCS)."""
    return "sha256:" + hashlib.sha256(encode_for(schema, obj)).hexdigest()


# --- §3 fault taxonomy ------------------------------------------------------

DivergenceClass = Literal[
    "honest_vantage_conditioned",   # explained by declared conditioning variables -- NOT a fault
    "same_signer_equivocation",     # Byzantine evidence
    "unexplained",                  # Byzantine candidate -- investigate, don't assume
]


@dataclass(frozen=True)
class Attestation:
    """§3: an attestation is a signed message carrying an observation plus metadata.

    Observation identity is (input_hash, namespace, value); attestation identity is separate.
    `signature` of "0x" is the live unsigned case -- structurally ineligible per §4.2.
    """
    input_hash: str
    namespace: str
    value: str
    signer: str
    signature: str
    vantage_class: str
    source_peer: Optional[str] = None   # transport metadata -- excluded from identity by §4.2

    @property
    def observation_id(self) -> tuple:
        return (self.input_hash, self.namespace, self.value)

    def structurally_eligible(self) -> bool:
        """§4.2 structural eligibility: well-formed non-empty 65-byte signature. Necessary,
        not sufficient -- cryptographic eligibility is profile surface and is recomputed at
        commitment time, never inherited from the store."""
        s = self.signature or ""
        if not s.startswith("0x") or s == "0x":
            return False
        return len(s) == 132  # 0x + 130 hex chars == 65 bytes


# --- §6 output-state taxonomy (collapsed forms unrepresentable) -------------


class OutputState:
    """§6 base. §2 requires collapsed forms be UNREPRESENTABLE, not discouraged.

    That is enforced structurally: `Resolved` is a distinct type that is not a subclass of
    `Agreement` and carries no path to become one. There is no `state="agreement"` string a
    caller could assign on a resolved divergence, because the state is the type.
    """
    kind: str = "abstract"

    def to_obj(self) -> dict:
        raise NotImplementedError


@dataclass(frozen=True)
class Agreement(OutputState):
    """§6: genuine observation-level agreement over the committed set."""
    committed_set_digest: str
    kind: str = "agreement"

    def to_obj(self) -> dict:
        return {"state": "agreement", "committed_set_digest": self.committed_set_digest}


@dataclass(frozen=True)
class Divergence(OutputState):
    """§6: preserved, unresolved. The divergence ITSELF is the verified fact (§2 refusal 1)."""
    committed_set_digest: str
    observation_values: tuple
    divergence_class: DivergenceClass
    kind: str = "divergence"

    def to_obj(self) -> dict:
        return {"state": "divergence",
                "committed_set_digest": self.committed_set_digest,
                "observation_values": list(self.observation_values),
                "divergence_class": self.divergence_class}


@dataclass(frozen=True)
class InsufficientObservation(OutputState):
    """§9: MUST carry a committed enumeration of what WAS inspected. 'Not found' without an
    inspected-set commitment is nonconformant."""
    inspected_set_digest: str
    inspected_count: int
    kind: str = "insufficient-observation"

    def to_obj(self) -> dict:
        return {"state": "insufficient-observation",
                "inspected_set_digest": self.inspected_set_digest,
                "inspected_count": self.inspected_count}


@dataclass(frozen=True)
class Resolved(OutputState):
    """§6/V5: an opt-in profile's output. Distinct from agreement BY CONSTRUCTION.

    Carries the committed-set digest INLINE and the full set BY REFERENCE, with a
    retrievability obligation on the emitter (§6 Q2). Retrievability MUST be mechanically
    demonstrated by the conformance vector, never merely declared (§10).
    """
    policy: str
    committed_set_digest: str
    committed_set_ref: str
    conditions: dict
    kind: str = "resolved"

    def to_obj(self) -> dict:
        return {"state": "resolved", "policy": self.policy,
                "committed_set_digest": self.committed_set_digest,
                "committed_set_ref": self.committed_set_ref,
                "conditions": self.conditions}


# --- §5 envelope ------------------------------------------------------------


@dataclass(frozen=True)
class ResolutionEnvelope:
    """§5: every profile MUST publish a declaration containing E1-E6."""
    e1_agreement_object: Literal["observation_set", "resolution_verdict", "action"]
    e2_membership: dict
    e3_independence: dict          # per vantage class (§8) -- never global
    e4_fault_model: dict           # MUST carry finality rule or finality is NOT implied (§5 E4)
    e5_synchrony: dict             # evaluator-local window; MUST NOT be defined over signed ts
    e6_evidence_requirements: list
    schema: str = SPEC_ID
    version: str = SPEC_VERSION

    def __post_init__(self):
        # §5 E5: "Windows MUST NOT be defined over signed timestamps" -- backdating and late
        # arrival are indistinguishable, so a signed-timestamp window collapses them.
        if self.e5_synchrony.get("window_basis") == "signed_timestamp":
            raise ValueError(
                "§5 E5 violation: evaluation window MUST NOT be defined over signed timestamps "
                "-- a late attestation carrying an earlier signed timestamp is indistinguishable "
                "from early evidence. Use an evaluator-local window."
            )
        # §5 E3: independence is declared PER CLASS, never globally.
        if self.e3_independence.get("global") is True:
            raise ValueError(
                "§5 E3 violation: independence is claimed per vantage class (§8), never globally."
            )

    def to_obj(self) -> dict:
        return {"schema": self.schema, "version": self.version,
                "e1_agreement_object": self.e1_agreement_object,
                "e2_membership": self.e2_membership,
                "e3_independence": self.e3_independence,
                "e4_fault_model": self.e4_fault_model,
                "e5_synchrony": self.e5_synchrony,
                "e6_evidence_requirements": list(self.e6_evidence_requirements)}

    def declares_finality(self) -> bool:
        """§5 E4 / §6a: no evaluation carries finality unless the profile declares a rule."""
        return bool(self.e4_fault_model.get("finality_rule"))


# --- V2 committed evidence-set commitment -----------------------------------


def committed_set_digest(attestations: Iterable[Attestation],
                         cryptographically_eligible: Optional[set] = None) -> str:
    """V2: digest over the SORTED, low-s-canonical signatures of the CRYPTOGRAPHICALLY ELIGIBLE
    attestation set. A set commitment, never a count.

    Eligibility is recomputed here at commitment time (§4.2, normative) -- the store is evidence,
    not authority. `cryptographically_eligible` is the profile-surface recovery/validity result;
    when omitted only structural eligibility is applied and the caller is asserting nothing about
    cryptographic validity.
    """
    sigs = sorted(
        a.signature for a in attestations
        if a.structurally_eligible()
        and (cryptographically_eligible is None or a.signature in cryptographically_eligible)
    )
    return digest({"v2_committed_signatures": sigs})


def inspected_set_digest(attestations: Iterable[Attestation]) -> str:
    """§9: commitment over what WAS inspected -- including ineligible rows, since the obligation
    is to enumerate the inspection, not the eligible subset."""
    return digest({"inspected": sorted(
        f"{a.signer}|{a.namespace}|{a.value}|{a.signature}" for a in attestations)})


# --- §3 divergence classification -------------------------------------------


def classify_divergence(attestations: list[Attestation],
                        declared_conditioning: Optional[dict] = None) -> DivergenceClass:
    """§3. Profiles MUST NOT count honest vantage-conditioned divergence toward Byzantine bounds.

    Same-signer equivocation (one signer, conflicting values for one observation identity) is
    Byzantine evidence. Multi-signer divergence is NOT -- that boundary is test-locked in the
    reference implementation (ccip-router#3, 3ce2a76): warn on equivocation, stay silent on
    multi-signer divergence.
    """
    by_signer: dict[str, set] = {}
    for a in attestations:
        by_signer.setdefault(a.signer, set()).add(a.value)
    if any(len(v) > 1 for v in by_signer.values()):
        return "same_signer_equivocation"
    declared = (declared_conditioning or {}).get("vantage_classes") or []
    classes = {a.vantage_class for a in attestations}
    if declared and classes.issubset(set(declared)):
        return "honest_vantage_conditioned"
    return "unexplained"


# --- §7.0 Profile A ---------------------------------------------------------


PROFILE_A_ENVELOPE = ResolutionEnvelope(
    e1_agreement_object="observation_set",
    e2_membership={"judgment": None, "note": "§7.0 A makes no membership judgment"},
    e3_independence={"claimed": False, "note": "§7.0 A assumes no independence"},
    e4_fault_model={"tolerated": [], "finality_rule": None,
                    "note": "§7.0 A claims no fault tolerance; no finality (§6a)"},
    e5_synchrony={"window_basis": "evaluator_local"},
    e6_evidence_requirements=["base"],
)


def profile_a_surface(attestations: list[Attestation],
                      declared_conditioning: Optional[dict] = None,
                      min_observations: int = 1) -> OutputState:
    """§7.0 Profile A -- Divergence Surfacing, the normative default. RESOLVES NOTHING.

    Emits the §6 taxonomy minus `resolved`. A is the floor because it composes unconditionally:
    every downstream resolution layer can disclose exactly what it inherited.
    """
    if len(attestations) < min_observations:
        return InsufficientObservation(
            inspected_set_digest=inspected_set_digest(attestations),
            inspected_count=len(attestations))
    values = {a.value for a in attestations}
    dg = committed_set_digest(attestations)
    if len(values) == 1:
        return Agreement(committed_set_digest=dg)
    return Divergence(committed_set_digest=dg,
                      observation_values=tuple(sorted(values)),
                      divergence_class=classify_divergence(attestations, declared_conditioning))


# --- §7.1 Profile B ---------------------------------------------------------


def profile_b_quorum(attestations: list[Attestation], k: int,
                     envelope: ResolutionEnvelope,
                     committed_set_ref: str,
                     cryptographically_eligible: Optional[set] = None) -> OutputState:
    """§7.1 Profile B -- Quorum (opt-in). k-of-n over corroboration of each value.

    NORMATIVE COUNTING RULE: counts DISTINCT SIGNERS PER DECLARED VANTAGE CLASS, never raw
    attestations. Low-s canonicalization collapses one signature's malleability, but a signer
    re-signing the same message under a fresh nonce mints a genuinely distinct attestation the
    base rightly retains -- counting attestations would let one vantage inflate its own weight
    by re-signing. The base retains signed messages; the profile counts signers.

    Returns Resolved ONLY on quorum. Never Agreement -- an auto-resolved disagreement emitted as
    agreement is the §6 "no false green" prohibition, and here it is unrepresentable because
    Resolved is a distinct type.
    """
    eligible = [a for a in attestations if a.structurally_eligible()
                and (cryptographically_eligible is None
                     or a.signature in cryptographically_eligible)]
    if not eligible:
        return InsufficientObservation(
            inspected_set_digest=inspected_set_digest(attestations),
            inspected_count=len(attestations))

    # distinct signers per value, deduplicated per (value, signer) -- never per attestation
    signers_per_value: dict[str, set] = {}
    for a in eligible:
        signers_per_value.setdefault(a.value, set()).add(a.signer)

    dg = committed_set_digest(eligible, cryptographically_eligible)
    winners = [v for v, s in signers_per_value.items() if len(s) >= k]
    if len(winners) != 1:
        # no quorum -> A's own output stands; B resolves nothing here
        return profile_a_surface(attestations)
    return Resolved(
        policy=f"{SPEC_ID}#profile-b-quorum/k={k}",
        committed_set_digest=dg,
        committed_set_ref=committed_set_ref,
        conditions={
            "k": k,
            "distinct_signers": len(signers_per_value[winners[0]]),
            "vantage_classes": sorted({a.vantage_class for a in eligible}),
            "independence_declared": envelope.e3_independence,
            "finality": envelope.e4_fault_model.get("finality_rule"),   # None => not final (§6a)
            "resolved_value": winners[0],
        })


# --- §5 verdict (V1-V5) + §6a evaluation identity ---------------------------


@dataclass(frozen=True)
class Verdict:
    """§5 V1-V5 plus §6a evaluation identity.

    Immutable historical claim, verifiable forever under its original window and evidence. Late
    evidence never mutates it -- it produces a NEW evaluation that MAY supersede this one as the
    current conclusion (§6a). Supersession neither rewrites nor invalidates the superseded claim.
    """
    v1_policy: str
    v1_policy_version: str
    v2_committed_set_digest: str
    v3_as_of: dict
    v4_vantage_classes: dict
    v5_state: OutputState
    supersedes: Optional[str] = None
    execution_binding: str = "external"   # §10 role; we are not in the caller's execution path
    disclosed_limitations: tuple = field(default_factory=tuple)

    def to_obj(self) -> dict:
        return {"schema": SPEC_ID, "version": SPEC_VERSION,
                "v1": {"policy": self.v1_policy, "policy_version": self.v1_policy_version},
                "v2_committed_set_digest": self.v2_committed_set_digest,
                "v3_as_of": self.v3_as_of,
                "v4_vantage_classes": self.v4_vantage_classes,
                "v5": self.v5_state.to_obj(),
                "supersedes": self.supersedes,
                "execution_binding": self.execution_binding,
                "disclosed_limitations": list(self.disclosed_limitations)}

    def evaluation_id(self) -> str:
        """§6a: identity binds the committed evidence set and the window, at production time."""
        return digest(self.to_obj())

    def is_final(self, envelope: ResolutionEnvelope) -> bool:
        """§6a: no evaluation carries finality unless the profile DECLARES a finality rule."""
        return envelope.declares_finality()

    def supersede_with(self, newer: "Verdict") -> "Verdict":
        """§6a: produce a NEW evaluation referencing this one. Never mutates the prior claim."""
        return Verdict(
            v1_policy=newer.v1_policy, v1_policy_version=newer.v1_policy_version,
            v2_committed_set_digest=newer.v2_committed_set_digest,
            v3_as_of=newer.v3_as_of, v4_vantage_classes=newer.v4_vantage_classes,
            v5_state=newer.v5_state, supersedes=self.evaluation_id(),
            execution_binding=newer.execution_binding,
            disclosed_limitations=newer.disclosed_limitations)


def compose_a_plus_optional_b(attestations: list[Attestation],
                              envelope: ResolutionEnvelope,
                              as_of: dict,
                              committed_set_ref: str = "",
                              quorum_k: Optional[int] = None,
                              cryptographically_eligible: Optional[set] = None,
                              declared_conditioning: Optional[dict] = None) -> Verdict:
    """The §10 reference-consumer role: A-plus-opt-in-B composition with disclosed-limitation
    verdicts and `execution_binding = external`.

    A always runs and its output is what B inherits, so the verdict can disclose exactly what was
    inherited (§7.0's composition argument). B is applied only when a quorum k is declared AND
    the envelope actually requires ATTEST-RETAIN (§7.1 E6).
    """
    a_state = profile_a_surface(attestations, declared_conditioning)
    state: OutputState = a_state
    limitations: list[str] = []

    if quorum_k is not None:
        if "ATTEST-RETAIN" not in envelope.e6_evidence_requirements:
            raise ValueError("§7.1 E6 violation: Profile B requires ATTEST-RETAIN in the "
                             "envelope's declared evidence requirements")
        if not committed_set_ref:
            raise ValueError("§6 Q2 violation: resolved(...) carries the full set BY REFERENCE; "
                             "a resolving profile MUST supply a retrievable committed_set_ref")
        state = profile_b_quorum(attestations, quorum_k, envelope, committed_set_ref,
                                 cryptographically_eligible)

    if cryptographically_eligible is None:
        limitations.append(
            "cryptographic_eligibility_not_recomputed: only structural eligibility (§4.2) was "
            "applied; signer-binding was not verified at commitment time")
    if isinstance(a_state, Divergence) and a_state.divergence_class == "unexplained":
        limitations.append(
            "unexplained_divergence: not attributable to a declared conditioning variable; "
            "Byzantine candidate, investigate -- not assumed (§3)")
    if not envelope.declares_finality():
        limitations.append("no_finality_declared: this evaluation is supersedable (§6a)")

    return Verdict(
        v1_policy=SPEC_ID + ("#profile-b-quorum" if quorum_k is not None else "#profile-a"),
        v1_policy_version=SPEC_VERSION,
        v2_committed_set_digest=committed_set_digest(attestations, cryptographically_eligible),
        v3_as_of=as_of,
        v4_vantage_classes={"declared": envelope.e3_independence,
                            "observed": sorted({a.vantage_class for a in attestations})},
        v5_state=state,
        disclosed_limitations=tuple(limitations))
