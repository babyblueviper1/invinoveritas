"""Internal Kick OAuth 2.1 helpers.

Kick requires Authorization Code + PKCE for user tokens. These helpers are
operator-only: they are not exposed in public spawn kits, public guides, or
external Agent Zero payloads.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx


KICK_OAUTH_BASE = "https://id.kick.com"
DEFAULT_KICK_SCOPES = (
    "user:read",
    "channel:read",
    "channel:write",
    "chat:write",
    "streamkey:read",
)
OAUTH_STATE_TTL_SECONDS = 15 * 60


def configured_kick_scopes() -> list[str]:
    raw = os.getenv("KICK_OAUTH_SCOPES", "").strip()
    if not raw:
        return list(DEFAULT_KICK_SCOPES)
    return [scope.strip() for scope in raw.replace(",", " ").split() if scope.strip()]


def _client_id() -> str:
    return (
        os.getenv("KICK_OAUTH_CLIENT_ID")
        or os.getenv("KICK_CLIENT_ID")
        or ""
    ).strip()


def _client_secret() -> str:
    return (
        os.getenv("KICK_OAUTH_CLIENT_SECRET")
        or os.getenv("KICK_CLIENT_SECRET")
        or ""
    ).strip()


def _refresh_token() -> str:
    return (
        os.getenv("KICK_OAUTH_REFRESH_TOKEN")
        or os.getenv("KICK_REFRESH_TOKEN")
        or ""
    ).strip()


def kick_oauth_readiness() -> dict[str, Any]:
    return {
        "oauth_client_configured": bool(_client_id() and _client_secret()),
        "refresh_token_configured": bool(_refresh_token()),
        "requested_scopes": configured_kick_scopes(),
        "oauth_server": KICK_OAUTH_BASE,
        "uses_pkce": True,
    }


def _oauth_state_path() -> Path:
    return Path(os.getenv("VPS_DATA_DIR", "/root/invinoveritas/data")) / "kick_oauth_states.json"


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
    path.write_text(json.dumps(states, indent=2, sort_keys=True) + "\n")


def _code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _remember_oauth_state(state: str, redirect_uri: str, code_verifier: str) -> None:
    now = int(time.time())
    states = {
        key: value
        for key, value in _load_oauth_states().items()
        if now - int(value.get("created_at", 0)) < OAUTH_STATE_TTL_SECONDS
    }
    states[state] = {
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "created_at": now,
    }
    _save_oauth_states(states)


def consume_kick_oauth_state(state: str, redirect_uri: str) -> str | None:
    """Validate and consume a one-use OAuth state value.

    Returns the PKCE code verifier when the state is valid.
    """
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
        return None
    if now - int(record.get("created_at", 0)) > OAUTH_STATE_TTL_SECONDS:
        return None
    if record.get("redirect_uri") != redirect_uri:
        return None
    verifier = record.get("code_verifier")
    return verifier if isinstance(verifier, str) and verifier else None


def build_kick_consent_url(redirect_uri: str) -> dict[str, Any]:
    client_id = _client_id()
    if not client_id:
        raise ValueError("KICK_OAUTH_CLIENT_ID or KICK_CLIENT_ID is not configured")

    state = secrets.token_urlsafe(24)
    verifier = _code_verifier()
    _remember_oauth_state(state, redirect_uri, verifier)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(configured_kick_scopes()),
        "code_challenge": _code_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
    }
    return {
        "authorization_url": f"{KICK_OAUTH_BASE}/oauth/authorize?" + urlencode(params),
        "state": state,
        "scopes": configured_kick_scopes(),
        "pkce": "S256",
        "next_step": "Authorize Kick, then the callback exchanges the code with the stored PKCE verifier.",
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


async def exchange_kick_authorization_code(
    code: str,
    redirect_uri: str,
    code_verifier: str,
    persist_refresh_token: bool = True,
) -> dict[str, Any]:
    client_id = _client_id()
    client_secret = _client_secret()
    if not client_id or not client_secret:
        raise ValueError("Kick OAuth client ID/secret are not configured")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{KICK_OAUTH_BASE}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "code": code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    data = response.json()
    if response.status_code >= 400:
        return {
            "ok": False,
            "status_code": response.status_code,
            "error": data.get("error"),
            "error_description": data.get("error_description") or data.get("message"),
        }

    refresh_token = data.get("refresh_token")
    if persist_refresh_token and refresh_token:
        _persist_env_value("KICK_OAUTH_REFRESH_TOKEN", refresh_token)
        if data.get("access_token"):
            _persist_env_value("KICK_OAUTH_ACCESS_TOKEN", data["access_token"])

    return {
        "ok": True,
        "access_token_received": bool(data.get("access_token")),
        "refresh_token_received": bool(refresh_token),
        "refresh_token_persisted": bool(refresh_token and persist_refresh_token),
        "expires_in": data.get("expires_in"),
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", ""),
        "next_step": "Restart invinoveritas.service so Agent Zero loads the Kick refresh token." if refresh_token and persist_refresh_token else "No refresh token returned; retry authorization if Kick did not grant offline access.",
    }


async def refresh_kick_access_token() -> dict[str, Any]:
    refresh_token = _refresh_token()
    client_id = _client_id()
    client_secret = _client_secret()
    if not refresh_token:
        raise ValueError("KICK_OAUTH_REFRESH_TOKEN or KICK_REFRESH_TOKEN is not configured")
    if not client_id or not client_secret:
        raise ValueError("Kick OAuth client ID/secret are not configured")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{KICK_OAUTH_BASE}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
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
            "error_description": data.get("error_description") or data.get("message"),
        }

    if data.get("refresh_token"):
        _persist_env_value("KICK_OAUTH_REFRESH_TOKEN", data["refresh_token"])
    if data.get("access_token"):
        _persist_env_value("KICK_OAUTH_ACCESS_TOKEN", data["access_token"])

    return {
        "ok": True,
        "access_token_received": bool(data.get("access_token")),
        "refresh_token_received": bool(data.get("refresh_token")),
        "tokens_persisted": bool(data.get("access_token") or data.get("refresh_token")),
        "expires_in": data.get("expires_in"),
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", ""),
    }

