#!/usr/bin/env python3
"""Generate the three-party action-binding conformance vectors.

Deterministic: no clock, no randomness, no network. Re-running reproduces byte-identical output,
so any implementation can regenerate and diff rather than trust the committed file.

THE SEAM THESE VECTORS EXIST FOR. Three independent mechanisms bind "what an agent did":

  action_ref     domain-separated hash over (agent_id, action_type, scope)   [argentum-core]
  evidence_ref   the coordinate at which the effect is claimed to be observable
  args_digest    hash of the arguments the action was authorized with

Each is sound in isolation. Each takes its inputs FROM THE PARTY BEING VERIFIED. So a caller who
reports the right SHAPE but the wrong OBJECT produces a record that verifies under all three and
still describes something that did not happen. That is not a flaw in any one mechanism; it is a
property of composing three self-reported coordinates, and it is only visible by cross-reading.

NEGATIVES DECLARE WHY THEY MUST FAIL. Every negative carries expected_reject_reason. "6/6
rejected" is not evidence: a vector that fails to PARSE is rejected for a reason unrelated to the
property it tests, and with four independent implementations a vector can be a real negative under
one parser and a parse error under another while the fixture reports green everywhere. A
conformant runner reports WHICH check rejected, not merely that something did.
"""
import hashlib
import json
import os

H = lambda b: hashlib.sha256(b).hexdigest()
DOMAIN = b"argentum.action_ref.v2\x00"


def jcs(obj):
    """Sorted-key, no-whitespace JSON. Stated explicitly because 'canonical' unqualified is how
    two implementations agree on a word and disagree on bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def action_ref(agent_id, action_type, scope, *, tagged=True, tag_after=False):
    body = jcs({"agent_id": agent_id, "action_type": action_type, "scope": scope})
    if tag_after:                      # collision mode: tag applied AFTER hashing
        return H(DOMAIN + H(body).encode())
    if not tagged:                     # collision mode: bare untagged hash presented as v2
        return H(body)
    return H(DOMAIN + body)


def args_digest(args):
    return H(jcs(args))


def build():
    agent, atype = "agent:treasury-7", "transfer"
    scope = {"chain": "base", "contract": "0xA0b8...eB48", "cap_minor": 5_000_000}
    args = {"to": "0xdead...beef", "amount_minor": 4_200_000}
    other_args = {"to": "0xfeed...face", "amount_minor": 4_200_000}   # same shape, other object

    positives = [{
        "id": "P1-all-three-agree",
        "note": "All three coordinates derive from ONE object. Each check passes alone AND the "
                "cross-read agrees. This is the only shape a conformant record may take.",
        "record": {
            "agent_id": agent, "action_type": atype, "scope": scope, "args": args,
            "action_ref": action_ref(agent, atype, scope),
            "args_digest": args_digest(args),
            "evidence_ref": {"kind": "tx", "chain": "base", "tx_hash": "0x" + "11" * 32},
        },
    }]

    negatives = [
        {
            "id": "N1-right-shape-wrong-object",
            "expected_reject_reason": "cross-coordinate-mismatch",
            "why": "THE SEAM. action_ref and args_digest are each internally valid, but the "
                   "args_digest covers a DIFFERENT object than the one the caller acted on. Every "
                   "mechanism passes in isolation; only cross-reading the coordinates against one "
                   "another catches it. A runner that checks each field independently reports "
                   "this record as conformant.",
            "record": {
                "agent_id": agent, "action_type": atype, "scope": scope, "args": args,
                "action_ref": action_ref(agent, atype, scope),
                "args_digest": args_digest(other_args),
                "evidence_ref": {"kind": "tx", "chain": "base", "tx_hash": "0x" + "11" * 32},
            },
        },
        {
            "id": "N2-untagged-hash-as-v2",
            "expected_reject_reason": "missing-domain-separation",
            "why": "A bare hash of the body presented as a domain-separated v2 action_ref. This is "
                   "the exact collision mode the v1->v2 split was made to close.",
            "record": {
                "agent_id": agent, "action_type": atype, "scope": scope, "args": args,
                "action_ref": action_ref(agent, atype, scope, tagged=False),
                "args_digest": args_digest(args),
                "evidence_ref": {"kind": "tx", "chain": "base", "tx_hash": "0x" + "11" * 32},
            },
        },
        {
            "id": "N3-tag-applied-after-hashing",
            "expected_reject_reason": "domain-tag-not-prefixed",
            "why": "The domain tag is concatenated to the DIGEST rather than prefixed to the "
                   "preimage. It looks domain-separated and provides none of the separation.",
            "record": {
                "agent_id": agent, "action_type": atype, "scope": scope, "args": args,
                "action_ref": action_ref(agent, atype, scope, tag_after=True),
                "args_digest": args_digest(args),
                "evidence_ref": {"kind": "tx", "chain": "base", "tx_hash": "0x" + "11" * 32},
            },
        },
        {
            "id": "N4-evidence-ref-unresolvable",
            "expected_reject_reason": "evidence-not-retrievable",
            "why": "A well-formed coordinate pointing at nothing. ABSENCE IS NOT EVIDENCE OF "
                   "NON-EXECUTION -- the correct verdict is could-not-verify, never 'did not "
                   "happen'. A runner that reports this as a refutation has made a claim the "
                   "record cannot support.",
            "record": {
                "agent_id": agent, "action_type": atype, "scope": scope, "args": args,
                "action_ref": action_ref(agent, atype, scope),
                "args_digest": args_digest(args),
                "evidence_ref": {"kind": "tx", "chain": "base", "tx_hash": "0x" + "ff" * 32},
            },
        },
        {
            "id": "N5-canary-fails-for-the-wrong-reason",
            "expected_reject_reason": "cross-coordinate-mismatch",
            "also_malformed": True,
            "why": "META-CHECK, and the reason expected_reject_reason exists at all. This record "
                   "carries the SAME seam defect as N1 and is ALSO structurally malformed "
                   "(action_ref is not hex). A runner that rejects on the malformed field and "
                   "reports 'rejected' has NOT demonstrated it can detect the seam -- it failed "
                   "for the wrong reason and looks identical in an aggregate pass/fail count. A "
                   "conformant runner must report cross-coordinate-mismatch here, not a parse "
                   "error. If your runner cannot distinguish these, that is the finding.",
            "record": {
                "agent_id": agent, "action_type": atype, "scope": scope, "args": args,
                "action_ref": "not-a-hex-digest",
                "args_digest": args_digest(other_args),
                "evidence_ref": {"kind": "tx", "chain": "base", "tx_hash": "0x" + "11" * 32},
            },
        },
    ]

    return {
        "schema": "three-party-action-binding/v0.1",
        "canonicalization": "sorted-key JSON, separators (',',':'), UTF-8, no trailing byte",
        "domain_tag_hex": DOMAIN.hex(),
        "non_goals": [
            "config_hash / tools-list rug-pull. All three mechanisms here bind THE ACTION. A "
            "rug-pull changes what the action's NAME RESOLVED TO -- a different object -- so no "
            "amount of tightening action-binding can reach it. Stated as a named non-goal rather "
            "than an open item so a green run here is never read as covering it.",
        ],
        "positives": positives,
        "negatives": negatives,
    }


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vectors.json")
    with open(out, "w") as fh:
        json.dump(build(), fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("wrote", out)
