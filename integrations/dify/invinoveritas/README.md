# invinoveritas Dify Tool Plugin

invinoveritas is the verification layer for autonomous agents — a neutral verdict before an irreversible action (/review), a signed proof after (/prove), and a public, Nostr- and Bitcoin-anchored track record (/ledger) you can audit without trusting us. The verdict is committed before the outcome it's graded against (recomputable from public data, no TEE, no trusted scorer). A reasoning / memory / sandboxed-execution / payments stack runs underneath. This plugin exposes it to Dify workflows:

- **Governed review (the proven front door): `/review`** — a capital-scale-aware approve/revise/reject verdict on a trade, diff, command, or plan, the same gate we run our own important decisions through. Sign the verdict to attach a portable proof to your output.
- **Verify proof (free trust handshake): `/verify-proof`** — confirm a counterparty's signed proof without trusting them or us
- **Residence act (the one-call governed bundle): `/residence/act`** — your home reasons + governs + remembers your intent in one call, with deterministic house rules
- **Markets Bundle: `/markets/act`** — regime + live derivatives signals + ecosystem brief + optional governance review in one call, priced below the sum
- **Signals: `/signals` (free BTC teaser) + `/signals/full`** — live Hyperliquid derivatives signals (funding + 24h delta, basis, open interest, the vol-expansion regime our own trading research is grounded in, realized vol, BTC DVOL). Facts-only, never advice
- **Regime: `/regime`** — macro risk-off data feed (OOS-validated, facts-only)
- Premium reasoning: `/reason`
- Structured decision making: `/decision`
- Marketplace purchases: `/offers/buy`
- Persistent memory: `/memory/store`, `/memory/get`
- A2A delegation: `/a2a`

Payments: Lightning, x402 (USDC on Base), or card. `/verify-proof` is free. Users register free at `https://api.babyblueviper.com/register`, then top up with Lightning, x402 (USDC), or card to make paid calls. The plugin uses Bearer API keys for automation reliability while preserving L402/Bearer sats economics.

Use this plugin to gate an agent's irreversible actions through an independent verdict, attach verifiable proofs to its output, and verify proofs it receives from other agents.

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

- `User-Agent: invinoveritas-dify/0.3.0`
- `X-Invino-Integration: dify`

Use these headers in API logs to attribute sats revenue and conversion.

## Proof you can recompute

Don't take our word for it: every `/ledger` verdict is a signed Nostr event, committed before its outcome and Bitcoin-anchored (OpenTimestamps). `pip install invinoveritas-verify` then `invinoveritas-recompute-ledger` re-derives the entire public track record from raw relay bytes — trusting no one.
