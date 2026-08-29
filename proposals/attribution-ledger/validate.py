"""Attribution-ledger reference validator (this directory, v3).

Closes the "ledger-level gaps" NEXT step flagged in the schema's own README and
BUILD_QUEUE.md: JSON Schema alone can check that a field looks right, but not that a
hash is actually correct, that a pointer resolves, or that a claimant isn't the only
one vouching for their own claim. Those need code with access to the full entry set --
this file is that code.

v2 (2026-08-29, damon:general msg 3727 -- Pavlo's independent review of v1, all four
points confirmed by re-running the exact case he named before fixing anything):
  - v1 composed NOTHING with schema.json/edge-schema.json -- a rehashed entry with
    verified_by=[] recomputed clean and returned ok=True, silently contradicting the
    schema's own minItems:1. This file's `validate()` now runs jsonschema FIRST (a
    schema violation is reported as its own class of error, distinct from a
    ledger-level one, but both roll into the same INVALID status) -- one combined
    entrypoint, not two gates a caller could accidentally run only one of.
  - v1's CLI printed a distinct UNRESOLVED section but still exited 0 / "RESULT: PASS"
    when only edge_unresolved was non-empty, collapsing a genuinely different
    machine-readable state into the same signal as VALID. `ValidationResult.status`
    is now a real tri-state (VALID / UNRESOLVED / INVALID) with its own exit code
    (0 / 2 / 1) so a CI gate can tell "known-good" from "some pointers not resolved
    yet, otherwise clean" from "actually wrong".
  - v1's `find_amendment_families` grouped BYTE-IDENTICAL duplicate entries (same
    verified_by too, hence the same entry_id) under the same "amendment family" label
    as a genuine re-verification -- a duplicate submission is not a supersession
    relationship. Now excludes exact-content groups and classifies the real relation
    (verifier_growth / verifier_shrink / verifier_replace) between the base and each
    later member of each family, rather than a bare list of ids with no relationship
    stated. Ordering the base vs. later members by `timestamp` (v1's approach) turned
    out to be wrong once real fixtures were built: `timestamp` documents when the
    CLAIM was made, not when it was verified, so a genuine amendment (same claim,
    added/changed verifiers) keeps an IDENTICAL timestamp -- sorting by it doesn't
    distinguish earlier from later. Uses the input list's own append order instead,
    which is the real recording order for an append-only JSONL ledger.
  - Dependency declaration: this directory ships requirements.txt (rfc8785==0.1.4,
    jsonschema==4.26.0, pinned to the exact versions this file was verified against)
    so a clean checkout can actually run it, per Pavlo's first point -- CI wiring is
    the repo owner's own follow-up, not something this file can do for itself.
  - Factual correction accepted, not disputed: v1's commit message claimed "no
    safal207 comment exists on crewAIInc/crewAI#4877" -- wrong, caused by an
    unpaginated `gh api` call that only fetched page 1 of a long thread. Re-checked
    with --paginate: safal207 posted a 2026-08-21 comment there addressed to
    @babyblueviper1, linking the exact CML PR #313 fixture. The surface fix itself
    (mapping to safal207/Causal-Memory-Layer#313, since that PR is the actual
    verification artifact) stands; only the "no comment exists" rationale was wrong,
    and is retracted here rather than left uncorrected.

Checks (BUILD_QUEUE.md's numbered list, same order):
  1. entry_id recompute -- reject a pattern-valid-but-wrong digest.
  2. Referential integrity -- edges' source_entry/target must resolve to a real
     entry_id. UNRESOLVED is its own distinct outcome, never silently folded into
     "invalid" or "false" -- an edge pointing at an entry not seen yet may be a
     sequencing gap (entry not committed yet), not a fabrication.
  3. actor == sole verified_by is mechanically rejected (JSON Schema can't express an
     array-vs-sibling-field comparison without a $data extension; this is exactly that
     comparison).
  4. Amendment-family detection for the verified_by append-only/supersession question:
     entry_id is content-addressed over verified_by, so adding a verifier to an
     existing claim necessarily mints a new entry_id, not a mutation of the old one.
     This validator does not invent new schema (that's a group decision, not a
     unilateral one) -- it flags entries that share every OTHER field but differ in
     verified_by, classifies HOW they differ (growth/shrink/replace), and leaves the
     `amends` pointer question itself to the group.
  5. This file is itself exercised by tests/test_attribution_ledger_validate.py
     against committed fixture vectors (fixtures/attribution_ledger/).
  0. Schema composition (v2): every entry/edge is checked against schema.json/
     edge-schema.json BEFORE the ledger-level checks run, in the same call.

Usage:
  python3 validate.py --entries examples.jsonl --edges edges.jsonl  (run from proposals/attribution-ledger/)
  (--schema/--edge-schema default to schema.json/edge-schema.json next to --entries/--edges)

Exit codes: 0 = VALID, 2 = UNRESOLVED (no errors, but a pointer doesn't resolve yet),
1 = INVALID (a real schema or ledger-level error).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field

import jsonschema
import rfc8785

ENTRY_PREIMAGE_FIELDS = ["claim", "actor", "verified_by", "timestamp", "surface", "type", "evidence"]
SAME_CONTENT_FAMILY_FIELDS = ["claim", "actor", "timestamp", "surface", "type", "evidence"]


def _entry_id_preimage_bytes(entry: dict) -> bytes:
    preimage = {k: entry[k] for k in ENTRY_PREIMAGE_FIELDS}
    return rfc8785.dumps(preimage)


def recompute_entry_id(entry: dict) -> str:
    return "sha256:" + hashlib.sha256(_entry_id_preimage_bytes(entry)).hexdigest()


def _verifier_names(verified_by: list) -> set[str]:
    names = set()
    for v in verified_by:
        if isinstance(v, str):
            names.add(v)
        elif isinstance(v, dict):
            names.add(v.get("name", ""))
    return names


@dataclass
class ValidationResult:
    schema_errors: list[str] = field(default_factory=list)
    entry_errors: list[str] = field(default_factory=list)
    edge_errors: list[str] = field(default_factory=list)
    edge_unresolved: list[str] = field(default_factory=list)
    amendment_families: list[dict] = field(default_factory=list)
    n_entries: int = 0
    n_edges: int = 0

    @property
    def ok(self) -> bool:
        """Legacy boolean -- True only for a hard-clean VALID result. Kept for
        callers that just want a pass/fail bit; prefer `status` for anything that
        needs to distinguish UNRESOLVED from a real failure."""
        return self.status == "VALID"

    @property
    def status(self) -> str:
        if self.schema_errors or self.entry_errors or self.edge_errors:
            return "INVALID"
        if self.edge_unresolved:
            return "UNRESOLVED"
        return "VALID"

    @property
    def exit_code(self) -> int:
        return {"VALID": 0, "UNRESOLVED": 2, "INVALID": 1}[self.status]


def load_jsonl(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def load_schema(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def validate_schema(items: list[dict], schema: dict, kind: str) -> list[str]:
    """Check 0: run every item against its JSON Schema before any ledger-level
    check -- a claim that fails the schema is INVALID regardless of whether its
    entry_id happens to recompute correctly."""
    errors: list[str] = []
    validator = jsonschema.Draft202012Validator(schema)
    for i, item in enumerate(items):
        for err in validator.iter_errors(item):
            errors.append(f"{kind}[{i}] ({item.get('actor', item.get('edge_type', '?'))}): schema violation at {'/'.join(str(p) for p in err.absolute_path) or '(root)'}: {err.message}")
    return errors


def validate_entries(entries: list[dict]) -> tuple[list[str], dict[str, dict]]:
    """Check 1 (entry_id recompute) + check 3 (actor != sole verifier).

    Returns (errors, by_id map of entry_id -> entry for entries whose recomputed id matched).
    """
    errors: list[str] = []
    by_id: dict[str, dict] = {}
    for i, e in enumerate(entries):
        claimed_id = e.get("entry_id", "")
        try:
            computed_id = recompute_entry_id(e)
        except (KeyError, TypeError) as exc:
            errors.append(f"entry[{i}] ({e.get('actor', '?')}): cannot compute entry_id, missing/malformed field: {exc}")
            continue
        if computed_id != claimed_id:
            errors.append(
                f"entry[{i}] ({e.get('actor', '?')}): entry_id MISMATCH -- claimed={claimed_id!r} "
                f"computed={computed_id!r}. Either the content was edited after minting the id, or "
                f"the id was never real. This entry does not verify."
            )
            continue  # a bad-id entry can't be trusted as a target either -- don't index it
        verifiers = _verifier_names(e.get("verified_by", []))
        actor = e.get("actor", "")
        if not verifiers or verifiers == {actor}:
            errors.append(
                f"entry[{i}] ({actor}): verified_by has no verifier distinct from the actor "
                f"({'empty' if not verifiers else 'actor is the SOLE verifier'}) -- a claim cannot "
                f"be its own only confirmation."
            )
            continue
        by_id[claimed_id] = e
    return errors, by_id


def validate_edges(edges: list[dict], entries_by_id: dict[str, dict]) -> tuple[list[str], list[str]]:
    """Check 2: referential integrity. Returns (hard_errors, unresolved_notes) -- kept
    distinct on purpose (BUILD_QUEUE.md #2: UNRESOLVED must be its own state, not
    silently folded into a false/invalid verdict)."""
    errors: list[str] = []
    unresolved: list[str] = []
    for i, edge in enumerate(edges):
        src, tgt = edge.get("source_entry", ""), edge.get("target", "")
        src_ok, tgt_ok = src in entries_by_id, tgt in entries_by_id
        if not src_ok:
            unresolved.append(f"edge[{i}] ({edge.get('edge_type', '?')}): source_entry {src!r} does not resolve to a known entry_id -- UNRESOLVED, not necessarily wrong (may not be committed yet).")
        if not tgt_ok:
            unresolved.append(f"edge[{i}] ({edge.get('edge_type', '?')}): target {tgt!r} does not resolve to a known entry_id -- UNRESOLVED, not necessarily wrong (may not be committed yet).")
        if edge.get("edge_type") == "verified_application":
            if not edge.get("edge_verified_by"):
                errors.append(f"edge[{i}]: verified_application with no edge_verified_by -- the causal link itself is unconfirmed.")
    return errors, unresolved


def _classify_verifier_relation(older_verifiers: set[str], newer_verifiers: set[str]) -> str:
    if older_verifiers == newer_verifiers:
        return "identical_verifiers"  # same content family key, but verified_by round-trips equal -- a duplicate, not an amendment
    if older_verifiers < newer_verifiers:
        return "verifier_growth"  # newer strictly adds verifiers -- the append-only re-verification case
    if newer_verifiers < older_verifiers:
        return "verifier_shrink"  # newer strictly removes verifiers -- e.g. a retracted confirmation
    return "verifier_replace"  # neither a subset of the other -- some added, some removed


def find_amendment_families(entries: list[dict]) -> list[dict]:
    """Check 4: group entries that share every field except verified_by. Excludes
    exact-content duplicates (same verified_by too, hence the same entry_id -- a
    resubmission, not a supersession) and classifies the real relationship between
    the earliest-RECORDED member and each later one. Informational -- does not fail
    validation, since the format has no `amends` field yet to formally express it;
    the classification is what a human (or the group) needs to decide whether it
    should grow one.

    Ordering note: `timestamp` is explicitly "when the claim was made, not when it
    was verified" (schema.json's own field description) -- a real re-verification of
    an existing claim keeps the SAME timestamp, only verified_by changes. So members
    of a real amendment family routinely share an identical timestamp, and sorting by
    it would not distinguish "earlier" from "later". This uses the input list's own
    order instead, which for an append-only JSONL ledger IS the true recording order
    (append order), even though the `timestamp` field itself stays fixed."""
    by_content: dict[str, list[dict]] = {}
    for e in entries:
        try:
            key_bytes = rfc8785.dumps({k: e[k] for k in SAME_CONTENT_FAMILY_FIELDS})
        except (KeyError, TypeError):
            continue
        by_content.setdefault(key_bytes.decode("utf-8"), []).append(e)

    families = []
    for group in by_content.values():
        if len(group) < 2:
            continue
        distinct_ids = {e.get("entry_id") for e in group}
        if len(distinct_ids) < 2:
            continue  # exact duplicates (identical entry_id) -- not an amendment family, a resubmission
        base, *rest = group  # append order, not timestamp order -- see docstring
        base_verifiers = _verifier_names(base.get("verified_by", []))
        members = []
        for later in rest:
            later_verifiers = _verifier_names(later.get("verified_by", []))
            members.append({
                "entry_id": later.get("entry_id", "?"),
                "relation_to_earliest": _classify_verifier_relation(base_verifiers, later_verifiers),
            })
        families.append({"earliest_entry_id": base.get("entry_id", "?"), "later_members": members})
    return families


def validate(
    entries: list[dict],
    edges: list[dict],
    entry_schema: dict | None = None,
    edge_schema: dict | None = None,
) -> ValidationResult:
    result = ValidationResult(n_entries=len(entries), n_edges=len(edges))
    if entry_schema is not None:
        result.schema_errors.extend(validate_schema(entries, entry_schema, "entry"))
    if edge_schema is not None:
        result.schema_errors.extend(validate_schema(edges, edge_schema, "edge"))
    result.entry_errors, entries_by_id = validate_entries(entries)
    result.edge_errors, result.edge_unresolved = validate_edges(edges, entries_by_id)
    result.amendment_families = find_amendment_families(entries)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries", required=True)
    ap.add_argument("--edges", required=True)
    ap.add_argument("--schema", help="defaults to schema.json next to --entries")
    ap.add_argument("--edge-schema", help="defaults to edge-schema.json next to --edges")
    ap.add_argument("--no-schema", action="store_true", help="skip schema composition (ledger-level checks only)")
    args = ap.parse_args()

    entries = load_jsonl(args.entries)
    edges = load_jsonl(args.edges)

    entry_schema = edge_schema = None
    if not args.no_schema:
        schema_path = args.schema or os.path.join(os.path.dirname(args.entries) or ".", "schema.json")
        edge_schema_path = args.edge_schema or os.path.join(os.path.dirname(args.edges) or ".", "edge-schema.json")
        entry_schema = load_schema(schema_path)
        edge_schema = load_schema(edge_schema_path)

    result = validate(entries, edges, entry_schema, edge_schema)

    print(f"entries: {result.n_entries}  edges: {result.n_edges}")
    if result.schema_errors:
        print(f"\nSCHEMA ERRORS ({len(result.schema_errors)}):")
        for err in result.schema_errors:
            print(f"  - {err}")
    if result.entry_errors:
        print(f"\nENTRY ERRORS ({len(result.entry_errors)}):")
        for err in result.entry_errors:
            print(f"  - {err}")
    if result.edge_errors:
        print(f"\nEDGE ERRORS ({len(result.edge_errors)}):")
        for err in result.edge_errors:
            print(f"  - {err}")
    if result.edge_unresolved:
        print(f"\nUNRESOLVED ({len(result.edge_unresolved)}) -- not a failure, a distinct state:")
        for note in result.edge_unresolved:
            print(f"  - {note}")
    if result.amendment_families:
        print(f"\nAMENDMENT FAMILIES ({len(result.amendment_families)}) -- candidates for an `amends` pointer, informational:")
        for fam in result.amendment_families:
            print(f"  - earliest={fam['earliest_entry_id']}")
            for m in fam["later_members"]:
                print(f"      -> {m['entry_id']} ({m['relation_to_earliest']})")

    print(f"\nRESULT: {result.status} "
          f"({len(result.schema_errors)} schema errors, {len(result.entry_errors)} entry errors, "
          f"{len(result.edge_errors)} edge errors, {len(result.edge_unresolved)} unresolved)")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
