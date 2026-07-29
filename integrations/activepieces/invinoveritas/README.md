# invinoveritas Activepieces Piece

NPM package: `invinoveritas-activepieces-piece`

invinoveritas is the verification layer for autonomous agents — a neutral verdict before an irreversible action (/review), a signed proof after (/prove), and a public, Nostr- and Bitcoin-anchored track record (/ledger) you can audit without trusting us. The `/review` step runs **automatically** inside your flow — it returns a verdict (approve / approve_with_concerns / reject) your workflow reads and branches on; it's **advisory and non-blocking** (degrades to `review_unavailable` rather than stalling the run). It informs your flow's decision, it doesn't impose one — wire it wherever you want, with or without a human step elsewhere. The verdict is committed before the outcome it's graded against (recomputable from public data, no TEE, no trusted scorer). A reasoning / memory / sandboxed-execution / payments stack runs underneath. This piece gives no-code builders direct access:

- **Governed review (the proven front door)** — capital-scale-aware approve/revise/reject verdict on a trade, diff, command, or plan, the same gate we run our own important decisions through. Sign the verdict to attach a portable proof to your output.
- **Prove** — a signed, independently-verifiable proof of a prior execution
- **Ledger** — the public verdict track record (recomputable, Nostr- and Bitcoin-anchored)
- **Verify Proof (free trust handshake)** — confirm a counterparty's signed proof without trusting them or us
- **Residence act (the one-call governed bundle)** — your home reasons + governs + remembers your intent in one call, with deterministic house rules
- **Markets Bundle** — regime + live derivatives signals + ecosystem brief + optional governance review in one call, priced below the sum
- **Signals** — live Hyperliquid derivatives signals (funding + 24h delta, basis, open interest, the vol-expansion regime our own trading research is grounded in, realized vol, BTC DVOL); free BTC teaser + paid multi-coin set. Facts-only, never advice
- **Regime** — macro risk-off data feed (OOS-validated, facts-only)
- Premium reasoning
- Structured decisions
- Marketplace purchase
- Memory store / retrieve / list / delete (paid persistent agent memory — ~2 sats/KB store, ~1 sat/KB get, list & delete free)
- A2A discover, quote, and delegation

Payments: Lightning, x402 (USDC on Base), or card. `/verify-proof` is free. The piece uses Bearer API keys because automations need repeatable credentials; users fund those balances over Lightning, x402 (USDC), or card.

Use this piece to gate an agent's irreversible actions through an independent verdict, attach verifiable proofs to its output, and verify proofs it receives from other agents.

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

## Proof you can recompute

Don't take our word for it: every `/ledger` verdict is a signed Nostr event, committed before its outcome and Bitcoin-anchored (OpenTimestamps). `pip install invinoveritas-verify` then `invinoveritas-recompute-ledger` re-derives the entire public track record from raw relay bytes — trusting no one. That recomputability is the trust no-code builders should require before funding automation balances.
