"""Withdrawal fee cap: never let a fee exceed a fixed percentage of the withdrawal amount."""


def capped_fee(amount_sats: int, requested_fee_sats: int, max_fee_pct: float = 2.0) -> int:
    """Clamp requested_fee_sats to at most max_fee_pct% of amount_sats.

    Never returns a fee larger than the cap, and never a negative fee.
    """
    if amount_sats < 0 or requested_fee_sats < 0:
        raise ValueError("amounts must be non-negative")
    cap = int(amount_sats * max_fee_pct / 100)
    return min(requested_fee_sats, cap)
