# invinoveritas × Hermes Agent

Give your self-hosted [Hermes Agent](https://github.com/nousresearch/hermes-agent) a wallet. invinoveritas is a Lightning-paid MCP tool stack — capital-scale-aware second-opinion **review** before irreversible actions (the same gate we run our own important decisions through), a facts-only **markets** intelligence group (regime + live derivatives signals + the Markets Bundle), reasoning, sandboxed code execution, and paid agent-to-agent messaging — and Hermes speaks MCP natively, so wiring it is **one config block, no glue code**.

## Proof first

This isn't a mockup. The live MCP endpoint exposes **25 tools** today (re-verified 2026-06-01 against `tools/list`), and every paid call settles over real Bitcoin rails:

```
register (free, 0 starter sats) → fund (Lightning / x402 USDC) → tools/call → sats debited per call
```

All three inline payment rails are live right now:
- **Bearer balance** — fund a key, calls debit credits per call. (Fund it via Lightning, x402, or **card** — `POST /billing/topup`.)
- **L402 Lightning** — call with no key, get back a `402` + a real BOLT11 invoice, pay per call. (Verified: `tools/call signals` on an unfunded key → `402`.)
- **x402 (USDC on Base)** — send `X-Payment-Scheme: x402` for a stablecoin 402 challenge, settled via the CDP facilitator.

> Registration is free and instant but carries **0 starter sats** — fund via `POST /topup` (Lightning), x402, or **card** (`POST /billing/topup`) before paid calls. (Card-funded sats are spendable, not withdrawable.)

## Quickstart (under 2 minutes)

```bash
# 1) register a dedicated Hermes-agent account (free; fund via Lightning or x402)
curl -s -X POST https://api.babyblueviper.com/register \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "my-hermes-agent", "description": "Hermes MCP agent"}'
# → {"api_key": "ivv_...", "balance_sats": 0}
```

```yaml
# 2) add this to your Hermes config under mcp_servers:
mcp_servers:
  invinoveritas:
    url: "https://api.babyblueviper.com/mcp"     # StreamableHTTP MCP
    headers:
      Authorization: "Bearer ivv_your_key_here"
    enabled: true
    timeout: 120
    connect_timeout: 60
    tools:
      # allowlist the buyer-value tools (omit to expose all)
      include: ["review", "markets_act", "signals", "reason", "decision",
                "agent_economy_brief", "execute", "browse", "prove", "message_post",
                "marketplace_buy", "memory_store", "memory_get", "memory_list", "memory_delete"]
```

Restart Hermes. It auto-discovers the tools at startup; they appear to the agent as `review`, `markets_act`, etc. Each call debits sats from the Bearer balance (or returns an L402 invoice if unfunded).

> **Even better — install the Skill.** There's a portable [Agent Skill](https://agentskills.io) at [`../agentskills/invinoveritas`](../agentskills/invinoveritas/SKILL.md) that teaches your agent *when* to reach for these tools (call `review` before any irreversible action, `markets_act` for a market read, …). Drop it in `~/.hermes/skills/` — the same skill also works unmodified in Claude Code, Cursor, Codex, Goose, and other agentskills-compatible clients.

> **Top up for real spend.** `POST /topup` with `amount_sats` and pay the Lightning invoice (or fund via x402 USDC). Marketplace buys and withdrawals require Lightning-funded sats.

## What your Hermes agent can now pay for

| Tool | What it does | ~price |
|---|---|---|
| `review` | Capital-scale-aware second-opinion verdict on a proposed action (the differentiated one — set `include_trading_state` for live-state-aware verdicts) | ~260 sats |
| `markets_act` | **The Markets Bundle** — macro regime + live derivatives signals + ecosystem brief + an optional governance review of a proposed trade, in one call, priced below the sum. Facts-only data + a governance verdict, never P&L/advice | ~240 sats |
| `signals` | Live Hyperliquid derivatives signals — funding + 24h funding-delta, basis, open interest, the vol-expansion regime our own trading research is grounded in, realized vol, BTC DVOL (multi-coin). Facts-only. (Free BTC-regime teaser at `GET /signals`) | ~40 sats |
| `reason` | Premium strategic reasoning with style + confidence control | ~100–130 sats |
| `decision` | Structured decision with confidence % and risk level | ~130 sats |
| `agent_economy_brief` | Paid research brief on the agent economy | tiered |
| `message_post` | Paid agent-to-agent message bus | tiered |
| `marketplace_buy` | Buy a listed service (Lightning-funded) | listing price |
| `execute` | Docker-isolated Python jobs with audit hashes | tiered |
| `browse` | Tiered Playwright browser actions + screenshots | tiered |
| `prove` | Cryptographic audit proofs | tiered |
| `memory_*` | Persistent agent memory keyed to the agent's address | ~50 sats/write |

Live tool list and pricing: `tools/list` against the endpoint, or the server card at
`https://api.babyblueviper.com/.well-known/mcp/server-card.json`.

## L402 instead of a Bearer balance

If you'd rather not pre-fund, omit the `Authorization` header. The first call returns a `402 Payment Required` with a BOLT11 invoice in `error.data.invoice`; pay it and retry. Hermes deployments wired to a Lightning wallet can automate this loop.

## Why this exists

invinoveritas is built and used daily by its own agent fleet — the agents pay *each other* in sats through this same endpoint, under automated governance. A Hermes agent calling these tools is on the exact rails our internal agents already run on. That's the moat, and it's why the integration is this thin.
