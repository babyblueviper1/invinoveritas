# invinoveritas × agentic brokerage trading (Robinhood Agentic Trading)

> **Put a governance gate in front of your trading agent.** Robinhood's
> [Agentic Trading](https://robinhood.com/us/en/newsroom/robinhood-is-now-open-to-agents/)
> (launched 2026-05-27) lets an AI agent — running on Claude, ChatGPT, Codex,
> or Cursor — place trades in a dedicated brokerage account over MCP, and
> *optionally with no per-trade confirmation*. invinoveritas is a
> Lightning-paid MCP tool stack whose `review` tool returns a capital-aware
> **approve / approve_with_concerns / reject** verdict on a proposed action.
> Wire both into the same agent and your agent checks every order *before* it
> fires.

*Independent integration recipe. Not affiliated with or endorsed by Robinhood.*

## The idea in one picture

The agent host (Claude Code / Desktop, ChatGPT, Cursor) is the MCP **client**,
and it holds **multiple MCP servers at once**. So the same agent that places
trades through Robinhood's Trading MCP can also hold invinoveritas — and call
`review` on the proposed order first:

```
            ┌──────────────────────── your agent (Claude / ChatGPT / Cursor) ────────────────────────┐
            │                                                                                          │
  "rebalance into AI names"  ─▶  agent drafts an order  ─▶  invinoveritas.review(order)                │
            │                                                       │                                  │
            │                                          reject ◀─────┤                                  │
            │                                                       └─▶ approve / approve_with_concerns │
            │                                                                   │                      │
            │                                                       robinhood-trading.place_order  ◀────┘
            └──────────────────────────────────────────────────────────────────────────────────────────┘
```

**What this is:** an advisory, agent-instruction-level gate — you tell the agent
to consult `review` before trading, and `review` returns a real verdict it can
act on. **What this is not:** it does not sit *inside* Robinhood's server and it
cannot physically block an order. That's the same trust model agentic trading
already runs on (the agent is trusted to follow its instructions) — `review`
just gives the agent a second opinion worth following.

## Setup (Claude Code; Desktop/ChatGPT/Cursor are the same two connectors)

```bash
# 1) register a free invinoveritas key (fund via Lightning or x402 / USDC)
curl -s -X POST https://api.babyblueviper.com/register \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "my-trading-agent", "description": "agentic trading governance"}'
# → {"api_key": "ivv_...", "balance_sats": 0}

# 2) add Robinhood's Trading MCP (their published endpoint)
claude mcp add robinhood-trading --transport http https://agent.robinhood.com/mcp/trading
#    then run /mcp and authenticate the robinhood-trading connector in the browser

# 3) add invinoveritas alongside it
claude mcp add invinoveritas --transport http https://api.babyblueviper.com/mcp \
  --header "Authorization: Bearer ivv_your_key_here"
```

## The review-before-trade rule

Add this to the agent's instructions (`CLAUDE.md`, a Claude Code skill, a system
prompt, or a Cursor rule) so it gates itself:

```md
## Trading governance (hard rule)
Before calling any `robinhood-trading` order/place tool, you MUST first call
`invinoveritas.review` with the proposed order as the artifact and the live
portfolio + thesis as context. If the verdict is `reject`, do NOT place the
trade — surface the issues to me and stop. If `approve_with_concerns`, place it
only after telling me the concerns. Never place a trade you have not reviewed.
```

That's the whole integration — no glue code.

## What the agent passes to `review`

Put the proposed order in `artifact` and the account state + reasoning in
`context`. **Do not set `include_trading_state`** — that flag injects *our*
internal trading bot's state and is irrelevant to your brokerage account; pass
*your* portfolio in `context` instead.

```jsonc
// invinoveritas.review
{
  "artifact": "BUY 12 NVDA @ market (~$1,420 notional)",
  "artifact_type": "plan",
  "context": "Agentic account balance $4,800; current positions 38% AAPL, 22% MSFT. Thesis: rotate into AI hardware ahead of earnings. This single order would push tech concentration to ~71%.",
  "concerns": "position sizing, concentration risk, thesis coherence vs. account size",
  "return_suggestions": true
}
// → { "verdict": "approve_with_concerns",
//     "confidence": 0.x,
//     "summary": "Aligns with the thesis but significantly increases tech concentration and correlation risk.",
//     "issues": [{ "severity": "high", "title": "Concentration to ~71% — high for a portfolio of this size" }, ...],
//     "alternative_approaches": ["Halve the order to keep tech under ~55%", ...] }
```

`review` is capital-scale-aware — the same order gets a different verdict on a
$5k account than on a $5M one. It returns ranked issues, suggested fixes, and a
clear approve/approve_with_concerns/reject so the agent has something concrete
to act on.

## Why this exists

invinoveritas is built and used daily by its own autonomous trading + ops
fleet, which runs every irreversible action past `review` under automated
governance before it executes. A trading agent calling `review` before a
Robinhood order is on the exact rails our internal agents already run on. Pay
per call from a Bearer balance (`~260 sats/review`) or omit the header for an
L402 Lightning invoice per call.

Live tool list and pricing: `tools/list` against `https://api.babyblueviper.com/mcp`,
or the server card at `https://api.babyblueviper.com/.well-known/mcp/server-card.json`.

> Equities-only in Robinhood's beta today; options, crypto, event contracts,
> and futures are on their roadmap. `review` is asset-agnostic and works on all
> of them the day they ship.
