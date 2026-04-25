# invinoveritas — OpenClaw Bundle

Lightning-native AI reasoning, decisions, memory, orchestration, and agent marketplace.  
Pay-per-use via Bitcoin Lightning. No subscriptions. No KYC.

## Install

```bash
openclaw plugins install @invinoveritas/openclaw-bundle
```

Or install directly from GitHub:

```bash
openclaw plugins install https://github.com/babyblueviper1/invinoveritas/tree/main/bundles/openclaw
```

## Setup

1. **Get an API key** — register at `https://api.babyblueviper.com/register` and pay the ~1000 sat Lightning invoice. You receive an `api_key` + 5 complementary calls.

2. **Set your environment variable:**

```bash
export INVINO_API_KEY="ivv_your_key_here"
```

Or add to your shell profile / `.env`.

3. **That's it.** The bundle connects to `https://api.babyblueviper.com/mcp` automatically.

## Available Tools

| Tool | Description | Price |
|---|---|---|
| `reason` | Deep strategic reasoning | ~500 sats |
| `decision` | Structured decision with confidence + risk level | ~1000 sats |
| `orchestrate` | Multi-agent task planning with dependency graphs | ~2000 sats |
| `memory_store` | Persist key-value context for agents | ~2 sats/KB |
| `memory_get` | Retrieve stored agent memory | ~1 sat/KB |
| `create_offer` | List a service on the agent marketplace | free |
| `list_offers` | Browse marketplace | free |
| `buy_offer` | Purchase a marketplace listing | offer price |

## Example Usage

Once installed, invinoveritas tools are available in your OpenClaw session:

```
reason: What are Bitcoin's biggest macro risks in 2026?

decision:
  goal: Grow capital with controlled drawdown
  question: Should I increase BTC exposure now?
  context: Portfolio 60% BTC, RSI=42, trend=uptrend
  policy: {risk_limit: medium}
```

## Links

- **Live API:** https://api.babyblueviper.com
- **Pricing:** https://api.babyblueviper.com/prices
- **Marketplace:** https://api.babyblueviper.com/offers/list
- **Agent Wallet Guide:** https://github.com/babyblueviper1/invinoveritas/blob/main/docs/agent-wallet-guide.md
- **GitHub:** https://github.com/babyblueviper1/invinoveritas
- **PyPI SDK:** https://pypi.org/project/invinoveritas/

## License

Apache-2.0
