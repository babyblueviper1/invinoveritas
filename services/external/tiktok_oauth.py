"""Internal TikTok OAuth and Content Posting helpers.

These helpers are for operator-owned growth workflows only. They are not
included in public spawn guides and they intentionally avoid any engagement
automation such as likes, comments, DMs, follows, scraping, or browser control.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx


TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_DIRECT_VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_DRAFT_VIDEO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
TIKTOK_CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
OAUTH_STATE_TTL_SECONDS = 15 * 60

DEFAULT_TIKTOK_SCOPES = (
    "user.info.basic",
    "video.upload",
)


def _client_key() -> str:
    return (os.getenv("TIKTOK_CLIENT_KEY") or os.getenv("TIKTOK_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return os.getenv("TIKTOK_CLIENT_SECRET", "").strip()


def _refresh_token() -> str:
    return os.getenv("TIKTOK_REFRESH_TOKEN", "").strip()


def _access_token() -> str:
    return os.getenv("TIKTOK_ACCESS_TOKEN", "").strip()


def _oauth_state_path() -> Path:
    return Path(os.getenv("VPS_DATA_DIR", "/root/invinoveritas/data")) / "tiktok_oauth_states.json"


def configured_tiktok_scopes() -> list[str]:
    raw = os.getenv("TIKTOK_OAUTH_SCOPES", "").strip()
    if not raw:
        return list(DEFAULT_TIKTOK_SCOPES)
    return [scope.strip() for scope in raw.replace(",", " ").split() if scope.strip()]


def tiktok_oauth_readiness() -> dict[str, Any]:
    scopes = configured_tiktok_scopes()
    return {
        "oauth_client_configured": bool(_client_key() and _client_secret()),
        "refresh_token_configured": bool(_refresh_token()),
        "access_token_configured": bool(_access_token()),
        "requested_scopes": scopes,
        "draft_upload_ready": "video.upload" in scopes and bool(_client_key() and _client_secret()),
        "direct_post_requested": "video.publish" in scopes,
        "guardrails": {
            "official_api_only": True,
            "default_mode": "draft_upload_until_direct_post_audit_is_approved",
            "no_engagement_automation": True,
            "ai_generated_content_label_required": True,
        },
        "required_redirect_uri": "https://api.babyblueviper.com/internal/tiktok/oauth-callback",
    }


def _load_oauth_states() -> dict[str, dict[str, Any]]:
    path = _oauth_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def _save_oauth_states(states: dict[str, dict[str, Any]]) -> None:
    path = _oauth_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(states, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _remember_oauth_state(state: str, redirect_uri: str) -> None:
    now = int(time.time())
    states = {
        key: value
        for key, value in _load_oauth_states().items()
        if now - int(value.get("created_at", 0)) < OAUTH_STATE_TTL_SECONDS
    }
    states[state] = {"redirect_uri": redirect_uri, "created_at": now}
    _save_oauth_states(states)


def consume_tiktok_oauth_state(state: str, redirect_uri: str) -> bool:
    now = int(time.time())
    states = _load_oauth_states()
    record = states.pop(state, None)
    fresh_states = {
        key: value
        for key, value in states.items()
        if now - int(value.get("created_at", 0)) < OAUTH_STATE_TTL_SECONDS
    }
    _save_oauth_states(fresh_states)
    if not record:
        return False
    if now - int(record.get("created_at", 0)) > OAUTH_STATE_TTL_SECONDS:
        return False
    return record.get("redirect_uri") == redirect_uri


def build_tiktok_consent_url(redirect_uri: str) -> dict[str, Any]:
    client_key = _client_key()
    if not client_key:
        raise ValueError("TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_ID is not configured")

    state = secrets.token_urlsafe(24)
    scopes = configured_tiktok_scopes()
    _remember_oauth_state(state, redirect_uri)
    params = {
        "client_key": client_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(scopes),
        "state": state,
    }
    return {
        "authorization_url": TIKTOK_AUTH_URL + "?" + urlencode(params),
        "state": state,
        "scopes": scopes,
        "next_step": "After consent, TikTok redirects to the callback. Tokens are persisted server-side and never returned.",
    }


def _persist_env_value(key: str, value: str, env_path: str = "/root/invinoveritas/.env") -> None:
    path = Path(env_path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{key}="
    updated: list[str] = []
    replaced = False
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
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


async def exchange_tiktok_authorization_code(
    code: str,
    redirect_uri: str,
    persist_refresh_token: bool = True,
) -> dict[str, Any]:
    client_key = _client_key()
    client_secret = _client_secret()
    if not client_key or not client_secret:
        raise ValueError("TikTok client key/secret are not configured")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TIKTOK_TOKEN_URL,
            data={
                "client_key": client_key,
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
            "log_id": data.get("log_id"),
        }

    refresh_token = data.get("refresh_token")
    access_token = data.get("access_token")
    if persist_refresh_token:
        if refresh_token:
            _persist_env_value("TIKTOK_REFRESH_TOKEN", refresh_token)
        if access_token:
            _persist_env_value("TIKTOK_ACCESS_TOKEN", access_token)

    return {
        "ok": True,
        "open_id_received": bool(data.get("open_id")),
        "access_token_received": bool(access_token),
        "refresh_token_received": bool(refresh_token),
        "tokens_persisted": bool(persist_refresh_token and (access_token or refresh_token)),
        "expires_in": data.get("expires_in"),
        "refresh_expires_in": data.get("refresh_expires_in"),
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", ""),
        "next_step": "Restart invinoveritas.service so Agent Zero can load TikTok tokens." if persist_refresh_token and refresh_token else "If no refresh token was returned, re-run consent after confirming scopes and redirect URI.",
    }


async def refresh_tiktok_access_token() -> dict[str, Any]:
    refresh_token = _refresh_token()
    client_key = _client_key()
    client_secret = _client_secret()
    if not refresh_token:
        raise ValueError("TIKTOK_REFRESH_TOKEN is not configured")
    if not client_key or not client_secret:
        raise ValueError("TikTok client key/secret are not configured")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TIKTOK_TOKEN_URL,
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
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
            "log_id": data.get("log_id"),
        }

    if data.get("refresh_token"):
        _persist_env_value("TIKTOK_REFRESH_TOKEN", data["refresh_token"])
    if data.get("access_token"):
        _persist_env_value("TIKTOK_ACCESS_TOKEN", data["access_token"])
    return {
        "ok": True,
        "open_id_received": bool(data.get("open_id")),
        "access_token_received": bool(data.get("access_token")),
        "refresh_token_received": bool(data.get("refresh_token")),
        "tokens_persisted": bool(data.get("access_token") or data.get("refresh_token")),
        "expires_in": data.get("expires_in"),
        "refresh_expires_in": data.get("refresh_expires_in"),
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", ""),
    }


async def _tiktok_access_token() -> str:
    refreshed = await refresh_tiktok_access_token() if _refresh_token() else {}
    token = refreshed.get("access_token") if refreshed.get("ok") else None
    token = token or _access_token()
    if not token:
        raise ValueError("TikTok access token unavailable")
    return token


async def tiktok_creator_info() -> dict[str, Any]:
    token = await _tiktok_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TIKTOK_CREATOR_INFO_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={},
        )
    data = response.json()
    return {"ok": response.status_code < 400, "status_code": response.status_code, "data": data}


async def initialize_tiktok_video_upload(
    *,
    title: str,
    video_url: str,
    direct_post: bool = False,
    privacy_level: str = "SELF_ONLY",
    disable_comment: bool = True,
    disable_duet: bool = True,
    disable_stitch: bool = True,
    brand_organic_toggle: bool = True,
    is_aigc: bool = True,
) -> dict[str, Any]:
    """Initialize a TikTok video post or draft using PULL_FROM_URL.

    The safest default is draft upload (`video.upload`). Direct Post requires
    `video.publish` scope, creator privacy option handling, and TikTok audit.
    """
    token = await _tiktok_access_token()
    url = TIKTOK_DIRECT_VIDEO_INIT_URL if direct_post else TIKTOK_DRAFT_VIDEO_INIT_URL
    post_info: dict[str, Any] = {
        "title": title[:2200],
        "disable_comment": disable_comment,
        "disable_duet": disable_duet,
        "disable_stitch": disable_stitch,
        "brand_organic_toggle": brand_organic_toggle,
        "is_aigc": is_aigc,
    }
    if direct_post:
        post_info["privacy_level"] = privacy_level
    body = {
        "post_info": post_info,
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": video_url,
        },
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json=body,
        )
    data = response.json()
    return {
        "ok": response.status_code < 400 and data.get("error", {}).get("code", "ok") == "ok",
        "status_code": response.status_code,
        "mode": "direct_post" if direct_post else "draft_upload",
        "ai_generated_content_labeled": is_aigc,
        "data": data,
    }
