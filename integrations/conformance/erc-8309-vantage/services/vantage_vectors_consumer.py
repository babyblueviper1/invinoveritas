"""ERC-8309 vantage companion -- conformance consumer for the canonical-form adversarial vectors.

WHY THIS EXISTS (2026-08-24, working group: Damon / Pavlo / Merlini / Jimmy).

The companion's §10 mutation gate reported 16/16 KILLED, and that number was true -- of a scope
that excluded three of the spec's own normative MUSTs. The gate's implementation-under-test is
`services/vantage_resolution.py`, which never touches the vectors artifact at all, so these three
had no enforcing vector anywhere and could not have had one:

    bytes_hex REQUIRED as the normative carrier
    the adversarial PAIR must be present
    the wrong-serializer digest MUST be rejected

Pavlo declined to infer that coverage from the 16/16 count, which was correct: "we looked and
found nothing" and "no observation exists" are different claims and only the second was true.
A fourth obligation from Merlini's map -- an unbound schema MUST raise -- is already banked as
M15 on the resolution module, so THREE are outstanding, not four. (I got that count wrong in
Telegram and Pavlo corrected it; recorded here so the artifact carries the right number.)

This module is the missing enforcement surface. It is deliberately a CONSUMER, not a validator
of convenience: every MUST below is expressed as a path that REJECTS, because a checker that can
only pass proves nothing when mutated. The three mutants land on these rejection paths.

DESIGN RULES, each of which exists because of a specific failure this round already produced:

1. FAIL CLOSED, ALWAYS. Any missing, malformed or unverifiable input is a rejection, never a skip
   and never a warning. §9's own vacuous-digest defect was a checker that reported success over an
   input it had not actually checked.

2. bytes_hex IS THE ONLY HASHABLE CARRIER. A vector may also carry a human-readable rendering, and
   that rendering MUST NOT be hashed. This is why the display field was renamed
   `bytes_utf8_display_only` in v0.1 -- a reader who hashes the escaped form gets a digest that is
   wrong in a way that still looks like a digest.

3. THE ADVERSARIAL PAIR IS STRUCTURAL, NOT DECORATIVE. A binding's vector set proves the two
   serializers are DISTINGUISHABLE. One serialization alone cannot: it is consistent with a world
   where both serializers agree, which is exactly the world the per-schema rule was ratified to
   rule out.

4. THE WRONG-SERIALIZER DIGEST MUST BE REJECTED, and rejection has to be earned rather than
   asserted -- the consumer recomputes under the bound serializer and compares. Accepting a
   failure_digest is the whole defect in one line: a conforming-looking artifact whose bytes were
   produced by a serializer the schema does not bind.

5. NO DEFAULTS. An unbound schema raises out of `encode_for`; this module never catches that into
   a pass.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from vantage_resolution import SERIALIZER_BINDINGS, _ENCODERS, encode_for  # noqa: E402


class VectorRejected(Exception):
    """A vector or binding set failed a normative MUST. Carries the clause it failed."""

    def __init__(self, clause: str, detail: str):
        self.clause = clause
        self.detail = detail
        super().__init__(f"[{clause}] {detail}")


@dataclass
class VectorReport:
    binding: Optional[str] = None
    accepted: int = 0
    rejections: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejections

    def as_dict(self) -> dict:
        return {"binding": self.binding, "accepted": self.accepted, "ok": self.ok,
                "rejections": [{"clause": c, "detail": d} for c, d in self.rejections]}


def _require_bytes_hex(vector: dict) -> bytes:
    """MUST: bytes_hex is the normative carrier. Rule 2 above."""
    if "bytes_hex" not in vector:
        raise VectorRejected(
            "bytes_hex-REQUIRED",
            "vector has no bytes_hex. The hashable carrier is normative; a display rendering is "
            "not a substitute, and hashing one silently yields a wrong-but-plausible digest.")
    raw = vector["bytes_hex"]
    if not isinstance(raw, str) or not raw:
        raise VectorRejected("bytes_hex-REQUIRED", f"bytes_hex must be a non-empty string, got {type(raw).__name__}")
    try:
        out = bytes.fromhex(raw)
    except ValueError as e:
        raise VectorRejected("bytes_hex-REQUIRED", f"bytes_hex is not valid hex: {e}")
    if not out:
        raise VectorRejected("bytes_hex-REQUIRED", "bytes_hex decoded to zero bytes")
    return out


def _reject_display_as_carrier(vector: dict) -> None:
    """MUST NOT: the display rendering is never the hashed input.

    Rejects a vector that carries ONLY the display field, because such a vector cannot be checked
    without hashing something the spec forbids hashing -- and a consumer that quietly hashed it
    would produce a confident wrong answer rather than an error.
    """
    if "bytes_hex" not in vector and any(
            k in vector for k in ("bytes_utf8_display_only", "bytes_utf8", "display")):
        raise VectorRejected(
            "display-not-hashable",
            "vector carries only a display rendering. That field is explicitly display-only; "
            "hashing it produces a digest that is wrong in a way that still looks like a digest.")


def _require_adversarial_pair(binding_set: dict) -> None:
    """MUST: the pair is present. Rule 3 above."""
    vectors = binding_set.get("vectors")
    if not isinstance(vectors, list) or len(vectors) < 2:
        raise VectorRejected(
            "adversarial-pair-REQUIRED",
            f"binding set has {0 if not isinstance(vectors, list) else len(vectors)} vector(s); "
            f"the adversarial PAIR is required. One serialization alone is consistent with the two "
            f"serializers agreeing -- the exact world the per-schema rule exists to rule out.")
    serializers = {v.get("serializer") for v in vectors if isinstance(v, dict)}
    if len(serializers) < 2:
        raise VectorRejected(
            "adversarial-pair-REQUIRED",
            f"all vectors name the same serializer {serializers!r}. A pair that does not span two "
            f"DIFFERENT serializers demonstrates nothing about distinguishability.")


def _require_wrong_serializer_rejected(binding_set: dict) -> None:
    """MUST: a digest produced by the unbound serializer is rejected. Rule 4 above.

    Earned, not asserted: the conforming bytes are recomputed under the BOUND serializer from the
    demonstration object and compared. A set whose failure_digest equals the conforming digest is
    not adversarial at all.

    UPGRADED 2026-08-26 (the LF byte-contract landed in trustless-ai/recompute-kit's
    encode-json-utf8-lf.v0, closing the block this offer -- msg 3233 -- had been waiting on).
    Before this, "differs from the conforming digest" was the entire test, and an arbitrary bogus
    value (the test suite's own placeholder was 64 zero-hex-chars) passed it -- adversarial-LOOKING,
    not adversarial. Now the OTHER serializer in _ENCODERS is recomputed from the SAME
    demonstration_object and failure_digest must equal THAT, not merely differ from conforming.
    This proves failure_digest is genuinely the wrong-serializer's real output on this object,
    not an arbitrary distinguishable value.

    HONEST SCOPE LIMIT, disclosed rather than silently assumed away: `encode_json_utf8_lf` in
    vantage_resolution.py is the simplified, Python-native local form (sort_keys + compact
    separators + trailing LF via json.dumps) -- it is byte-identical to the full
    encode-json-utf8-lf.v0 byte-exact domain contract (ECMAScript number rendering, UTF-16
    surrogate-safe key ordering, negative-zero/out-of-range domain errors) for ordinary
    demonstration objects (plain nested dict/str/int/bool/null, no floats needing ECMAScript-
    specific rendering, no non-ASCII keys needing UTF-16 sort), but this function does NOT
    independently re-derive it via the landed v0 reference encoder's abstract-value model
    (ObjectValue/F64Value/IntegerValue) -- that would need a plain-JSON adapter this module does
    not yet have. A demonstration_object that exercises one of the v0 domain's edge cases would
    not be caught by this upgrade specifically; it would still need the full adapter.
    """
    schema = binding_set.get("schema")
    bound = SERIALIZER_BINDINGS.get(schema)
    if bound is None:
        raise VectorRejected(
            "no-default-serializer",
            f"schema {schema!r} has no bound serializer. Per the ratified rule the binding is "
            f"explicit per schema and never inferred -- a consumer must not pick one.")

    obj = binding_set.get("demonstration_object")
    if obj is None:
        raise VectorRejected(
            "wrong-serializer-digest-REJECTED",
            "no demonstration_object: the rejection cannot be EARNED by recomputation, only "
            "asserted, and an asserted rejection is what this clause exists to prevent.")

    conforming = hashlib.sha256(encode_for(schema, obj)).hexdigest()

    failure = binding_set.get("failure_digest")
    if failure is None:
        raise VectorRejected(
            "wrong-serializer-digest-REJECTED",
            "no failure_digest present; the set cannot demonstrate that a wrong-serializer digest "
            "is distinguishable from the conforming one.")
    failure_norm = str(failure).lower().removeprefix("sha256:")
    if failure_norm == conforming:
        # Distinct clause name from the equality check below, on purpose (found via this
        # module's own mutation gate, 2026-08-26): both checks used to raise the same clause
        # string, so disabling EITHER one individually left the other still catching this
        # specific test input and the mutant SURVIVED -- a real coverage collapse the gate itself
        # caught, the same class of defect this whole module exists to prevent one level up.
        raise VectorRejected(
            "failure-equals-conforming-digest",
            "failure_digest EQUALS the digest recomputed under the bound serializer. The set is "
            "not adversarial: it would accept wrong-serializer bytes as conforming.")

    other_names = [name for name in _ENCODERS if name != bound]
    if len(other_names) != 1:
        raise VectorRejected(
            "no-default-serializer",
            f"expected exactly one alternate serializer besides {bound!r} in the registry, found "
            f"{other_names!r} -- the equality check needs a single unambiguous wrong serializer.")
    wrong_serializer = _ENCODERS[other_names[0]](obj)
    wrong_digest = hashlib.sha256(wrong_serializer).hexdigest()
    if failure_norm != wrong_digest:
        raise VectorRejected(
            "wrong-serializer-digest-REJECTED",
            f"failure_digest does not equal the real {other_names[0]!r} digest of this "
            f"demonstration_object (recomputed sha256:{wrong_digest}). A digest that merely "
            f"differs from conforming is not earned -- it must BE the actual wrong-serializer "
            f"output, or the vector proves nothing about which serializer was used.")

    declared = binding_set.get("conforming_digest")
    if declared is not None and str(declared).lower().removeprefix("sha256:") != conforming:
        raise VectorRejected(
            "conforming-digest-mismatch",
            f"declared conforming_digest does not match recomputation under the bound serializer "
            f"({bound}). Declared {declared}, recomputed sha256:{conforming}.")


def check_binding_set(binding_set: dict) -> VectorReport:
    """Run every normative MUST this surface owns. Never raises -- collects, so one bad clause
    does not hide the others."""
    rep = VectorReport(binding=binding_set.get("schema") if isinstance(binding_set, dict) else None)
    if not isinstance(binding_set, dict):
        rep.rejections.append(("malformed-binding-set", f"expected object, got {type(binding_set).__name__}"))
        return rep

    for check in (_require_adversarial_pair, _require_wrong_serializer_rejected):
        try:
            check(binding_set)
        except VectorRejected as e:
            rep.rejections.append((e.clause, e.detail))
        except Exception as e:  # an unbound schema raising out of encode_for lands here
            rep.rejections.append(("no-default-serializer", str(e)))

    # `or []` is not enough: a truthy non-list (an int, a bare string) would be iterated, and the
    # TypeError would escape a function whose contract is that it NEVER raises. Found by the
    # non-list test added to kill mutant V2 -- the mutant survived because nothing exercised this
    # input shape at all, and the shape turned out to carry a real defect of its own.
    vectors = binding_set.get("vectors")
    for v in (vectors if isinstance(vectors, list) else []):
        if not isinstance(v, dict):
            rep.rejections.append(("malformed-vector", f"expected object, got {type(v).__name__}"))
            continue
        try:
            _reject_display_as_carrier(v)
            _require_bytes_hex(v)
            rep.accepted += 1
        except VectorRejected as e:
            rep.rejections.append((e.clause, e.detail))
    return rep


def golden_set_inventory(binding_sets: list) -> dict:
    """Per-binding golden-set state, in the THREE distinct values Pavlo asked for.

    'needs a conforming set' and 'no denominator yet' must never collapse into one blank: that
    collapse is precisely what let 16/16 read as complete coverage. A binding with no set at all
    is a different state from one whose set exists and is failing, and a reader has to be able to
    tell them apart without reading prose.
    """
    seen = {}
    for bs in binding_sets or []:
        if isinstance(bs, dict) and bs.get("schema"):
            seen[bs["schema"]] = check_binding_set(bs)
    inventory = {}
    for schema in SERIALIZER_BINDINGS:
        rep = seen.get(schema)
        if rep is None:
            inventory[schema] = "no denominator yet"
        elif rep.ok:
            inventory[schema] = "has a conforming set"
        else:
            inventory[schema] = "needs a conforming set"
    return {
        "bindings_total": len(SERIALIZER_BINDINGS),
        "has_conforming_set": sum(1 for v in inventory.values() if v == "has a conforming set"),
        "needs_conforming_set": sum(1 for v in inventory.values() if v == "needs a conforming set"),
        "no_denominator_yet": sum(1 for v in inventory.values() if v == "no denominator yet"),
        "complete": all(v == "has a conforming set" for v in inventory.values()),
        "by_binding": inventory,
    }
