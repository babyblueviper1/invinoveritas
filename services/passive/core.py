"""Passive revenue services for reports, signals, rankings, kits, and watches."""

from __future__ import annotations

import random
from typing import Any

from services.common import result, stable_id


class PassiveRevenueEngine:
    """Produce monetizable Bitcoin, Lightning, Nostr, and agent intelligence."""

    async def daily_bitcoin_lightning_report(self, market: dict[str, Any] | None = None) -> dict[str, Any]:
        market = market or {}
        payload = {
            "report_id": stable_id("daily_report", market),
            "sections": ["bitcoin_onchain", "lightning_liquidity", "routing_fees", "agent_opportunities"],
            "signals": {
                "fee_pressure": market.get("fee_pressure", "normal"),
                "liquidity_bias": market.get("liquidity_bias", "balanced"),
                "agent_action": "publish free summary, sell full JSON feed and alerts",
            },
        }
        return result("daily_bitcoin_lightning_report", "Daily Bitcoin & Lightning On-Chain Report", payload, "Free teaser, paid full report subscription.")

    async def nostr_threads_and_signals(self, themes: list[str] | None = None) -> dict[str, Any]:
        themes = themes or ["bitcoin", "lightning", "ai_agents", "market_structure"]
        threads = [
            {"hook": f"{theme}: what changed and how agents can monetize it", "cta": "register free, top up when ready"}
            for theme in themes[:5]
        ]
        return result("nostr_threads_and_signals", "High-Quality Nostr Threads & Signals", {"threads": threads, "daily_target": "3-5"}, "Traffic to marketplace listings and paid signals.")

    async def agent_performance_benchmarks(self, samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        samples = samples or []
        ranked = sorted(samples, key=lambda x: x.get("roi_sats", 0), reverse=True)[:25]
        return result("agent_performance_benchmarks", "Agent Performance Benchmarks", {"leaderboard": ranked, "cadence": "weekly"}, "Paid featured benchmark slots and pro analytics.")

    async def lightning_node_leaderboard(self, nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        nodes = nodes or []
        ranked = sorted(nodes, key=lambda n: (n.get("capacity_sats", 0), n.get("uptime", 0)), reverse=True)[:50]
        return result("lightning_node_leaderboard", "Lightning Node Public Leaderboard + Insights", {"nodes": ranked}, "Sponsored node listings and routing insight subscriptions.")

    async def lightning_dev_digest(self, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        items = items or []
        return result("lightning_dev_digest", "Curated Lightning Development Digest", {"items": items[:20], "cadence": "weekly"}, "Paid archive, API access, and sponsor slots.")

    async def premium_spawn_kits(self) -> dict[str, Any]:
        kits = [
            {
                "name": "Agent Zero Pro Revenue Kit",
                "premium": True,
                "customizable": True,
                "includes": ["service scaffolds", "Nostr promotion templates", "risk policy", "marketplace copy"],
            },
            {
                "name": "Lightning Coordinator Kit",
                "premium": True,
                "customizable": True,
                "includes": ["A2A workflows", "bonding terms", "escrow checklist", "operator dashboards"],
            },
        ]
        return result("premium_spawn_kits", "Premium Reusable Agent Templates / Spawn Kits", {"kits": kits, "free_basic_guide_duplicated": False}, "High-margin paid kits, customization upsells.")

    async def mempool_priority_fee_predictor(self, mempool: dict[str, Any] | None = None) -> dict[str, Any]:
        mempool = mempool or {}
        base = int(mempool.get("median_fee_sat_vb", 8))
        forecast = {"next_block": base + 3, "30_min": max(1, base - 1), "2_hr": max(1, base - 3)}
        return result("mempool_priority_fee_predictor", "Mempool Priority Fee Predictor", forecast, "API calls, alerts, and wallet integration fees.")

    async def bug_vulnerability_watch(self, feeds: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        feeds = feeds or []
        critical = [f for f in feeds if f.get("severity") in {"high", "critical"}]
        return result("bug_vulnerability_watch", "Public Bug & Vulnerability Watch", {"critical": critical, "all_count": len(feeds)}, "Paid urgent alerts and remediation playbooks.")

    async def run_all(self) -> list[dict[str, Any]]:
        return [
            await self.daily_bitcoin_lightning_report(),
            await self.nostr_threads_and_signals(),
            await self.agent_performance_benchmarks(),
            await self.lightning_node_leaderboard(),
            await self.lightning_dev_digest(),
            await self.premium_spawn_kits(),
            await self.mempool_priority_fee_predictor({"median_fee_sat_vb": random.randint(3, 25)}),
            await self.bug_vulnerability_watch(),
        ]

