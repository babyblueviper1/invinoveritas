"""Reusable safety wrapper for external registration and interactions."""

from __future__ import annotations

from services.common import result


class SafeExternalRegistration:
    async def prepare(self, platform: str, purpose: str, requires_credentials: bool = True) -> dict:
        checks = ["respect platform ToS", "rate limit actions", "store no raw credentials", "log only non-sensitive status"]
        if requires_credentials:
            checks.append("require operator-provided secret through environment or vault")
        return result("safe_external_registration", "Safe External Registration Module", {"platform": platform, "purpose": purpose, "checks": checks}, "Reusable expansion module for games, streaming, music, and NFT platforms.")

