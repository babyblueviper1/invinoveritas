import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fee_cap import capped_fee


def test_fee_within_cap_passes_through():
    assert capped_fee(10_000, 100) == 100


def test_fee_above_cap_is_clamped():
    assert capped_fee(10_000, 5_000, max_fee_pct=2.0) == 200


def test_negative_amount_rejected():
    try:
        capped_fee(-1, 10)
        assert False, "expected ValueError"
    except ValueError:
        pass
