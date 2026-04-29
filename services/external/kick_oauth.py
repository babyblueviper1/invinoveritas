"""Internal Kick OAuth 2.1 helpers.

Kick requires Authorization Code + PKCE for user tokens. These helpers are
operator-only: they are not exposed in public spawn kits, public guides, or
external Agent Zero payloads.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx


KICK_OAUTH_BASE = "https://id.kick.com"
KICK_API_BASE = "https://api.kick.com/public/v1"
KICK_API_ROOT = "https://api.kick.com"
DEFAULT_KICK_SCOPES = (
    "user:read",
    "channel:read",
    "channel:write",
    "chat:write",
    "streamkey:read",
)
OAUTH_STATE_TTL_SECONDS = 15 * 60
KICK_GROWTH_COOLDOWN_SECONDS = int(os.getenv("KICK_GROWTH_COOLDOWN_SECONDS", str(6 * 3600)))
KICK_STREAM_COOLDOWN_SECONDS = int(os.getenv("KICK_STREAM_COOLDOWN_SECONDS", str(24 * 3600)))
KICK_STREAM_MAX_DURATION_SECONDS = int(os.getenv("KICK_STREAM_MAX_DURATION_SECONDS", "900"))
KICK_STREAM_DEFAULT_DURATION_SECONDS = int(os.getenv("KICK_STREAM_DEFAULT_DURATION_SECONDS", "180"))
KICK_STREAM_DISCOVERY_LIMIT = int(os.getenv("KICK_STREAM_DISCOVERY_LIMIT", "12"))
KICK_STREAM_MIN_FREE_DISK_GB = float(os.getenv("KICK_STREAM_MIN_FREE_DISK_GB", "3"))
KICK_STREAM_MIN_FREE_MEMORY_MB = int(os.getenv("KICK_STREAM_MIN_FREE_MEMORY_MB", "350"))
KICK_STREAM_MAX_LOAD_1M = float(os.getenv("KICK_STREAM_MAX_LOAD_1M", "3.0"))
KICK_STREAM_VIDEO_BITRATE_K = int(os.getenv("KICK_STREAM_VIDEO_BITRATE_K", "1600"))
KICK_STREAM_AUDIO_BITRATE_K = int(os.getenv("KICK_STREAM_AUDIO_BITRATE_K", "96"))

KICK_STREAM_VARIANTS: tuple[dict[str, Any], ...] = (
    {
        "key": "marketplace_pulse",
        "title": "Agent Zero Live: Marketplace Pulse",
        "subtitle": "Lightning-native AI services | buy agent work with sats",
        "pattern": "testsrc2=size=1280x720:rate=30",
        "tone_hz": 432,
        "duration_seconds": 120,
        "tags": ["AI", "Bitcoin", "Lightning", "Agents"],
    },
    {
        "key": "btc_signal_room",
        "title": "Agent Zero Live: BTC Signal Room",
        "subtitle": "Flat unless edge is real | premium signal desk on marketplace",
        "pattern": "smptebars=size=1280x720:rate=30",
        "tone_hz": 528,
        "duration_seconds": 180,
        "tags": ["Bitcoin", "Trading", "AI", "Signals"],
    },
    {
        "key": "agent_build_lab",
        "title": "Agent Zero Live: Autonomous Build Lab",
        "subtitle": "Coordination, growth scans, creative releases, and paid agent services",
        "pattern": "testsrc=size=1280x720:rate=30",
        "tone_hz": 396,
        "duration_seconds": 300,
        "tags": ["Agents", "Build", "Automation", "Lightning"],
    },
    {
        "key": "creative_drop",
        "title": "Agent Zero Live: Creative Revenue Drop",
        "subtitle": "AI art/music release plans, Kick funnels, Nostr promotion, sats",
        "pattern": "mandelbrot=size=1280x720:rate=30",
        "tone_hz": 639,
        "duration_seconds": 420,
        "tags": ["Creative", "AI", "Music", "Nostr"],
    },
    {
        "key": "founder_status",
        "title": "Agent Zero Live: Growth Status",
        "subtitle": "What the agent tried, what converted, and what gets tested next",
        "pattern": "life=size=1280x720:rate=30:mold=10:ratio=0.12",
        "tone_hz": 741,
        "duration_seconds": 600,
        "tags": ["Startup", "Growth", "Agents", "Bitcoin"],
    },
)


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


def _access_token() -> str:
    return (
        os.getenv("KICK_OAUTH_ACCESS_TOKEN")
        or os.getenv("KICK_ACCESS_TOKEN")
        or ""
    ).strip()


def kick_oauth_readiness() -> dict[str, Any]:
    return {
        "oauth_client_configured": bool(_client_id() and _client_secret()),
        "refresh_token_configured": bool(_refresh_token()),
        "access_token_configured": bool(_access_token()),
        "requested_scopes": configured_kick_scopes(),
        "oauth_server": KICK_OAUTH_BASE,
        "api_server": KICK_API_BASE,
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


def _kick_growth_state_path() -> Path:
    return Path(os.getenv("VPS_DATA_DIR", "/root/invinoveritas/data")) / "kick_growth_state.json"


def _load_kick_growth_state() -> dict[str, Any]:
    path = _kick_growth_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_kick_growth_state(state: dict[str, Any]) -> None:
    path = _kick_growth_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _kick_stream_state_path() -> Path:
    return Path(os.getenv("VPS_DATA_DIR", "/root/invinoveritas/data")) / "kick_stream_state.json"


def _load_kick_stream_state() -> dict[str, Any]:
    path = _kick_stream_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_kick_stream_state(state: dict[str, Any]) -> None:
    path = _kick_stream_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _next_stream_variant(state: dict[str, Any]) -> dict[str, Any]:
    idx = int(state.get("variant_index", 0) or 0) % len(KICK_STREAM_VARIANTS)
    variant = dict(KICK_STREAM_VARIANTS[idx])
    state["variant_index"] = idx + 1
    return variant


def _append_stream_history(state: dict[str, Any], record: dict[str, Any]) -> None:
    history = state.get("history", [])
    if not isinstance(history, list):
        history = []
    history.append(record)
    state["history"] = history[-20:]


def _available_memory_mb() -> int | None:
    """Return MemAvailable from Linux procfs when available."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                return int(int(parts[1]) / 1024)
    except Exception:
        return None
    return None


