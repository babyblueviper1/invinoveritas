# -*- coding: utf-8 -*-
"""Conformance suite for the ERC-8309 vectors consumer.

These are the enforcing vectors for the three normative MUSTs that had NO enforcement surface
until this module existed. The §10 gate reported 16/16 KILLED against
services/vantage_resolution.py, which never touches the vectors artifact -- so bytes_hex-REQUIRED,
adversarial-pair presence, and wrong-serializer-digest rejection could not have been covered by it.

Each test below is paired with a mutant in scripts/vantage_vectors_mutations.py. A test that
cannot go red when its guard is removed is decoration, not coverage -- which is the entire lesson
this round keeps re-teaching.
"""
from __future__ import annotations

import hashlib
import os
import sys

SERVICES = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "services"))
if SERVICES not in sys.path:
    sys.path.insert(0, SERVICES)

from vantage_resolution import SERIALIZER_BINDINGS, encode_for  # noqa: E402
from vantage_vectors_consumer import (  # noqa: E402
    check_binding_set, golden_set_inventory,
)

# v0.3.3 §5 binds `erc-8309.envelope` and `erc-8309.verdict` as two explicit schemas. The document
# id is NOT a schema; using it as one is the six-binding collapse this realignment removed.
SCHEMA = "erc-8309.envelope"
DEMO = {"b": 2, "a": 1}


def _conforming_digest():
    return hashlib.sha256(encode_for(SCHEMA, DEMO)).hexdigest()


def _set(**over):
    d = {
        "schema": SCHEMA,
        "demonstration_object": DEMO,
        "conforming_digest": "sha256:" + _conforming_digest(),
        "failure_digest": "sha256:" + ("0" * 64),
        "vectors": [
            {"serializer": "rfc8785-jcs", "bytes_hex": encode_for(SCHEMA, DEMO).hex()},
            {"serializer": "encode-json-utf8-lf", "bytes_hex": "7b7d0a"},
        ],
    }
    d.update(over)
    return d


def _clauses(bs):
    return [c for c, _ in check_binding_set(bs).rejections]


# --- baseline ---------------------------------------------------------------

def test_a_conforming_set_is_accepted():
    """Without this the suite could pass by rejecting everything, which is its own failure mode."""
    rep = check_binding_set(_set())
    assert rep.ok, rep.as_dict()
    assert rep.accepted == 2


# --- MUST 1: bytes_hex REQUIRED ---------------------------------------------

def test_missing_bytes_hex_is_rejected():
    bs = _set(vectors=[{"serializer": "rfc8785-jcs"},
                       {"serializer": "encode-json-utf8-lf", "bytes_hex": "7b7d0a"}])
    assert "bytes_hex-REQUIRED" in _clauses(bs)


def test_display_only_rendering_is_not_an_acceptable_carrier():
    """The escaped rendering is display-only. A consumer that hashed it would produce a digest
    that is wrong in a way that still looks like a digest -- so a vector carrying ONLY that field
    must be rejected rather than quietly hashed."""
    bs = _set(vectors=[{"serializer": "rfc8785-jcs", "bytes_utf8_display_only": "{\"a\":1}"},
                       {"serializer": "encode-json-utf8-lf", "bytes_hex": "7b7d0a"}])
    assert "display-not-hashable" in _clauses(bs)


def test_malformed_bytes_hex_is_rejected_not_coerced():
    for bad in ("zzzz", "", 123, None):
        bs = _set(vectors=[{"serializer": "rfc8785-jcs", "bytes_hex": bad},
                           {"serializer": "encode-json-utf8-lf", "bytes_hex": "7b7d0a"}])
        assert "bytes_hex-REQUIRED" in _clauses(bs), bad


# --- MUST 2: the adversarial PAIR must be present ---------------------------

def test_dropping_the_pair_is_rejected():
    assert "adversarial-pair-REQUIRED" in _clauses(_set(vectors=_set()["vectors"][:1]))


def test_a_pair_naming_one_serializer_twice_is_not_a_pair():
    """Two vectors under the SAME serializer demonstrate nothing about distinguishability -- the
    property the pair exists to establish."""
    bs = _set(vectors=[{"serializer": "rfc8785-jcs", "bytes_hex": "00"},
                       {"serializer": "rfc8785-jcs", "bytes_hex": "01"}])
    assert "adversarial-pair-REQUIRED" in _clauses(bs)


# --- MUST 3: the wrong-serializer digest MUST be rejected -------------------

def test_failure_digest_equal_to_the_conforming_one_is_rejected():
    """The decisive case: a set whose 'failure' digest is the conforming digest would accept
    wrong-serializer bytes. Rejection is EARNED by recomputing under the bound serializer."""
    assert "wrong-serializer-digest-REJECTED" in _clauses(
        _set(failure_digest="sha256:" + _conforming_digest()))


def test_rejection_must_be_earned_not_asserted():
    """No demonstration object means the recomputation cannot happen, so the rejection could only
    be asserted -- which is what this clause exists to prevent."""
    assert "wrong-serializer-digest-REJECTED" in _clauses(_set(demonstration_object=None))


def test_declared_conforming_digest_must_match_recomputation():
    assert "conforming-digest-mismatch" in _clauses(_set(conforming_digest="sha256:" + "f" * 64))


# --- no defaults ------------------------------------------------------------

def test_unbound_schema_is_rejected_never_defaulted():
    """encode_for raises for an unbound schema; the consumer must not catch that into a pass."""
    assert "no-default-serializer" in _clauses(_set(schema="not.bound.anywhere"))


# --- the inventory Pavlo asked for ------------------------------------------

def test_inventory_reports_three_distinct_states():
    """'needs a conforming set' and 'no denominator yet' must never collapse into one blank --
    that collapse is exactly what let 16/16 read as complete coverage."""
    inv = golden_set_inventory([_set()])
    assert inv["by_binding"][SCHEMA] == "has a conforming set"
    others = [v for k, v in inv["by_binding"].items() if k != SCHEMA]
    assert all(v == "no denominator yet" for v in others)
    assert inv["complete"] is False
    assert inv["bindings_total"] == len(SERIALIZER_BINDINGS)


def test_a_failing_set_reads_as_needs_one_not_as_absent():
    inv = golden_set_inventory([_set(vectors=_set()["vectors"][:1])])
    assert inv["by_binding"][SCHEMA] == "needs a conforming set"
    assert inv["needs_conforming_set"] == 1


def test_inventory_cannot_read_complete_while_bindings_are_unmeasured():
    """The structural version of Pavlo's point: completeness is over ALL bindings, so an inventory
    covering one binding can never print complete."""
    assert golden_set_inventory([_set()])["complete"] is False
    assert golden_set_inventory([])["no_denominator_yet"] == len(SERIALIZER_BINDINGS)


def test_non_list_vectors_field_is_rejected_as_a_missing_pair():
    """Added after mutant V2 SURVIVED the first run of the gate -- a real hole in this suite.

    For a LIST input the len<2 guard is shadowed by the serializer-count guard below it, so
    removing it changes nothing and that part of the mutant is equivalent. For a NON-LIST
    (`None`, a dict, a string) the type guard is the ONLY protection: without it the consumer
    falls through to iterating a non-iterable, the TypeError is swallowed by the broad handler in
    check_binding_set, and the set is reported under the WRONG clause -- a rejection that names
    the wrong MUST is barely better than no rejection at all.
    """
    for bad in (None, {}, "xx", 7):
        bs = _set(vectors=bad)
        assert "adversarial-pair-REQUIRED" in _clauses(bs), f"vectors={bad!r}"
