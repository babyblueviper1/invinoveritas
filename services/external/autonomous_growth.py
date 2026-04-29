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
    env_tokens: tuple[str, ...] = ()
    internal_only: bool = False
    monetization: tuple[str, ...] = ()

    def can_execute(self) -> bool:
        if self.permissionless:
            return True
        if self.official_api and self.env_tokens:
            return any(bool(os.getenv(name)) for name in self.env_tokens)
        return False

    def blocked_reason(self, public: bool = False) -> str | None:
        if self.can_execute():
            return None
        if self.official_api and self.env_tokens:
            if public:
                return "requires an internal official API credential"
            return f"missing internal environment credential: {', '.join(self.env_tokens)}"
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
            env_tokens=("YOUTUBE_API_KEY", "YOUTUBE_API_TOKEN"),
            internal_only=True,
            monetization=("ad revenue", "tips", "funnels"),
        ),
        GrowthChannel(
            name="Kick",
            kind="streaming",
            permissionless=False,
            official_api=True,
            env_tokens=("KICK_OAUTH_REFRESH_TOKEN", "KICK_REFRESH_TOKEN", "KICK_API_TOKEN"),
            internal_only=True,
            monetization=("tips", "subs", "sponsorships"),
        ),
        GrowthChannel(
            name="Audius",
            kind="music",
            permissionless=False,
            official_api=True,
            env_tokens=("AUDIUS_API_TOKEN",),
            internal_only=True,
            monetization=("music discovery", "tips", "fan funnel"),
        ),
        GrowthChannel(
            name="NFT_marketplace",
            kind="art",
            permissionless=False,
            official_api=True,
            env_tokens=("NFT_MARKETPLACE_API_TOKEN",),
            internal_only=True,
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

    async def plan(
        self,
        agent_id: str,
        assets: list[dict[str, Any]] | None = None,
        public: bool = False,
    ) -> dict[str, Any]:
        assets = assets or []
        executable = []
        blocked = []
        for channel in self.CHANNELS:
            item = {
                "channel": channel.name,
                "kind": channel.kind,
                "monetization": list(channel.monetization),
                "internal_only": channel.internal_only,
            }
            if channel.can_execute():
                action = {
                    **item,
                    "action_id": stable_id("growth", {"agent_id": agent_id, "channel": channel.name}),
                    "next_action": self._next_action(channel, assets),
                }
                if not public or not channel.internal_only:
                    executable.append(action)
            else:
                blocked_item = {**item, "blocked_reason": channel.blocked_reason(public=public)}
                if not public or not channel.internal_only:
                    blocked.append(blocked_item)

        return result(
            "autonomous_growth_plan",
            "Autonomous Growth Plan",
            {
                "agent_id": agent_id,
                "mode": "public_redacted" if public else "zero_human_where_authorized",
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
            if channel.name == "YouTube":
                has_api_key = bool(os.getenv("YOUTUBE_API_KEY") or os.getenv("YOUTUBE_API_TOKEN"))
                has_oauth_client = bool(os.getenv("YOUTUBE_OAUTH_CLIENT_ID") and os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET"))
                has_refresh_token = bool(os.getenv("YOUTUBE_OAUTH_REFRESH_TOKEN") or os.getenv("YOUTUBE_OAUTH_TOKEN"))
                if has_refresh_token:
                    return "publish or schedule YouTube content through stored OAuth refresh token"
                if has_oauth_client:
                    return "OAuth client configured; generate consent URL and wait for refresh token before upload/stream"
                if has_api_key:
                    return "research trends through YouTube Data API key; upload/stream waits for OAuth credential"
            if channel.name == "Kick":
                has_refresh_token = bool(os.getenv("KICK_OAUTH_REFRESH_TOKEN") or os.getenv("KICK_REFRESH_TOKEN") or os.getenv("KICK_API_TOKEN"))
                has_oauth_client = bool(
                    (os.getenv("KICK_OAUTH_CLIENT_ID") or os.getenv("KICK_CLIENT_ID"))
                    and (os.getenv("KICK_OAUTH_CLIENT_SECRET") or os.getenv("KICK_CLIENT_SECRET"))
                )
                if has_refresh_token:
                    return "refresh Kick user token and update livestream metadata, fetch stream key, or coordinate chat through official API"
                if has_oauth_client:
                    return "Kick OAuth client configured; generate PKCE consent URL and wait for refresh token before autonomous streaming"
            return "publish or schedule stream content through official platform credential"
        if channel.kind == "music":
            return "publish generated release metadata through official API credential"
        if channel.kind == "art":
            return "publish art-drop metadata through official API credential"
        return "prepare API-authorized growth action"
