"""Conformance vectors for ../validate.py.

Runs the reference validator against committed fixtures (fixtures/attribution_ledger/)
so the synthetic pass/fail cases named in BUILD_QUEUE.md are actual runnable checks,
not something informally tried once in a shell and never saved. Also exercises the
validator against the real published examples/edges to keep the two in sync -- if
someone edits proposals/attribution-ledger/examples.jsonl without recomputing
entry_id, this test catches it the same way the validator's CLI would.

v2 (2026-08-29): four fixtures and their tests added after Pavlo's independent review
(damon:general msg 3727) confirmed four real gaps in v1 -- see
scripts/attribution_ledger_validate.py's own module docstring for the full accounting.
"""
import json
import unittest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from validate import (
    find_amendment_families,
    load_jsonl,
    load_schema,
    recompute_entry_id,
    validate,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures") + "/"
SCHEMA = load_schema(os.path.join(os.path.dirname(__file__), "..", "schema.json"))
EDGE_SCHEMA = load_schema(os.path.join(os.path.dirname(__file__), "..", "edge-schema.json"))


class TestEntryIdRecompute(unittest.TestCase):
    def test_valid_entry_recomputes_clean(self):
        entries = load_jsonl(FIXTURES + "valid_entries.jsonl")
        result = validate(entries, [], SCHEMA, EDGE_SCHEMA)
        self.assertEqual(result.entry_errors, [])
        self.assertEqual(result.status, "VALID")

    def test_tampered_entry_id_is_rejected(self):
        entries = load_jsonl(FIXTURES + "tampered_entry_id.jsonl")
        result = validate(entries, [], SCHEMA, EDGE_SCHEMA)
        self.assertEqual(len(result.entry_errors), 1)
        self.assertIn("MISMATCH", result.entry_errors[0])
        self.assertEqual(result.status, "INVALID")

    def test_recompute_is_deterministic(self):
        entries = load_jsonl(FIXTURES + "valid_entries.jsonl")
        e = entries[0]
        self.assertEqual(recompute_entry_id(e), e["entry_id"])
        self.assertEqual(recompute_entry_id(e), recompute_entry_id(e))


class TestActorNotSoleVerifier(unittest.TestCase):
    def test_self_verified_claim_is_rejected(self):
        entries = load_jsonl(FIXTURES + "self_verified.jsonl")
        result = validate(entries, [], SCHEMA, EDGE_SCHEMA)
        self.assertEqual(len(result.entry_errors), 1)
        self.assertIn("SOLE verifier", result.entry_errors[0])

    def test_real_examples_have_no_self_verified_claims(self):
        entries = load_jsonl(os.path.join(os.path.dirname(__file__), "..", "examples.jsonl"))
        result = validate(entries, [], SCHEMA, EDGE_SCHEMA)
        self_verify_errors = [e for e in result.entry_errors if "SOLE verifier" in e]
        self.assertEqual(self_verify_errors, [])


class TestSchemaComposition(unittest.TestCase):
    """Pavlo's point 3 (msg 3727): schema.json's own minItems:1 on verified_by must
    actually gate the result, not just the ledger-level check."""

    def test_empty_verified_by_fails_schema_even_though_hash_recomputes(self):
        entries = load_jsonl(FIXTURES + "empty_verified_by.jsonl")
        # sanity: the entry_id itself IS correctly recomputed -- the bug this fixture
        # catches is specifically that a correct hash was masking a schema violation.
        self.assertEqual(recompute_entry_id(entries[0]), entries[0]["entry_id"])
        result = validate(entries, [], SCHEMA, EDGE_SCHEMA)
        self.assertTrue(any("minItems" in e or "verified_by" in e for e in result.schema_errors))
        self.assertEqual(result.status, "INVALID")

    def test_schema_composition_is_optional_via_no_schema_equivalent(self):
        # calling validate() without schemas (None, None) must still run the
        # ledger-level checks -- schema composition is additive, not a replacement.
        entries = load_jsonl(FIXTURES + "empty_verified_by.jsonl")
        result = validate(entries, [], None, None)
        self.assertEqual(result.schema_errors, [])
        # the ledger-level check on its own also catches empty verified_by now
        # (v2 tightened `verifiers == {actor}` to `not verifiers or verifiers == {actor}`)
        self.assertEqual(len(result.entry_errors), 1)

    def test_malformed_edge_fails_schema(self):
        bad_edge = {"edge_type": "dependency", "source_entry": "not-a-real-id", "target": "also-not-real", "timestamp": "2026-08-29T20:00:00Z", "evidence": {}}
        result = validate([], [bad_edge], SCHEMA, EDGE_SCHEMA)
        self.assertTrue(len(result.schema_errors) > 0)
        self.assertEqual(result.status, "INVALID")


class TestReferentialIntegrity(unittest.TestCase):
    def test_unresolved_edge_is_flagged_but_not_a_hard_error(self):
        edges = load_jsonl(FIXTURES + "unresolved_edges.jsonl")
        result = validate([], edges, None, EDGE_SCHEMA)
        self.assertEqual(len(result.edge_unresolved), 2)
        self.assertEqual(result.edge_errors, [])
        # this is exactly the tri-state gap Pavlo's point 2 named: UNRESOLVED must be
        # its own status, not silently reported as VALID.
        self.assertEqual(result.status, "UNRESOLVED")
        self.assertEqual(result.exit_code, 2)

    def test_valid_edge_with_both_endpoints_resolves_clean(self):
        entries = load_jsonl(FIXTURES + "valid_entries_pair.jsonl")
        edges = load_jsonl(FIXTURES + "valid_edges.jsonl")
        result = validate(entries, edges, SCHEMA, EDGE_SCHEMA)
        self.assertEqual(result.edge_unresolved, [])
        self.assertEqual(result.edge_errors, [])
        self.assertEqual(result.status, "VALID")

    def test_verified_application_edge_without_edge_verified_by_errors(self):
        entries = load_jsonl(FIXTURES + "valid_entries_pair.jsonl")
        edge = {
            "edge_type": "verified_application",
            "source_entry": entries[0]["entry_id"],
            "target": entries[1]["entry_id"],
            "timestamp": "2026-08-29T20:00:00Z",
            "evidence": {"note": "missing edge_verified_by on purpose"},
        }
        # this also fails schema (edge-schema.json's own if/then requires
        # edge_verified_by for verified_application) -- check both layers fire.
        result = validate(entries, [edge], SCHEMA, EDGE_SCHEMA)
        self.assertTrue(len(result.schema_errors) > 0)
        result_no_schema = validate(entries, [edge], None, None)
        self.assertEqual(len(result_no_schema.edge_errors), 1)
        self.assertIn("no edge_verified_by", result_no_schema.edge_errors[0])

    def test_real_edges_all_resolve(self):
        entries = load_jsonl(os.path.join(os.path.dirname(__file__), "..", "examples.jsonl"))
        edges = load_jsonl(os.path.join(os.path.dirname(__file__), "..", "edges.jsonl"))
        result = validate(entries, edges, SCHEMA, EDGE_SCHEMA)
        self.assertEqual(result.edge_unresolved, [])
        self.assertEqual(result.edge_errors, [])


class TestAmendmentFamilyDetection(unittest.TestCase):
    def test_exact_duplicate_is_not_reported_as_an_amendment_family(self):
        """Pavlo's point 4: byte-identical entries (same verified_by too) are a
        resubmission, not a supersession -- must NOT appear in amendment_families."""
        entries = load_jsonl(FIXTURES + "exact_duplicate.jsonl")
        self.assertEqual(entries[0]["entry_id"], entries[1]["entry_id"])  # sanity: truly identical
        families = find_amendment_families(entries)
        self.assertEqual(families, [])

    def test_verifier_growth_is_classified(self):
        entries = load_jsonl(FIXTURES + "verifier_growth.jsonl")
        families = find_amendment_families(entries)
        self.assertEqual(len(families), 1)
        self.assertEqual(len(families[0]["later_members"]), 1)
        self.assertEqual(families[0]["later_members"][0]["relation_to_earliest"], "verifier_growth")

    def test_verifier_shrink_is_classified(self):
        entries = load_jsonl(FIXTURES + "verifier_shrink.jsonl")
        families = find_amendment_families(entries)
        self.assertEqual(len(families), 1)
        self.assertEqual(families[0]["later_members"][0]["relation_to_earliest"], "verifier_shrink")

    def test_verifier_replace_is_classified(self):
        entries = load_jsonl(FIXTURES + "verifier_replace.jsonl")
        families = find_amendment_families(entries)
        self.assertEqual(len(families), 1)
        self.assertEqual(families[0]["later_members"][0]["relation_to_earliest"], "verifier_replace")

    def test_unrelated_entries_are_not_grouped(self):
        entries = load_jsonl(FIXTURES + "valid_entries_pair.jsonl")
        families = find_amendment_families(entries)
        self.assertEqual(families, [])


class TestRealPublishedLedger(unittest.TestCase):
    """The actual proposals/attribution-ledger/ data, not just fixtures -- catches
    real drift if someone edits an example without recomputing its entry_id."""

    def test_examples_and_edges_validate_clean(self):
        entries = load_jsonl(os.path.join(os.path.dirname(__file__), "..", "examples.jsonl"))
        edges = load_jsonl(os.path.join(os.path.dirname(__file__), "..", "edges.jsonl"))
        result = validate(entries, edges, SCHEMA, EDGE_SCHEMA)
        self.assertEqual(result.status, "VALID", msg=f"schema={result.schema_errors} entry={result.entry_errors} edge={result.edge_errors}")

    def test_examples_are_individually_schema_valid(self):
        entries = load_jsonl(os.path.join(os.path.dirname(__file__), "..", "examples.jsonl"))
        result = validate(entries, [], SCHEMA, None)
        self.assertEqual(result.schema_errors, [])


if __name__ == "__main__":
    unittest.main()
