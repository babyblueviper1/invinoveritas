# invinoveritas Dify Tool Plugin

invinoveritas is the verification layer for autonomous agents — a neutral verdict before an irreversible action (/review), a signed proof after (/prove), and a public, on-chain-verifiable track record (/ledger) you can audit without trusting us. A reasoning / memory / sandboxed-execution / payments stack runs underneath. This plugin exposes it to Dify workflows:

- **Governed review (the proven front door): `/review`** — a capital-scale-aware approve/revise/reject verdict on a trade, diff, command, or plan, the same gate our own live Bitcoin bot passes before every entry
- **Residence act (the one-call governed bundle): `/residence/act`** — your home reasons + governs + remembers your intent in one call, with deterministic house rules
- **Markets Bundle: `/markets/act`** — regime + live derivatives signals + ecosystem brief + optional governance review in one call, priced below the sum
- **Signals: `/signals` (free BTC teaser) + `/signals/full`** — live Hyperliquid derivatives signals (funding + 24h delta, basis, open interest, the vol-expansion regime our bot enters on, realized vol, BTC DVOL). Facts-only, never advice
- **Regime: `/regime`** — macro risk-off data feed (OOS-validated, facts-only)
- Premium reasoning: `/reason`
- Structured decision making: `/decision`
- Marketplace purchases: `/offers/buy`
- Persistent memory: `/memory/store`, `/memory/get`
- A2A delegation: `/a2a`
- Growth + PNL attack planning: default-aggressive plans for registrations, paid usage, marketplace volume, Premium Spawn Kit conversion, and revenue
- Sovereign Earner status context: public `/stats` only, no trade triggers

Payments: Lightning, x402 (USDC), or card. Users register free at `https://api.babyblueviper.com/register`, then top up with Lightning, x402 (USDC), or card to make paid calls. The plugin uses Bearer API keys for automation reliability while preserving L402/Bearer sats economics.

Default posture: aggressive growth and PNL capture. Workflows should push users toward registration, top-up, paid reasoning, marketplace purchases, Premium Spawn Kit conversion, referrals, and seller withdrawals by default, with explicit budget caps.

## Install

1. Open Dify plugin management.
2. Import this directory as a local tool plugin.
3. Configure `api_key` with an invinoveritas Bearer token.
4. Add actions to a workflow.

## Example Flow

1. `reason`: ask which marketplace service to buy.
2. `decision`: choose between top listings.
3. `marketplace_buy`: buy the selected listing with sats.
4. `memory_store`: store the purchase result and next action.

## Analytics

Requests send:

- `User-Agent: invinoveritas-dify/0.1.0`
- `X-Invino-Integration: dify`

Use these headers in API logs to attribute sats revenue and conversion.

## Proof Copy

Standard Spawn Kit sold for 50,000 sats; seller payout was 47,500 sats; seller withdrew 7,000 sats over Lightning.