def _stream_resource_guard() -> dict[str, Any]:
    """Fail closed when the small VPS is too constrained for a stream."""
    total, used, free = shutil.disk_usage("/")
    free_gb = round(free / (1024**3), 2)
    load_1m = None
    try:
        load_1m = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    memory_mb = _available_memory_mb()

    failures: list[str] = []
    if free_gb < KICK_STREAM_MIN_FREE_DISK_GB:
        failures.append("low_disk")
    if load_1m is not None and load_1m > KICK_STREAM_MAX_LOAD_1M:
        failures.append("high_load")
    if memory_mb is not None and memory_mb < KICK_STREAM_MIN_FREE_MEMORY_MB:
        failures.append("low_memory")

    return {
        "ok": not failures,
        "failures": failures,
        "free_disk_gb": free_gb,
        "min_free_disk_gb": KICK_STREAM_MIN_FREE_DISK_GB,
        "load_1m": load_1m,
        "max_load_1m": KICK_STREAM_MAX_LOAD_1M,
        "available_memory_mb": memory_mb,
        "min_free_memory_mb": KICK_STREAM_MIN_FREE_MEMORY_MB,
    }


async def _refresh_kick_access_token_raw() -> dict[str, Any]:
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
    return {"ok": True, **data}


async def _kick_access_token() -> str:
    refreshed = await _refresh_kick_access_token_raw()
    token = refreshed.get("access_token") if refreshed.get("ok") else None
    token = token or _access_token()
    if not token:
        raise ValueError("Kick access token unavailable after refresh")
    return token


def _sanitize_kick_response(data: Any) -> Any:
    if isinstance(data, dict):
        clean: dict[str, Any] = {}
        for key, value in data.items():
            if key.lower() in {"key", "stream_key", "access_token", "refresh_token", "token"}:
                clean[key] = "[redacted]"
            else:
                clean[key] = _sanitize_kick_response(value)
        return clean
    if isinstance(data, list):
        return [_sanitize_kick_response(item) for item in data]
    return data


async def _kick_api_request(method: str, path: str, *, json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    token = await _kick_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method,
            f"{KICK_API_BASE}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=json_body,
            params=params,
        )
    if response.status_code == 204:
        return {"ok": True, "status_code": response.status_code}
    try:
        data: Any = response.json()
    except Exception:
        data = {"text": response.text[:500]}
    return {
        "ok": response.status_code < 400,
        "status_code": response.status_code,
        "data": _sanitize_kick_response(data),
    }


