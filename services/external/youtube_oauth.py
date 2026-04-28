"""Internal YouTube OAuth helpers.

These helpers are intentionally not used in public spawn guides. They prepare
operator-owned OAuth consent URLs and keep upload readiness separate from API-key
research readiness.
"""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode


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

