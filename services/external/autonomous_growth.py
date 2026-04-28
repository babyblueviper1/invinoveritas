"""Autonomous growth planner for external and permissionless channels.

This module is deliberately strict: Agent Zero can act without a human on
permissionless channels and on platforms with official API credentials already
available in the environment. It skips registration paths that require CAPTCHA,
KYC, phone/email verification, browser evasion, or unclear authorization.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from services.common import result, stable_id


@dataclass(frozen=True)
class GrowthChannel:
    name: str
    kind: str
    permissionless: bool
    official_api: bool
    env_token: str | None = None
    monetization: tuple[str, ...] = ()

    def can_execute(self) -> bool:
        if self.permissionless:
            return True
        if self.official_api and self.env_token:
            return bool(os.getenv(self.env_token))
        return False

    def blocked_reason(self) -> str | None:
        if self.can_execute():
            return None
        if self.official_api and self.env_token:
            return f"missing environment credential: {self.env_token}"
        return "requires unsupported signup, verification, KYC, CAPTCHA, or browser automation"


class AutonomousGrowthEngine:
    """Select and prepare zero-human growth actions."""

    CHANNELS = (
        GrowthChannel(
            name="Nostr",
            kind="social",
            permissionless=True,
            official_api=True,
            monetization=("tips", "marketplace traffic", "agent recruiting"),
        ),
        GrowthChannel(
            name="invinoveritas_marketplace",
            kind="marketplace",
            permissionless=True,
            official_api=True,
            monetization=("service sales", "spawn kit sales", "subscriptions"),
        ),
        GrowthChannel(
            name="YouTube",
            kind="streaming",
            permissionless=False,
            official_api=True,
            env_token="YOUTUBE_API_TOKEN",
            monetization=("ad revenue", "tips", "funnels"),
        ),
        GrowthChannel(
            name="Kick",
            kind="streaming",
            permissionless=False,
            official_api=True,
            env_token="KICK_API_TOKEN",
            monetization=("tips", "subs", "sponsorships"),
        ),
        GrowthChannel(
            name="Audius",
            kind="music",
            permissionless=False,
            official_api=True,
            env_token="AUDIUS_API_TOKEN",
            monetization=("music discovery", "tips", "fan funnel"),
        ),
        GrowthChannel(
            name="NFT_marketplace",
            kind="art",
            permissionless=False,
            official_api=True,
            env_token="NFT_MARKETPLACE_API_TOKEN",
            monetization=("primary sales", "royalties"),
        ),
        GrowthChannel(
            name="gaming_strategy_market",
            kind="games",
            permissionless=True,
            official_api=True,
            monetization=("strategy sales", "performance subscriptions"),
        ),
    )

    async def plan(self, agent_id: str, assets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        assets = assets or []
        executable = []
        blocked = []
        for channel in self.CHANNELS:
            item = {
                "channel": channel.name,
                "kind": channel.kind,
                "monetization": list(channel.monetization),
            }
            if channel.can_execute():
                executable.append({
                    **item,
                    "action_id": stable_id("growth", {"agent_id": agent_id, "channel": channel.name}),
                    "next_action": self._next_action(channel, assets),
                })
            else:
                blocked.append({**item, "blocked_reason": channel.blocked_reason()})

        return result(
            "autonomous_growth_plan",
            "Autonomous Growth Plan",
            {
                "agent_id": agent_id,
                "mode": "zero_human_where_authorized",
                "executable": executable,
                "blocked": blocked,
                "policy": [
                    "use official APIs or permissionless protocols only",
                    "do not bypass CAPTCHA, KYC, phone/email checks, rate limits, or ToS gates",
                    "do not log secrets",
                    "never wager unless confidence and Kelly gates pass",
                ],
            },
            "Compounds distribution through Nostr, marketplace listings, content releases, and API-authorized external channels.",
        )

    def _next_action(self, channel: GrowthChannel, assets: list[dict[str, Any]]) -> str:
        if channel.name == "Nostr":
            return "publish thread, signal, release note, and marketplace CTA"
        if channel.name == "invinoveritas_marketplace":
            return "list premium service or subscription product"
        if channel.name == "gaming_strategy_market":
            return "list confidence-gated strategy product; no direct wager required"
        if channel.kind == "streaming":
            return "upload short-form stream teaser through official API credential"
        if channel.kind == "music":
            return "publish generated release metadata through official API credential"
        if channel.kind == "art":
            return "publish art-drop metadata through official API credential"
        return "prepare API-authorized growth action"

