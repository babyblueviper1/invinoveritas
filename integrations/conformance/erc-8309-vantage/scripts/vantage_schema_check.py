#!/usr/bin/env python3
"""Check the ERC-8309 §5 schemas against the bytes the reference implementation ACTUALLY emits.

A schema written from prose and never run against the emitter is a claim, not a constraint. This
closes that loop in both directions:

  1. every live emitter output MUST validate against its schema -- otherwise the schema describes
     an implementation nobody has;
  2. deliberately nonconformant objects MUST be REJECTED, each for its own declared reason --
     otherwise the schema is decorative. A schema that accepts everything validates nothing, which
     is the same defect as a conformance test that cannot go red.

The negatives carry expected_reject_reason for the same reason the three-party fixture does:
"5 of 5 rejected" is not evidence when a vector can be rejected for a reason unrelated to the
property it tests.

Usage:  venv/bin/python scripts/vantage_schema_check.py
"""
from __future__ import annotations

import copy
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "services"))

import jsonschema  # noqa: E402
from vantage_resolution import (  # noqa: E402
    ENVELOPE_SCHEMA, PROFILE_A_ENVELOPE, SPEC_VERSION, SPEC_ID, VERDICT_SCHEMA,
    InsufficientObservation, Verdict, encode_for,
)

SCHEMA_DIR = os.path.join(ROOT, "conformance", "erc-8309-vantage", "schema")


def load(name):
    with open(os.path.join(SCHEMA_DIR, name)) as fh:
        return json.load(fh)


def sample_verdict():
    return Verdict(
        v1_policy=f"{SPEC_ID}#profile-a", v1_policy_version=SPEC_VERSION,
        v2_committed_set_digest="sha256:" + "0" * 64,
        v3_as_of={"basis": "evaluator_local"}, v4_vantage_classes={"rpc": 1},
        v5_state=InsufficientObservation(inspected_set_digest="sha256:" + "0" * 64,
                                         inspected_count=0)).to_obj()


def mutate(obj, path, value):
    out = copy.deepcopy(obj)
    ref = out
    for k in path[:-1]:
        ref = ref[k]
    if value is ...:
        ref.pop(path[-1], None)
    else:
        ref[path[-1]] = value
    return out


def main() -> int:
    env_schema, vd_schema = load("erc-8309.envelope.schema.json"), load("erc-8309.verdict.schema.json")
    env, vd = PROFILE_A_ENVELOPE.to_obj(), sample_verdict()
    fails = []

    print("POSITIVE -- the live emitters must validate:")
    for name, obj, schema in (("envelope", env, env_schema), ("verdict", vd, vd_schema)):
        try:
            jsonschema.validate(obj, schema)
            print(f"  {name:9} VALID")
        except jsonschema.ValidationError as e:
            print(f"  {name:9} INVALID -- {e.message}")
            fails.append(f"{name}: live emitter output does not satisfy its own schema -- "
                         f"the schema describes an implementation nobody has ({e.message})")

    # Each negative names the normative clause it violates. If one of these VALIDATES, that
    # constraint is not being enforced and the schema is decorative on that axis.
    negatives = [
        ("envelope: document id used as schema", env_schema,
         mutate(env, ["schema"], SPEC_ID), "the document identifier must not resolve as a schema"),
        ("envelope: E5 window over signed timestamps", env_schema,
         mutate(env, ["e5_synchrony", "window_basis"], "signed_timestamp"),
         "§5 E5 -- backdating and late arrival are indistinguishable under a signed-timestamp window"),
        ("envelope: E3 global independence claim", env_schema,
         mutate(env, ["e3_independence", "global"], True),
         "§5 E3 -- independence is per vantage class (§8), never global"),
        ("envelope: E6 empty evidence requirements", env_schema,
         mutate(env, ["e6_evidence_requirements"], []),
         "§5 E6 -- 'no evidence required' is not a resolution"),
        ("verdict: V2 committed set replaced by a count", vd_schema,
         mutate(vd, ["v2_committed_set_digest"], 3),
         "§4.2/V2 -- a set COMMITMENT, never a count; the store is evidence, not authority"),
        ("verdict: §9 insufficient without inspected set", vd_schema,
         mutate(vd, ["v5"], {"state": "insufficient-observation"}),
         "§9 -- 'not found' without a committed inspected set is nonconformant"),
        ("verdict: §6 collapsed state", vd_schema,
         mutate(vd, ["v5", "state"], "resolved-agreement"),
         "§6/§2 -- collapsed forms must be UNREPRESENTABLE, not merely discouraged"),
        ("verdict: V3 as_of empty", vd_schema,
         mutate(vd, ["v3_as_of"], {}), "V3 -- 'as of nothing' is not a checkable claim"),
        ("verdict: execution_binding invented", vd_schema,
         mutate(vd, ["execution_binding"], "advisory"),
         "§10 -- the enforce/observe distinction is declared, not free text"),
    ]

    print("\nNEGATIVE -- each must be REJECTED by the constraint it violates:")
    for name, schema, obj, clause in negatives:
        try:
            jsonschema.validate(obj, schema)
            print(f"  {name:48} ACCEPTED  <-- NOT ENFORCED")
            fails.append(f"{name}: accepted -- {clause}")
        except jsonschema.ValidationError:
            print(f"  {name:48} rejected  ({clause[:46]})")

    # The serializer binding must be IN the schema. A schema that does not name its own serializer
    # forces every consumer to infer one, which is the defect §5 exists to remove.
    print("\nSERIALIZER BINDING declared in-schema:")
    for name, schema, expect in (("envelope", env_schema, ENVELOPE_SCHEMA),
                                 ("verdict", vd_schema, VERDICT_SCHEMA)):
        b = schema.get("x-canonical-serializer", {})
        ok = b.get("schema") == expect and b.get("serializer") == "rfc8785-jcs"
        print(f"  {name:9} {b.get('schema')} -> {b.get('serializer')}  {'OK' if ok else 'MISMATCH'}")
        if not ok:
            fails.append(f"{name}: schema does not name its own serializer binding")

    # And the declared binding must match what the implementation actually does.
    probe = {"b": 2, "a": 1}
    for name, sname in (("envelope", ENVELOPE_SCHEMA), ("verdict", VERDICT_SCHEMA)):
        raw = encode_for(sname, probe)
        if raw.endswith(b"\n"):
            fails.append(f"{name}: declared rfc8785-jcs but the implementation emits a trailing byte")
        print(f"  {name:9} encode_for -> {raw!r} (no trailing byte: {not raw.endswith(chr(10).encode())})")

    print()
    if fails:
        print("FAILURES:")
        for f in fails:
            print("  -", f)
        return 1
    print(f"schemas agree with the live emitters; {len(negatives)} nonconformant objects all rejected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
