"""
invinoveritas MCP Server
Exposes /reason and /decision as MCP tools.
Handles the full L402 payment flow transparently —
the calling agent just sees the final AI response.

Requirements:
  pip install mcp requests lndgrpc pyln-client

Environment variables (same as agent_client.py):
  API_BASE      — e.g. https://your-api.onrender.com
  LND_DIR       — path to .lnd dir (preferred)
  CLN_RPC_PATH  — path to CLN rpc socket (fallback)
"""

import os
import json
import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ─── config ───────────────────────────────────────────────
API_BASE = os.getenv("API_BASE", "https://your-api.onrender.com").rstrip("/")
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


# ─── lightning payment helpers ────────────────────────────

def _pay_invoice(bolt11: str) -> str:
    """Pay a bolt11 invoice. Returns preimage hex string."""
    if LND_DIR and LNDClient:
        lnd = LNDClient(LND_DIR)
        resp = lnd.send_payment_sync(payment_request=bolt11)
        return resp.payment_preimage.hex()
    if CLN_RPC_PATH and LightningRpc:
        rpc = LightningRpc(CLN_RPC_PATH)
        result = rpc.pay(bolt11)
        return result.get("payment_preimage")
    raise RuntimeError(
        "No Lightning node configured. Set LND_DIR or CLN_RPC_PATH."
    )


def _parse_l402_header(www_auth: str) -> tuple[str, str]:
    """Extract (token, bolt11) from WWW-Authenticate: L402 header."""
    token = www_auth.split('token="')[1].split('"')[0]
    invoice = www_auth.split('invoice="')[1].split('"')[0]
    return token, invoice


def _call_with_l402(endpoint: str, payload: dict) -> dict:
    """
    Full L402 flow:
      1. POST → expect 402
      2. Parse invoice from WWW-Authenticate header
      3. Pay via Lightning
      4. Retry POST with Authorization: L402 token:preimage
    Returns the final JSON response body.
    """
    url = f"{API_BASE}/{endpoint}"

    # Step 1 — initial request, expect 402
    resp = requests.post(url, json=payload, timeout=15)

    if resp.status_code == 200:
        return resp.json()

    if resp.status_code != 402:
        resp.raise_for_status()

    www_auth = resp.headers.get("WWW-Authenticate", "")
    if "L402" not in www_auth:
        raise ValueError(f"Unexpected WWW-Authenticate header: {www_auth}")

    # Step 2 — parse token + bolt11
    token, bolt11 = _parse_l402_header(www_auth)

    # Step 3 — pay
    preimage = _pay_invoice(bolt11)

    # Step 4 — retry with credentials
    auth_header = f"L402 {token}:{preimage}"
    retry = requests.post(
        url,
        json=payload,
        headers={"Authorization": auth_header, "User-Agent": "invinoveritas-mcp/1.0"},
        timeout=30,
    )
    retry.raise_for_status()
    return retry.json()


# ─── MCP server ───────────────────────────────────────────

server = Server("invinoveritas")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="reason",
            description=(
                "Pay-per-use strategic reasoning powered by invinoveritas. "
                "Use this when you need high-quality analysis, strategic thinking, "
                "or a well-reasoned answer to a complex question. "
                "Payment is automatic via Bitcoin Lightning Network (L402). "
                "Costs a small number of satoshis per call (~500 sats by default). "
                "Returns a detailed strategic answer as a string."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": (
                            "The question or topic you want strategic reasoning about. "
                            "Be specific — longer, more detailed questions produce better answers."
                        ),
                    }
                },
                "required": ["question"],
            },
        ),
        types.Tool(
            name="decision",
            description=(
                "Pay-per-use structured decision intelligence powered by invinoveritas. "
                "Use this when you need a clear decision with confidence score and risk level — "
                "ideal for autonomous agents that need a machine-readable recommendation. "
                "Payment is automatic via Bitcoin Lightning Network (L402). "
                "Costs a small number of satoshis per call (~1000 sats by default). "
                "Returns JSON with: decision, confidence (0-1), reasoning, risk_level (low/medium/high)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "The objective or desired outcome.",
                    },
                    "context": {
                        "type": "string",
                        "description": "Relevant background information about the current situation.",
                    },
                    "question": {
                        "type": "string",
                        "description": "The specific decision question to answer.",
                    },
                },
                "required": ["goal", "context", "question"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "reason":
        question = arguments.get("question", "").strip()
        if not question:
            raise ValueError("'question' is required for the reason tool.")

        result = _call_with_l402("reason", {"question": question})
        answer = result.get("answer", json.dumps(result))
        return [types.TextContent(type="text", text=answer)]

    elif name == "decision":
        for field in ("goal", "context", "question"):
            if not arguments.get(field, "").strip():
                raise ValueError(f"'{field}' is required for the decision tool.")

        result = _call_with_l402("decision", {
            "goal": arguments["goal"],
            "context": arguments["context"],
            "question": arguments["question"],
        })

        # Return structured result as formatted JSON string
        decision_result = result.get("result", result)
        return [types.TextContent(
            type="text",
            text=json.dumps(decision_result, indent=2)
        )]

    else:
        raise ValueError(f"Unknown tool: {name}")


# ─── entrypoint ───────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
