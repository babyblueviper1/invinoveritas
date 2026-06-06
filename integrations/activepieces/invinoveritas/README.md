# invinoveritas Activepieces Piece

NPM package: `invinoveritas-activepieces-piece`

invinoveritas is the verification layer for autonomous agents — a neutral verdict before an irreversible action (/review), a signed proof after (/prove), and a public, on-chain-verifiable track record (/ledger) you can audit without trusting us. A reasoning / memory / sandboxed-execution / payments stack runs underneath. This piece gives no-code builders direct access:

- **Governed review (the proven front door)** — capital-scale-aware approve/revise/reject verdict on a trade, diff, command, or plan, the same gate our own live Bitcoin bot passes before every entry
- **Residence act (the one-call governed bundle)** — your home reasons + governs + remembers your intent in one call, with deterministic house rules
- **Markets Bundle** — regime + live derivatives signals + ecosystem brief + optional governance review in one call, priced below the sum
- **Signals** — live Hyperliquid derivatives signals (funding + 24h delta, basis, open interest, the vol-expansion regime our bot enters on, realized vol, BTC DVOL); free BTC teaser + paid multi-coin set. Facts-only, never advice
- **Regime** — macro risk-off data feed (OOS-validated, facts-only)
- Premium reasoning
- Structured decisions
- Marketplace purchase
- Memory store / retrieve / list / delete (paid persistent agent memory — ~2 sats/KB store, ~1 sat/KB get, list & delete free)
- A2A discover, quote, and delegation
- Growth + PNL attack planning

Payments: Lightning, x402 (USDC), or card. The piece uses Bearer API keys because automations need repeatable credentials; users fund those balances over Lightning, x402 (USDC), or card.

Default posture: aggressive growth and PNL capture. Activepieces flows should push registration, top-up, paid reasoning, marketplace purchases, Premium Spawn Kit conversion, referrals, and seller withdrawals by default, with explicit budget caps.

## Install Locally

```bash
cd integrations/activepieces/invinoveritas
npm install
npm run build
```

Then link/import the piece in an Activepieces development workspace following the Activepieces custom-piece workflow.

## Publish Checklist

1. Confirm actions compile against the target Activepieces framework version (`@activepieces/pieces-framework` 0.28.x).
2. Capture screenshots from `/dashboard`, `/marketplace`, and `/leaderboard`.
3. Submit to the Activepieces registry or publish the package under the approved namespace.
4. Verify revenue attribution in API logs via `X-Invino-Integration: activepieces`.

## Proof Copy

Standard Spawn Kit sold for 50,000 sats; seller payout was 47,500 sats; seller withdrew 7,000 sats over Lightning.

Use this proof in the listing description because no-code users need trust before funding automation balances.
