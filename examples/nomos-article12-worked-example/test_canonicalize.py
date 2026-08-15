#!/usr/bin/env python3
"""Field-order / spacing invariance for the Article-12 fixture fingerprint."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import canonicalize

HERE = Path(__file__).resolve().parent
ART = HERE / "synthetic_fund_transfer_artifact.json"


class TestCanonicalize(unittest.TestCase):
    def setUp(self):
        self.obj = canonicalize.load_artifact(ART)

    def test_insertion_order_does_not_change_fingerprint(self):
        a = canonicalize.fingerprint(self.obj)
        shuffled = {k: self.obj[k] for k in reversed(list(self.obj))}
        self.assertEqual(a, canonicalize.fingerprint(shuffled))

    def test_pretty_print_is_a_different_digest(self):
        import hashlib
        pretty = json.dumps(self.obj, indent=2).encode("utf-8")
        pretty_fp = "sha256:" + hashlib.sha256(pretty).hexdigest()
        self.assertNotEqual(canonicalize.fingerprint(self.obj), pretty_fp)

    def test_float_is_rejected(self):
        bad = dict(self.obj)
        bad["sneak_float"] = 87450.0
        with self.assertRaises(ValueError):
            canonicalize.canonicalize(bad)

    def test_written_fingerprint_matches_recompute(self):
        written = (HERE / "artifact_fingerprint.txt").read_text().strip()
        self.assertEqual(written, canonicalize.fingerprint(self.obj))


if __name__ == "__main__":
    unittest.main()
