"""Safe gameplay, bankroll management, and strategy monetization."""

from __future__ import annotations

from services.common import result


class GamesRevenueEngine:
    def kelly_fraction(self, win_probability: float, net_odds: float) -> float:
        if net_odds <= 0:
            return 0.0
        edge = (win_probability * (net_odds + 1) - 1) / net_odds
        return max(0.0, min(edge, 0.05))

    async def plan_wager(self, bankroll_sats: int, win_probability: float, net_odds: float, confidence: float) -> dict:
        fraction = self.kelly_fraction(win_probability, net_odds)
        if confidence < 0.62 or fraction <= 0:
            stake = 0
            action = "skip"
        else:
            stake = int(bankroll_sats * fraction * min(confidence, 0.85))
            action = "wager" if stake > 0 else "skip"
        return result("safe_gameplay", "Safe Autonomous Gameplay", {"action": action, "stake_sats": stake, "kelly_fraction": fraction, "confidence": confidence}, "Strategy sales and profit share, never uncapped bankroll exposure.")

    async def sell_strategy(self, game: str, edge_summary: str, price_sats: int) -> dict:
        return result("strategy_selling", "Game Strategy Selling", {"game": game, "edge_summary": edge_summary, "price_sats": price_sats, "disclaimer": "No guaranteed profit."}, "Marketplace strategy product.")

