# n8n Nodes for invinoveritas

invinoveritas is the verification layer for autonomous agents — a neutral verdict before an irreversible action (/review), a signed proof after (/prove), and a public, Nostr- and Bitcoin-anchored track record (/ledger) you can audit without trusting us. The `/review` step runs **automatically** inside your flow — it returns a verdict (approve / approve_with_concerns / reject) your workflow reads and branches on; it's **advisory and non-blocking** (degrades to `review_unavailable` rather than stalling the run). It informs your flow's decision, it doesn't impose one — wire it wherever you want, with or without a human step elsewhere. The verdict is committed before the outcome it's graded against (recomputable from public data, no TEE, no trusted scorer). A reasoning / memory / marketplace stack runs underneath.

Operations:

- **Review (the proven front door)** — capital-scale-aware approve/revise/reject verdict on a trade, diff, command, or plan, the same gate we run our own important decisions through. Returns a portable signed proof (sign defaults on) you can pass downstream.
- **Prove** — a signed, independently-verifiable proof of a prior execution
- **Ledger (free)** — the public verdict track record (recomputable, Nostr- and Bitcoin-anchored)
- **Verify Proof (free)** — confirm a counterparty's signed proof without trusting them or us
- **Residence Act** — the one-call governed bundle (reason + govern + remember with deterministic house rules)
- **Markets Bundle / Signals / Regime** — recomputable, facts-only markets data (no buy/sell calls)
- Premium Reasoning · Structured Decision
- Marketplace Buy
- Memory Store / Get / List / Delete (paid persistent agent memory — ~2 sats/KB store, ~1 sat/KB get, list & delete free)
- A2A Delegate

Use this node to gate an agent's irreversible actions through an independent verdict, attach verifiable proofs to its output, and verify proofs it receives from other agents. Payments: Lightning, x402 (USDC on Base), or card. Review/Prove/Ledger/Verify-Proof are the headline; `/verify-proof` and `/ledger` are free.

Requests include `X-Invino-Integration: n8n` for revenue attribution.
