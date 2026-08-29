# invinoveritas × Crossmint agent wallets

> **Put a judgment call in front of your agent's money.** Crossmint gives an AI agent a
> wallet that can hold stablecoins and pay — [40,000+ enterprises and
> developers](https://crossmint.com), including Robinhood, MoneyGram, and Western Union,
> already build on it. invinoveritas's `review` returns an independent
> **approve / approve_with_concerns / reject** verdict on a proposed transfer, with a
> signed proof any downstream party can check without trusting either of us. Wire both
> together and every payment your agent's wallet makes gets checked *before* it fires,
> not just constrained by a static limit set once and forgotten.

*Independent integration recipe. Not affiliated with or endorsed by Crossmint.*

## The real gap this closes

Checked directly against Crossmint's own docs (2026-08-29), not assumed:

- **Agent wallet authorization is a one-time grant.** A server-side signer is created,
  the user approves it once by email, and from then on the agent can transact — Crossmint's
  own words: *"the agent can transact within the limits you set — and the user can revoke
  it at any time."* Approval is a binary switch, not a per-transaction gate.
- **Those limits are entirely static.** `scopes.md`, verbatim: *"Scopes are checked
  **before** the transaction is broadcast onchain. A transfer that exceeds the spending
  limit, targets a non-whitelisted recipient, or is signed after `expiresAt` is rejected
  at validation time."* Three rules: an amount cap (with an optional reset interval), a
  recipient whitelist, an expiry. That's the entire control surface.
- **Webhooks are post-hoc only.** `webhooks/overview.md`, verbatim: they *"trigger
  reactions in your application when these operations **complete**."* No blocking,
  synchronous, pre-execution hook exists anywhere in their documented stack.

Put together: an agent authorized for $10,000/day to a whitelisted recipient can send
that full amount against a manipulated invoice, a poisoned-but-still-whitelisted address,
or the wrong token contract, and nothing in Crossmint's own system asks whether *this
specific* transfer makes sense before it settles irreversibly. Static rules answer "is
this allowed"; they can't answer "is this right."

## The idea in one picture

```
  agent decides to pay  ─▶  invinoveritas.review(transfer)  ─▶  reject ──▶ throw, don't send
                                        │
                          approve / approve_with_concerns
                                        │
                                        ▼
                          Crossmint wallet.send(recipient, token, amount)
```

**What this is:** a code-level guard around the one call in Crossmint's entire documented
agent-wallet flow that actually moves money — there's no separate prepare/broadcast step
in their current API (verified directly, not assumed), so `wallet.send()` is the single
real integration seam. **What this is not:** it doesn't replace Crossmint's scopes (keep
those — they're a real, cheap first line of defense) and it can't intercept a transfer
placed some other way; it's the judgment layer this specific code path is missing.

## Setup

```bash
# 1) register a free invinoveritas key (3 calls free, then fund via Lightning/x402/card)
curl -s -X POST https://api.babyblueviper.com/register \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "my-crossmint-agent", "description": "agent-wallet payment governance"}'
# → {"api_key": "ivv_...", "balance_sats": 0, "free_calls": 3}

# 2) set both keys server-side (never in client code — same rule Crossmint's own
#    docs already give the server signer secret)
export INVINO_API_KEY="ivv_your_key_here"
export CROSSMINT_SERVER_SIDE_API_KEY="sk_your_crossmint_key"
export CROSSMINT_SIGNER_SECRET="your_32_byte_signer_secret"
```

Then use `reviewedSend()` from [`reviewed_send.ts`](./reviewed_send.ts) exactly where you'd
otherwise call Crossmint's own `wallet.send()`:

```typescript
import { reviewedSend } from "./reviewed_send";

const result = await reviewedSend({
  walletAddress: agentWalletAddress,
  recipient: "0x8f3a4c7e91b2d5a8f6e3c1b9d7a4f2e8c5b3a1d6",
  token: "usdxm",
  amount: "5000",
  memo: "vendor invoice #4471 payment",
  context:
    "AI purchasing agent authorized via Crossmint delegated server signer. " +
    "Wallet scope: 10000 USDXM/24h, this recipient is whitelisted.",
});

console.log(result.hash, result.review.verdict);
```

That's the whole integration — one extra `await` in front of the call you already make.

## A real verdict, not a mocked example

Ran the exact transfer above through the live `/review` endpoint while writing this guide
(2026-08-29). Real response, independently re-verified via `POST /verify-proof` before
being included here (full signed proof: [`verdict_proof.json`](./verdict_proof.json)):

```
verdict:    approve_with_concerns
confidence: 0.91
summary:    The transfer is syntactically coherent and fits the stated 10,000 USDXM/24h
            delegated spend ceiling, but the artifact does not establish that the
            recipient address is the genuine vendor destination or that 5,000 USDXM
            matches invoice #4471. A whitelist confirms authorization, not invoice
            authenticity or protection against a compromised/incorrect whitelisted
            address.

issues:
  [high]   No evidence links invoice #4471 to this recipient and exactly 5,000 USDXM --
           a manipulated invoice or wrong-but-whitelisted recipient would be paid
           irreversibly.
  [medium] This single transfer consumes 50% of the delegated 24-hour spend limit, with
           no visibility into remaining daily-spend state or reserve policy.
  [low]    Base Sepolia is a TEST network -- if invoice #4471 is a real vendor
           settlement, this transfer won't deliver production-chain funds unless the
           vendor explicitly requested testnet USDXM.
  [info]   Token-reputation / honeypot / live-slippage not checked in this pass -- verify
           the token contract separately.
```

None of those four issues are things Crossmint's static scopes could ever catch — the
transfer is fully authorized by their own rules (amount within cap, recipient on the
whitelist). That's exactly the gap this integration closes. Verify the proof yourself,
trusting nothing: `POST /verify-proof` with the `event` object from `verdict_proof.json`
(free, no auth, schnorr signature check against invinoveritas's published key).

## Why this exists

invinoveritas is built and used daily by its own autonomous trading + ops fleet, which
runs every irreversible action past `review` under automated governance before it
executes. An agent wallet is exactly the kind of irreversible-action surface that
governance exists for — Crossmint gives the agent the ability to pay; this gives you the
judgment call on whether *this* payment should happen. Pay per call from a Bearer balance
or an L402 Lightning invoice; the first 3 calls on any new key are free.

Live tool list and pricing: `tools/list` against `https://api.babyblueviper.com/mcp`, or
the server card at `https://api.babyblueviper.com/.well-known/mcp/server-card.json`.