async def _kick_api_request_raw(method: str, path: str) -> dict[str, Any]:
    token = await _kick_access_token()
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method,
            f"{KICK_API_ROOT}{path}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    try:
        data: Any = response.json()
    except Exception:
        data = {"text": response.text[:500]}
    return {"ok": response.status_code < 400, "status_code": response.status_code, "data": data}


def _first_data_item(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data", {})
    if isinstance(data, dict) and isinstance(data.get("data"), list) and data["data"]:
        item = data["data"][0]
        return item if isinstance(item, dict) else {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data["data"]
    return {}


def _find_stream_credentials(data: Any) -> tuple[str, str]:
    """Extract RTMPS server URL and stream key from likely Kick payload shapes."""
    if isinstance(data, list):
        for item in data:
            server_url, stream_key = _find_stream_credentials(item)
            if server_url and stream_key:
                return server_url, stream_key
        return "", ""
    if not isinstance(data, dict):
        return "", ""

    server_candidates = (
        "stream_url",
        "streamUrl",
        "server_url",
        "serverUrl",
        "rtmp_url",
        "rtmps_url",
        "url",
    )
    key_candidates = ("stream_key", "streamKey", "key")
    server_url = next((str(data[key]) for key in server_candidates if data.get(key)), "")
    stream_key = next((str(data[key]) for key in key_candidates if data.get(key)), "")
    if server_url and stream_key:
        return server_url, stream_key

    nested = data.get("data")
    if nested is not None:
        server_url, stream_key = _find_stream_credentials(nested)
        if server_url and stream_key:
            return server_url, stream_key

    for value in data.values():
        if isinstance(value, (dict, list)):
            server_url, stream_key = _find_stream_credentials(value)
            if server_url and stream_key:
                return server_url, stream_key
    return "", ""


def _stream_target(server_url: str, stream_key: str) -> str:
    parsed = urlparse(server_url)
    if parsed.scheme in {"rtmp", "rtmps"} and not parsed.path:
        netloc = parsed.netloc
        if ":" not in netloc and parsed.scheme == "rtmps":
            netloc = f"{netloc}:443"
        server_url = urlunparse((parsed.scheme, netloc, "/app", "", "", ""))
    return f"{server_url.rstrip('/')}/{stream_key.lstrip('/')}"


async def _kick_stream_credentials_raw() -> dict[str, Any]:
    candidate_paths = (
        "/public/v1/channels",
        "/public/v1/stream-key",
        "/public/v1/streamkey",
        "/public/v1/stream-keys",
        "/public/v1/channels/stream-key",
        "/public/v1/livestreams/stream-key",
    )
    attempts: list[dict[str, Any]] = []
    for path in candidate_paths:
        response = await _kick_api_request_raw("GET", path)
        attempts.append({
            "path": path,
            "ok": bool(response.get("ok")),
            "status_code": response.get("status_code"),
        })
        if not response.get("ok"):
            continue
        server_url, stream_key = _find_stream_credentials(response.get("data"))
        if server_url and stream_key:
            return {
                "ok": True,
                "path": path,
                "server_url": server_url,
                "stream_key": stream_key,
                "attempts": attempts,
            }
    return {
        "ok": False,
        "error": "Kick stream credentials endpoint did not return a recognizable stream URL/key payload",
        "attempts": attempts,
    }


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
    data = await _refresh_kick_access_token_raw()
    if not data.get("ok"):
        return data

    return {
        "ok": True,
        "access_token_received": bool(data.get("access_token")),
        "refresh_token_received": bool(data.get("refresh_token")),
        "tokens_persisted": bool(data.get("access_token") or data.get("refresh_token")),
        "expires_in": data.get("expires_in"),
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", ""),
    }


async def kick_token_introspect() -> dict[str, Any]:
    return await _kick_api_request("POST", "/token/introspect")


async def kick_get_users() -> dict[str, Any]:
    return await _kick_api_request("GET", "/users")


async def kick_get_channels() -> dict[str, Any]:
    return await _kick_api_request("GET", "/channels")


async def kick_get_livestreams(limit: int = 10, sort: str = "viewer_count") -> dict[str, Any]:
    return await _kick_api_request(
        "GET",
        "/livestreams",
        params={"limit": max(1, min(int(limit), 100)), "sort": sort},
    )


async def kick_get_livestream_stats() -> dict[str, Any]:
    return await _kick_api_request("GET", "/livestreams/stats")


async def kick_growth_strategy() -> dict[str, Any]:
    """Build a lightweight streaming growth strategy from public Kick discovery data."""
    channels = await kick_get_channels()
    channel_item = _first_data_item(channels)
    current_category = channel_item.get("category") if isinstance(channel_item.get("category"), dict) else {}
    livestreams = await kick_get_livestreams(limit=KICK_STREAM_DISCOVERY_LIMIT, sort="viewer_count")
    raw_items = livestreams.get("data", {}).get("data", [])
    public_items: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    if isinstance(raw_items, list):
        for item in raw_items[:KICK_STREAM_DISCOVERY_LIMIT]:
            if not isinstance(item, dict):
                continue
            category = item.get("category") or item.get("categories") or {}
            if isinstance(category, list):
                category = category[0] if category and isinstance(category[0], dict) else {}
            category_name = str(category.get("name") or "")
            if category_name:
                category_counts[category_name] = category_counts.get(category_name, 0) + 1
            public_items.append({
                "slug": item.get("slug") or item.get("channel_slug"),
                "title": item.get("stream_title") or item.get("session_title"),
                "viewer_count": item.get("viewer_count") or item.get("viewers"),
                "category": category_name,
                "tags": item.get("custom_tags") or [],
            })
    stream_state = _load_kick_stream_state()
    return {
        "ok": True,
        "strategy": {
            "constraints": {
                "vps": {"vcpu": 2, "ram_gb": 2, "disk_gb": 40, "traffic_out_tb": 1},
                "media_persistence": "none; ffmpeg lavfi streams directly to RTMPS, only tiny JSON state is saved",
                "bitrate": f"{KICK_STREAM_VIDEO_BITRATE_K}k video + {KICK_STREAM_AUDIO_BITRATE_K}k audio",
                "max_duration_seconds": KICK_STREAM_MAX_DURATION_SECONDS,
                "cooldown_seconds": KICK_STREAM_COOLDOWN_SECONDS,
                "resource_guard": _stream_resource_guard(),
            },
            "next_variants": [variant["key"] for variant in KICK_STREAM_VARIANTS],
            "duration_tests_seconds": [variant["duration_seconds"] for variant in KICK_STREAM_VARIANTS],
            "current_channel_category": current_category,
            "discovered_live_streams": public_items,
            "observed_categories": category_counts,
            "learning_plan": [
                "Rotate title, visual pattern, tone, tags, and stream length each run.",
                "Compare stream history with Kick live stats and marketplace traffic after each cycle.",
                "Use top live categories as inspiration for positioning, not copying or spam.",
                "Keep all video ephemeral to protect disk on the 40 GB VPS.",
            ],
            "last_stream": {
                "variant": stream_state.get("last_variant"),
                "duration_seconds": stream_state.get("last_duration_seconds"),
                "returncode": stream_state.get("last_returncode"),
                "started_at": stream_state.get("last_started_at"),
            },
            "history": stream_state.get("history", [])[-10:],
        },
    }


async def kick_get_stream_credentials_status() -> dict[str, Any]:
    credentials = await _kick_stream_credentials_raw()
    if not credentials.get("ok"):
        return credentials
    return {
        "ok": True,
        "path": credentials.get("path"),
        "server_url_received": bool(credentials.get("server_url")),
        "stream_key_received": bool(credentials.get("stream_key")),
        "attempts": credentials.get("attempts", []),
    }


async def kick_patch_channel(
    *,
    stream_title: str | None = None,
    category_id: int | None = None,
    custom_tags: list[str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if stream_title:
        body["stream_title"] = stream_title[:140]
    if category_id:
        body["category_id"] = int(category_id)
    if custom_tags:
        body["custom_tags"] = [str(tag)[:25] for tag in custom_tags[:10] if str(tag).strip()]
    if not body:
        raise ValueError("At least one Kick channel metadata field is required")
    return await _kick_api_request("PATCH", "/channels", json_body=body)


async def kick_post_chat(
    *,
    content: str,
    message_type: str = "bot",
    broadcaster_user_id: int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "content": content[:500],
        "type": "bot" if message_type not in {"user", "bot"} else message_type,
    }
    if broadcaster_user_id and body["type"] == "user":
        body["broadcaster_user_id"] = int(broadcaster_user_id)
    return await _kick_api_request("POST", "/chat", json_body=body)


def _ffmpeg_stream_command(target_url: str, variant: dict[str, Any], marketplace_url: str, duration_seconds: int) -> list[str]:
    title = str(variant.get("title") or "Agent Zero Live")[:120]
    text = (
        title.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("\n", " ")[:120]
    )
    subtitle = str(variant.get("subtitle") or marketplace_url)[:140]
    subtitle = subtitle.replace(":", "\\:")
    footer = marketplace_url.replace(":", "\\:")[:140]
    video_filter = (
        "drawbox=x=0:y=0:w=iw:h=ih:color=0x080808@1:t=fill,"
        "drawbox=x=40:y=40:w=1200:h=640:color=0xf7931a@0.08:t=fill,"
        f"drawtext=text='{text}':x=60:y=90:fontsize=42:fontcolor=white,"
        f"drawtext=text='{subtitle}':x=60:y=160:fontsize=28:fontcolor=0xf7931a,"
        f"drawtext=text='{footer}':x=60:y=560:fontsize=24:fontcolor=0xffffff,"
        "drawtext=text='%{localtime\\:%Y-%m-%d %H\\\\\\:%M\\\\\\:%S}':x=60:y=620:fontsize=24:fontcolor=0xaaaaaa"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-re",
        "-f",
        "lavfi",
        "-i",
        str(variant.get("pattern") or "testsrc2=size=1280x720:rate=30"),
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={int(variant.get('tone_hz') or 432)}:sample_rate=48000",
        "-t",
        str(duration_seconds),
        "-vf",
        video_filter,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-b:v",
        f"{KICK_STREAM_VIDEO_BITRATE_K}k",
        "-maxrate",
        f"{KICK_STREAM_VIDEO_BITRATE_K}k",
        "-bufsize",
        f"{KICK_STREAM_VIDEO_BITRATE_K * 2}k",
        "-pix_fmt",
        "yuv420p",
        "-g",
        "60",
        "-c:a",
        "aac",
        "-b:a",
        f"{KICK_STREAM_AUDIO_BITRATE_K}k",
        "-ar",
        "48000",
        "-f",
        "flv",
        target_url,
    ]


async def kick_stream_once(
    agent_id: str,
    marketplace_url: str,
    *,
    duration_seconds: int | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Start one bounded Kick stream using ffmpeg and official stream credentials."""
    enabled = os.getenv("AGENT_ZERO_KICK_STREAM_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
    now = int(time.time())
    state = _load_kick_stream_state()
    last_started_at = int(state.get("last_started_at", 0) or 0)
    variant = _next_stream_variant(state)
    duration = int(duration_seconds or variant.get("duration_seconds") or KICK_STREAM_DEFAULT_DURATION_SECONDS)
    duration = max(30, min(duration, KICK_STREAM_MAX_DURATION_SECONDS))

    if not dry_run and not enabled:
        return {
            "ok": True,
            "skipped": True,
            "reason": "disabled",
            "enable_with": "AGENT_ZERO_KICK_STREAM_ENABLED=1",
            "duration_seconds": duration,
            "variant": variant["key"],
        }
    if not force and now - last_started_at < KICK_STREAM_COOLDOWN_SECONDS:
        return {
            "ok": True,
            "skipped": True,
            "reason": "cooldown",
            "next_allowed_at": last_started_at + KICK_STREAM_COOLDOWN_SECONDS,
        }
    if not shutil.which("ffmpeg"):
        return {"ok": False, "error": "ffmpeg is not installed"}
    resource_guard = _stream_resource_guard()
    if not dry_run and not resource_guard["ok"]:
        return {
            "ok": True,
            "skipped": True,
            "reason": "resource_guard",
            "resource_guard": resource_guard,
            "duration_seconds": duration,
            "variant": variant["key"],
        }

    title = str(variant.get("title") or "Agent Zero Live")
    metadata = await kick_patch_channel(
        stream_title=f"{title} | {marketplace_url}",
        custom_tags=variant.get("tags") or ["AI", "Bitcoin", "Lightning", "Agents"],
    )
    credentials = await _kick_stream_credentials_raw()
    if not credentials.get("ok"):
        return {"ok": False, "metadata_update": metadata, "credentials": credentials}

    target_url = _stream_target(credentials["server_url"], credentials["stream_key"])
    command = _ffmpeg_stream_command(target_url, variant, marketplace_url, duration)
    safe_command = command[:-1] + ["[redacted-rtmps-target]"]
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "metadata_update": metadata,
            "credentials": {
                "ok": True,
                "path": credentials.get("path"),
                "server_url_received": True,
                "stream_key_received": True,
                "attempts": credentials.get("attempts", []),
            },
            "duration_seconds": duration,
            "variant": variant["key"],
            "resource_guard": resource_guard,
            "command": safe_command,
        }

    started_at = int(time.time())
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    finished_at = int(time.time())
    state.update({
        "last_started_at": started_at,
        "last_finished_at": finished_at,
        "last_returncode": process.returncode,
        "last_duration_seconds": duration,
        "last_variant": variant["key"],
        "last_agent_id": agent_id,
        "last_stream_key_path": credentials.get("path"),
    })
    _append_stream_history(state, {
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": process.returncode,
        "duration_seconds": duration,
        "variant": variant["key"],
    })
    _save_kick_stream_state(state)
    return {
        "ok": process.returncode == 0,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration,
        "variant": variant["key"],
        "returncode": process.returncode,
        "resource_guard": resource_guard,
        "metadata_update": metadata,
        "credentials": {
            "ok": True,
            "path": credentials.get("path"),
            "server_url_received": True,
            "stream_key_received": True,
            "attempts": credentials.get("attempts", []),
        },
        "chat": {"ok": False, "skipped": True, "reason": "post_stream_chat_disabled"},
        "stderr_tail": stderr.decode("utf-8", errors="replace")[-1000:],
        "stdout_tail": stdout.decode("utf-8", errors="replace")[-1000:],
    }


async def kick_growth_action(agent_id: str, marketplace_url: str, *, force: bool = False) -> dict[str, Any]:
    """Run one conservative Kick promotion cycle.

    Uses official Kick APIs only. Secrets and stream keys are never returned.
    """
    now = int(time.time())
    state = _load_kick_growth_state()
    last_action_at = int(state.get("last_action_at", 0) or 0)
    if not force and now - last_action_at < KICK_GROWTH_COOLDOWN_SECONDS:
        return {
            "ok": True,
            "skipped": True,
            "reason": "cooldown",
            "next_allowed_at": last_action_at + KICK_GROWTH_COOLDOWN_SECONDS,
        }

    user = await kick_get_users()
    channel = await kick_get_channels()
    channel_item = _first_data_item(channel)
    stream = channel_item.get("stream") if isinstance(channel_item.get("stream"), dict) else {}
    is_live = bool(stream.get("is_live"))
    slug = channel_item.get("slug")
    stream_title = f"Agent Zero: Lightning-native AI services | {marketplace_url}"
    tags = ["AI", "Bitcoin", "Lightning", "Agents"]

    metadata_update = await kick_patch_channel(stream_title=stream_title, custom_tags=tags)
    chat_result: dict[str, Any] = {"ok": False, "skipped": True, "reason": "channel_not_live"}
    if is_live:
        chat_result = await kick_post_chat(
            content=(
                f"{agent_id} is live on Lightning-native AI coordination. "
                f"Marketplace: {marketplace_url}"
            ),
            message_type="bot",
        )

    state.update({
        "last_action_at": now,
        "last_agent_id": agent_id,
        "last_channel_slug": slug,
        "last_is_live": is_live,
        "last_metadata_ok": bool(metadata_update.get("ok")),
        "last_chat_ok": bool(chat_result.get("ok")),
    })
    _save_kick_growth_state(state)
    return {
        "ok": bool(metadata_update.get("ok")) and (bool(chat_result.get("ok")) or chat_result.get("skipped")),
        "checked_at": now,
        "channel_slug": slug,
        "is_live": is_live,
        "user_ok": bool(user.get("ok")),
        "channel_ok": bool(channel.get("ok")),
        "metadata_update": metadata_update,
        "chat": chat_result,
        "cooldown_seconds": KICK_GROWTH_COOLDOWN_SECONDS,
    }
