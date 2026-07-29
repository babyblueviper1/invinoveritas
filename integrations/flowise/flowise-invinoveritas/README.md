# Flowise Components for invinoveritas

invinoveritas is the verification layer for autonomous agents — a neutral verdict before an irreversible action (/review), a signed proof after (/prove), and a public, Nostr- and Bitcoin-anchored track record (/ledger) you can audit without trusting us. The `/review` step runs **automatically** inside your flow — it returns a verdict (approve / approve_with_concerns / reject) your workflow reads and branches on; it's **advisory and non-blocking** (degrades to `review_unavailable` rather than stalling the run). It informs your flow's decision, it doesn't impose one — wire it wherever you want, with or without a human step elsewhere. The verdict is committed before the outcome it's graded against (recomputable from public data, no TEE, no trusted scorer). A reasoning / memory / sandboxed-execution / payments stack runs underneath.

Components:

- **invinoveritas Review (the proven front door)** — capital-scale-aware approve/revise/reject verdict on a trade, diff, command, or plan, the same gate we run our own important decisions through. Set `sign` to attach a portable signed proof to your output.
- **invinoveritas Prove** — a signed, independently-verifiable proof of a prior execution
- **invinoveritas Ledger** — the public verdict track record (recomputable, Nostr- and Bitcoin-anchored)
- **invinoveritas Verify Proof (free trust handshake)** — confirm a counterparty's signed proof without trusting them or us
- **invinoveritas Residence Act (the one-call governed bundle)** — your home reasons + governs + remembers your intent in one call, with deterministic house rules
- **invinoveritas Markets Bundle** — regime + live derivatives signals + ecosystem brief + optional governance review in one call, priced below the sum
- **invinoveritas Signals** — live Hyperliquid derivatives signals (funding + 24h delta, basis, open interest, the vol-expansion regime our own trading research is grounded in, realized vol, BTC DVOL); free BTC teaser + paid multi-coin set. Facts-only, never advice
- **invinoveritas Regime** — macro risk-off data feed (OOS-validated, facts-only)
- invinoveritas Reason
- invinoveritas Decision
- invinoveritas Memory Store / Get / List / Delete (paid persistent agent memory — ~2 sats/KB store, ~1 sat/KB get, list & delete free)

Use these components to gate an agent's irreversible actions through an independent verdict, attach verifiable proofs to its output, and verify proofs it receives from other agents. Payments: Lightning, x402 (USDC on Base), or card. `/verify-proof` is free.

Requests include `X-Invino-Integration: flowise` for revenue attribution.
