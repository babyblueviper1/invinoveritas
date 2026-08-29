"""Attribution-ledger reference validator (this directory, v3).

Closes the "ledger-level gaps" NEXT step flagged in the schema's own README and
BUILD_QUEUE.md: JSON Schema alone can check that a field looks right, but not that a
hash is actually correct, that a pointer resolves, or that a claimant isn't the only
one vouching for their own claim. Those need code with access to the full entry set --
this file is that code.

Checks (BUILD_QUEUE.md's numbered list, same order):
  1. entry_id recompute -- reject a pattern-valid-but-wrong digest.
  2. Referential integrity -- edges' source_entry/target must resolve to a real
     entry_id. UNRESOLVED is its own distinct outcome, never silently folded into
     "invalid" or "false" -- an edge pointing at an entry not seen yet may be a
     sequencing gap (entry not committed yet), not a fabrication.
  3. actor == sole verified_by is mechanically rejected (JSON Schema can't express an
     array-vs-sibling-field comparison without a $data extension; this is exactly that
     comparison).
  4. Same-content-family detection for the verified_by append-only/supersession
     question (BUILD_QUEUE.md's #4, "a real design question, not yet thought
     through"): entry_id is content-addressed over verified_by, so adding a verifier
     to an existing claim necessarily mints a new entry_id, not a mutation of the
     old one. This validator does not invent new schema (that's a group decision,
     not a unilateral one) -- it flags entries that share every OTHER field
     (claim/actor/timestamp/surface/type/evidence) but differ in verified_by, so a
     human can see the amendment relationship and decide whether the format should
     grow an explicit `amends` pointer.
  5. This file is itself exercised by tests/test_attribution_ledger_validate.py
     against committed fixture vectors (fixtures/attribution_ledger/) -- the
     synthetic pass/fail cases from BUILD_QUEUE.md's #5, now runnable, not just
     informally tried once in a shell.

Usage:
  python3 validate.py --entries examples.jsonl --edges edges.jsonl  (run from proposals/attribution-ledger/)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field

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
    entry_errors: list[str] = field(default_factory=list)
    edge_errors: list[str] = field(default_factory=list)
    edge_unresolved: list[str] = field(default_factory=list)
    amendment_families: list[list[str]] = field(default_factory=list)
    n_entries: int = 0
    n_edges: int = 0

    @property
    def ok(self) -> bool:
        return not self.entry_errors and not self.edge_errors


def load_jsonl(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


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
        if verifiers == {actor}:
            errors.append(
                f"entry[{i}] ({actor}): actor is the SOLE verified_by -- a claim cannot be its own "
                f"only confirmation. Needs at least one verifier who isn't {actor!r}."
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


def find_amendment_families(entries: list[dict]) -> list[list[str]]:
    """Check 4: group entries that share every field except verified_by (and
    therefore differ only in entry_id, since verified_by is part of the preimage).
    Informational -- surfaces a real relationship, does not fail validation, since
    the format has no `amends` field yet to formally express it."""
    by_content: dict[str, list[dict]] = {}
    for e in entries:
        try:
            key_bytes = rfc8785.dumps({k: e[k] for k in SAME_CONTENT_FAMILY_FIELDS})
        except (KeyError, TypeError):
            continue
        by_content.setdefault(key_bytes.decode("utf-8"), []).append(e)
    families = []
    for group in by_content.values():
        if len(group) > 1:
            families.append([e.get("entry_id", "?") for e in group])
    return families


def validate(entries: list[dict], edges: list[dict]) -> ValidationResult:
    result = ValidationResult(n_entries=len(entries), n_edges=len(edges))
    result.entry_errors, entries_by_id = validate_entries(entries)
    result.edge_errors, result.edge_unresolved = validate_edges(edges, entries_by_id)
    result.amendment_families = find_amendment_families(entries)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--entries", required=True)
    ap.add_argument("--edges", required=True)
    args = ap.parse_args()

    entries = load_jsonl(args.entries)
    edges = load_jsonl(args.edges)
    result = validate(entries, edges)

    print(f"entries: {result.n_entries}  edges: {result.n_edges}")
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
        print(f"\nSAME-CONTENT FAMILIES ({len(result.amendment_families)}) -- candidates for an `amends` pointer, informational:")
        for fam in result.amendment_families:
            print(f"  - {fam}")

    if result.ok:
        print("\nRESULT: PASS (0 entry errors, 0 edge errors)")
        return 0
    print(f"\nRESULT: FAIL ({len(result.entry_errors)} entry errors, {len(result.edge_errors)} edge errors)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
