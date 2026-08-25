# -*- coding: utf-8 -*-
"""The §5 schemas must constrain the implementation, and the implementation must satisfy them.

A schema written from prose and never run against the emitter is a claim, not a constraint. These
close the loop in BOTH directions -- live output validates, and nonconformant objects are rejected
by the specific clause they violate. A schema that accepts everything validates nothing, which is
the same defect as a conformance test that cannot go red.
"""
from __future__ import annotations

import copy
import json
import os
import sys

import jsonschema
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "services"))

from vantage_resolution import (  # noqa: E402
    ENVELOPE_SCHEMA, PROFILE_A_ENVELOPE, SPEC_ID, SPEC_VERSION, VERDICT_SCHEMA,
    InsufficientObservation, Verdict, encode_for,
)

SCHEMA_DIR = os.path.join(ROOT, "conformance", "erc-8309-vantage", "schema")


def _load(n):
    with open(os.path.join(SCHEMA_DIR, n)) as fh:
        return json.load(fh)


ENV_SCHEMA = _load("erc-8309.envelope.schema.json")
VD_SCHEMA = _load("erc-8309.verdict.schema.json")


def _verdict():
    return Verdict(v1_policy=f"{SPEC_ID}#profile-a", v1_policy_version=SPEC_VERSION,
                   v2_committed_set_digest="sha256:" + "0" * 64,
                   v3_as_of={"basis": "evaluator_local"}, v4_vantage_classes={"rpc": 1},
                   v5_state=InsufficientObservation(inspected_set_digest="sha256:" + "0" * 64,
                                                    inspected_count=0)).to_obj()


def _mut(obj, path, value):
    out = copy.deepcopy(obj)
    ref = out
    for k in path[:-1]:
        ref = ref[k]
    if value is ...:
        ref.pop(path[-1], None)
    else:
        ref[path[-1]] = value
    return out


def test_live_envelope_emitter_satisfies_its_schema():
    """If this fails the schema describes an implementation nobody has."""
    jsonschema.validate(PROFILE_A_ENVELOPE.to_obj(), ENV_SCHEMA)


def test_live_verdict_emitter_satisfies_its_schema():
    jsonschema.validate(_verdict(), VD_SCHEMA)


@pytest.mark.parametrize("path,value,clause", [
    (["schema"], SPEC_ID, "the document id must not resolve as a schema"),
    (["e5_synchrony", "window_basis"], "signed_timestamp", "§5 E5"),
    (["e3_independence", "global"], True, "§5 E3 -- never global"),
    (["e6_evidence_requirements"], [], "§5 E6"),
    (["e1_agreement_object"], ..., "§5 E1 -- the agreed object must be named"),
])
def test_nonconformant_envelopes_are_rejected(path, value, clause):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_mut(PROFILE_A_ENVELOPE.to_obj(), path, value), ENV_SCHEMA)


@pytest.mark.parametrize("path,value,clause", [
    (["v2_committed_set_digest"], 3, "§4.2/V2 -- a commitment, never a count"),
    (["v5", "state"], "resolved-agreement", "§6/§2 -- collapsed forms unrepresentable"),
    (["v3_as_of"], {}, "V3 -- 'as of nothing' is not checkable"),
    (["execution_binding"], "advisory", "§10 -- enforce/observe is declared, not free text"),
    (["v1"], {"policy": "p"}, "V1 -- a policy without a version cannot be pinned"),
])
def test_nonconformant_verdicts_are_rejected(path, value, clause):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_mut(_verdict(), path, value), VD_SCHEMA)


def test_insufficient_observation_requires_its_inspected_set():
    """§9's whole point: 'not found' without a committed enumeration of what WAS inspected is a
    claim about absence with no evidence of the search."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_mut(_verdict(), ["v5"], {"state": "insufficient-observation"}),
                            VD_SCHEMA)


def test_each_schema_names_its_own_serializer_binding():
    """§5 binds the serializer explicitly per schema and never infers it. A schema that does not
    name its own serializer forces every consumer to infer one -- the exact defect the per-schema
    rule was ratified to remove."""
    for schema, expected in ((ENV_SCHEMA, ENVELOPE_SCHEMA), (VD_SCHEMA, VERDICT_SCHEMA)):
        b = schema["x-canonical-serializer"]
        assert b["schema"] == expected
        assert b["serializer"] == "rfc8785-jcs"
        assert b["trailing_byte"] == "none"


def test_the_declared_binding_matches_what_the_implementation_actually_does():
    """The binding is only worth declaring if it is true. RFC 8785 emits no trailing byte; if the
    implementation ever emitted one, the schema would be advertising a serializer it does not use
    and every cross-implementation digest comparison would fail by exactly one byte."""
    for sname in (ENVELOPE_SCHEMA, VERDICT_SCHEMA):
        assert not encode_for(sname, {"b": 2, "a": 1}).endswith(b"\n")


def test_envelope_and_verdict_are_separate_schemas_not_one():
    """Two schemas that share a serializer are still TWO bindings. Collapsing them is inference
    inside an artifact whose own rule forbids it -- the six-vs-seven correction, at schema level."""
    assert ENV_SCHEMA["properties"]["schema"]["const"] == "erc-8309.envelope"
    assert VD_SCHEMA["properties"]["schema"]["const"] == "erc-8309.verdict"
    assert ENV_SCHEMA["$id"] != VD_SCHEMA["$id"]
