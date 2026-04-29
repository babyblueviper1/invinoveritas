"""Internal YouTube OAuth helpers.

These helpers are intentionally not used in public spawn guides. They prepare
operator-owned OAuth consent URLs and keep upload readiness separate from API-key
research readiness.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx


DEFAULT_YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
)


def configured_youtube_scopes() -> list[str]:
    raw = os.getenv("YOUTUBE_OAUTH_SCOPES", "").strip()
    if not raw:
        return list(DEFAULT_YOUTUBE_SCOPES)
    return [scope.strip() for scope in raw.replace(",", " ").split() if scope.strip()]


def youtube_oauth_readiness() -> dict:
    return {
        "api_key_configured": bool(os.getenv("YOUTUBE_API_KEY") or os.getenv("YOUTUBE_API_TOKEN")),
        "oauth_client_configured": bool(
            os.getenv("YOUTUBE_OAUTH_CLIENT_ID")
            and os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET")
        ),
        "refresh_token_configured": bool(
            os.getenv("YOUTUBE_OAUTH_REFRESH_TOKEN")
            or os.getenv("YOUTUBE_OAUTH_TOKEN")
        ),
        "requested_scopes": configured_youtube_scopes(),
    }


def build_youtube_consent_url(redirect_uri: str) -> dict:
    client_id = os.getenv("YOUTUBE_OAUTH_CLIENT_ID", "").strip()
    if not client_id:
        raise ValueError("YOUTUBE_OAUTH_CLIENT_ID is not configured")

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(configured_youtube_scopes()),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return {
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params),
        "state": state,
        "scopes": configured_youtube_scopes(),
        "next_step": "After consent, exchange the returned code for a refresh token and store it as YOUTUBE_OAUTH_REFRESH_TOKEN.",
    }


def _persist_env_value(key: str, value: str, env_path: str = "/root/invinoveritas/.env") -> None:
    """Upsert a secret into the local env file without printing it."""
    path = Path(env_path)
    lines = path.read_text().splitlines() if path.exists() else []
    prefix = f"{key}="
    replaced = False
    updated = []
    for line in lines:
        if line.startswith(prefix):
            updated.append(prefix + value)
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(prefix + value)
    path.write_text("\n".join(updated) + "\n")


async def exchange_youtube_authorization_code(
    code: str,
    redirect_uri: str,
    persist_refresh_token: bool = True,
) -> dict[str, Any]:
    """Exchange a Google OAuth authorization code for tokens.

    Returns only metadata by default. The refresh token is persisted locally when
    present so Agent Zero can operate without further consent prompts.
    """
    client_id = os.getenv("YOUTUBE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ValueError("YouTube OAuth client ID/secret are not configured")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    data = response.json()
    if response.status_code >= 400:
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": data.get("error"),
            "error_description": data.get("error_description"),
        }

    refresh_token = data.get("refresh_token")
    access_token = data.get("access_token")
    if persist_refresh_token and refresh_token:
        _persist_env_value("YOUTUBE_OAUTH_REFRESH_TOKEN", refresh_token)

    return {
        "ok": True,
        "access_token_received": bool(access_token),
        "refresh_token_received": bool(refresh_token),
        "refresh_token_persisted": bool(refresh_token and persist_refresh_token),
        "expires_in": data.get("expires_in"),
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", ""),
        "next_step": "Restart invinoveritas.service so the refreshed environment is loaded." if refresh_token and persist_refresh_token else "If no refresh token was returned, revoke consent and retry with prompt=consent/access_type=offline.",
    }


async def refresh_youtube_access_token() -> dict[str, Any]:
    refresh_token = (
        os.getenv("YOUTUBE_OAUTH_REFRESH_TOKEN")
        or os.getenv("YOUTUBE_OAUTH_TOKEN")
        or ""
    ).strip()
    client_id = os.getenv("YOUTUBE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_OAUTH_CLIENT_SECRET", "").strip()
    if not refresh_token:
        raise ValueError("YOUTUBE_OAUTH_REFRESH_TOKEN is not configured")
    if not client_id or not client_secret:
        raise ValueError("YouTube OAuth client ID/secret are not configured")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    data = response.json()
    if response.status_code >= 400:
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": data.get("error"),
            "error_description": data.get("error_description"),
        }
    return {
        "ok": True,
        "access_token_received": bool(data.get("access_token")),
        "expires_in": data.get("expires_in"),
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", ""),
    }
