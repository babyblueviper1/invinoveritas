"""
invinoveritas MCP Server

Exposes /reason and /decision as MCP tools for autonomous agents.
Handles the full L402 Lightning payment flow transparently.

The calling agent (Claude, Cursor, etc.) only sees the final AI response.
"""

import os
import json
import asyncio
import requests
from typing import Dict, Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# =========================
# Configuration
# =========================
API_BASE = os.getenv("API_BASE", "https://invinoveritas.onrender.com").rstrip("/")
LND_DIR = os.getenv("LND_DIR")
CLN_RPC_PATH = os.getenv("CLN_RPC_PATH")

try:
    from lndgrpc import LNDClient
except ImportError:
    LNDClient = None

try:
    from pyln.client import LightningRpc
except ImportError:
    LightningRpc = None


# =========================
# Lightning Payment Helpers
# =========================
def _pay_invoice(bolt11: str) -> str:
    """Pay a bolt11 invoice using LND or CLN. Returns preimage as hex."""
    if LND_DIR and LNDClient:
        try:
            lnd = LNDClient(LND_DIR)
            resp = lnd.send_payment_sync(payment_request=bolt11)
            return resp.payment_preimage.hex()
        except Exception as e:
            raise RuntimeError(f"LND payment failed: {e}")

    if CLN_RPC_PATH and LightningRpc:
        try:
            rpc = LightningRpc(CLN_RPC_PATH)
            result = rpc.pay(bolt11)
            return result.get("payment_preimage")
        except Exception as e:
            raise RuntimeError(f"CLN payment failed: {e}")

    raise RuntimeError("No Lightning node configured. Set LND_DIR or CLN_RPC_PATH.")


def _parse_l402_header(www_auth: str) -> tuple[str, str]:
    """Extract token (payment_hash) and bolt11 from WWW-Authenticate header."""
    if "L402" not in www_auth:
        raise ValueError(f"Invalid L402 header: {www_auth}")

    try:
        token = www_auth.split('token="')[1].split('"')[0]
        invoice = www_auth.split('invoice="')[1].split('"')[0]
        return token, invoice
    except (IndexError, AttributeError):
        raise ValueError(f"Failed to parse L402 header: {www_auth}")


def _call_with_l402(endpoint: str, payload: dict) -> dict:
    """
    Full L402 payment flow:
    1. First POST → expect 402 + invoice
    2. Pay the invoice
    3. Retry with Authorization header
    """
    url = f"{API_BASE}/{endpoint}"

    # Step 1: Initial request
    try:
        resp = requests.post(url, json=payload, timeout=15, headers={"User-Agent": "invinoveritas-mcp/1.0"})
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to reach API: {e}")

    if resp.status_code == 200:
        return resp.json()  # Already paid (rare)

    if resp.status_code != 402:
        try:
            error = resp.json()
        except Exception:
            error = resp.text
        raise RuntimeError(f"Unexpected response {resp.status_code}: {error}")

    # Step 2: Parse L402 header
    www_auth = resp.headers.get("WWW-Authenticate", "")
    try:
        token, bolt11 = _parse_l402_header(www_auth)
    except ValueError as e:
        raise RuntimeError(str(e))

    # Step 3: Pay the invoice
    print(f"→ Paying invoice for /{endpoint}...")
    preimage = _pay_invoice(bolt11)

    # Step 4: Retry with payment proof
    auth_header = f"L402 {token}:{preimage}"
    try:
        retry_resp = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": auth_header,
                "User-Agent": "invinoveritas-mcp/1.0"
            },
            timeout=30,
        )
        retry_resp.raise_for_status()
        return retry_resp.json()
    except requests.RequestException as e:
        raise RuntimeError(f"Retry after payment failed: {e}")


# =========================
# MCP Server Setup
# =========================
server = Server("invinoveritas")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="reason",
            description=(
                "High-quality strategic reasoning powered by invinoveritas via Lightning payments. "
                "Use when you need deep analysis, risk assessment, or well-reasoned strategic answers. "
                "Payment is handled automatically (~500-700 sats)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The strategic question or topic you need analyzed."
                    }
                },
                "required": ["question"]
            },
        ),
        types.Tool(
            name="decision",
            description=(
                "Structured decision intelligence optimized for autonomous agents. "
                "Returns a clear recommendation with confidence score and risk level. "
                "Payment is handled automatically (~1000 sats)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "The overall objective or desired outcome."},
                    "context": {"type": "string", "description": "Relevant background context."},
                    "question": {"type": "string", "description": "The specific decision question."}
                },
                "required": ["goal", "context", "question"]
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "reason":
            question = arguments.get("question", "").strip()
            if not question:
                raise ValueError("'question' is required for reason tool.")

            result = _call_with_l402("reason", {"question": question})
            answer = result.get("answer") or json.dumps(result, indent=2)
            return [types.TextContent(type="text", text=answer)]

        elif name == "decision":
            for field in ("goal", "context", "question"):
                if not arguments.get(field, "").strip():
                    raise ValueError(f
