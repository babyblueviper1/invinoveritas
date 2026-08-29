"""Conformance vectors for ../validate.py.

Runs the reference validator against committed fixtures (fixtures/attribution_ledger/)
so the synthetic pass/fail cases named in BUILD_QUEUE.md are actual runnable checks,
not something informally tried once in a shell and never saved. Also exercises the
validator against the real published examples/edges to keep the two in sync -- if
someone edits proposals/attribution-ledger/examples.jsonl without recomputing
entry_id, this test catches it the same way the validator's CLI would.
"""
import unittest

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from validate import (
    find_amendment_families,
    load_jsonl,
    recompute_entry_id,
    validate,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures") + "/"


class TestEntryIdRecompute(unittest.TestCase):
    def test_valid_entry_recomputes_clean(self):
        entries = load_jsonl(FIXTURES + "valid_entries.jsonl")
        result = validate(entries, [])
        self.assertEqual(result.entry_errors, [])

    def test_tampered_entry_id_is_rejected(self):
        entries = load_jsonl(FIXTURES + "tampered_entry_id.jsonl")
        result = validate(entries, [])
        self.assertEqual(len(result.entry_errors), 1)
        self.assertIn("MISMATCH", result.entry_errors[0])

    def test_recompute_is_deterministic(self):
        entries = load_jsonl(FIXTURES + "valid_entries.jsonl")
        e = entries[0]
        self.assertEqual(recompute_entry_id(e), e["entry_id"])
        # recomputing twice must be byte-identical -- a real conformance property,
        # not just "it ran once".
        self.assertEqual(recompute_entry_id(e), recompute_entry_id(e))


class TestActorNotSoleVerifier(unittest.TestCase):
    def test_self_verified_claim_is_rejected(self):
        entries = load_jsonl(FIXTURES + "self_verified.jsonl")
        result = validate(entries, [])
        self.assertEqual(len(result.entry_errors), 1)
        self.assertIn("SOLE verified_by", result.entry_errors[0])

    def test_real_examples_have_no_self_verified_claims(self):
        entries = load_jsonl(os.path.join(os.path.dirname(__file__), "..", "examples.jsonl"))
        result = validate(entries, [])
        self_verify_errors = [e for e in result.entry_errors if "SOLE verified_by" in e]
        self.assertEqual(self_verify_errors, [])


class TestReferentialIntegrity(unittest.TestCase):
    def test_unresolved_edge_is_flagged_but_not_a_hard_error(self):
        edges = load_jsonl(FIXTURES + "unresolved_edges.jsonl")
        result = validate([], edges)
        # UNRESOLVED must be its own distinct outcome, not silently pass and not a
        # hard entry_errors/edge_errors failure either.
        self.assertEqual(len(result.edge_unresolved), 2)  # both source_entry and target unresolved
        self.assertEqual(result.edge_errors, [])

    def test_valid_edge_with_both_endpoints_resolves_clean(self):
        entries = load_jsonl(FIXTURES + "valid_entries_pair.jsonl")
        edges = load_jsonl(FIXTURES + "valid_edges.jsonl")
        result = validate(entries, edges)
        self.assertEqual(result.edge_unresolved, [])
        self.assertEqual(result.edge_errors, [])

    def test_verified_application_edge_without_edge_verified_by_errors(self):
        entries = load_jsonl(FIXTURES + "valid_entries_pair.jsonl")
        edge = {
            "edge_type": "verified_application",
            "source_entry": entries[0]["entry_id"],
            "target": entries[1]["entry_id"],
            "timestamp": "2026-08-29T20:00:00Z",
            "evidence": {"note": "missing edge_verified_by on purpose"},
        }
        result = validate(entries, [edge])
        self.assertEqual(len(result.edge_errors), 1)
        self.assertIn("no edge_verified_by", result.edge_errors[0])

    def test_real_edges_all_resolve(self):
        entries = load_jsonl(os.path.join(os.path.dirname(__file__), "..", "examples.jsonl"))
        edges = load_jsonl(os.path.join(os.path.dirname(__file__), "..", "edges.jsonl"))
        result = validate(entries, edges)
        self.assertEqual(result.edge_unresolved, [])
        self.assertEqual(result.edge_errors, [])


class TestAmendmentFamilyDetection(unittest.TestCase):
    def test_same_content_different_verified_by_is_grouped(self):
        entries = load_jsonl(FIXTURES + "amendment_family.jsonl")
        families = find_amendment_families(entries)
        self.assertEqual(len(families), 1)
        self.assertEqual(len(families[0]), 2)

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
        result = validate(entries, edges)
        self.assertTrue(result.ok, msg=f"entry_errors={result.entry_errors} edge_errors={result.edge_errors}")


if __name__ == "__main__":
    unittest.main()
