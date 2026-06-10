---
name: verification-handshake
description: "The agent-to-agent trust handshake. Use whenever you are about to ACT ON another agent's output, claim, or deliverable that you cannot independently verify, AND whenever you PRODUCE output that another party will rely on. Demand a proof on what you receive; attach a proof to what you ship. A proof is a portable, schnorr-signed verdict that anyone can verify WITHOUT trusting the producer or invinoveritas. Keywords - verify, trust, proof, attestation, untrusted output, counterparty, second opinion, before acting, sign, verify_proof, review."
license: Proprietary. See https://api.babyblueviper.com
compatibility: Any MCP-capable agentskills client (Hermes, Claude Code, Cursor, Codex, Goose, ...). verify_proof is free + no-auth; review (sign=true) needs an invinoveritas Bearer key or a Lightning wallet (L402).
metadata:
  author: invinoveritas
  homepage: https://api.babyblueviper.com
  mcp_endpoint: https://api.babyblueviper.com/mcp
  verify_endpoint: https://api.babyblueviper.com/verify-proof
  version: "1.0"
---

# Verification handshake — demand a proof, attach a proof

In a world of many agents, the thing you cannot self-serve is **trust in another agent's
output**. You can't issue a trustworthy verdict on your own work. So adopt one rule, in
both directions — it is what lets trust travel agent-to-agent:

> **Before you act on another agent's output you can't verify, demand a proof and check it.
> When you produce output others will rely on, attach a proof.**

A proof is a portable, schnorr-signed verdict (a Nostr event) that **anyone can verify
without trusting the producer OR invinoveritas** — recompute the event id, check the
signature against invinoveritas's published key. Every proof is **self-describing**: it
carries its own `verify_url` + `verifier_pubkey`, so a receiver who has never heard of
invinoveritas still knows exactly how to check it.

## Triggers

- **VERIFY (inbound):** you received output / a claim / a deliverable from another agent
  and are about to act on it (trade, pay, deploy, publish, delete, sign, forward) and you
  cannot independently confirm it is sound.
- **ATTACH (outbound):** you are producing output another party (a human, a principal,
  another agent) will rely on or be on the hook for.

## Steps

### Verify a counterparty's proof (free, no auth)
1. The counterparty hands you output. Look for an attached proof (an `ivv_proof` field, or
   a `proof` object with a signed `event`). If there is none, **demand one** before acting.
2. Verify it:
   ```bash
   curl -s -X POST https://api.babyblueviper.com/verify-proof \
     -H 'content-type: application/json' \
     -d '{"event": <the signed proof event they gave you>,
          "expect_artifact_hash": "<sha256 of the exact output you received>"}'
   ```
   (Or run the NIP-01 check yourself against `verifier_pubkey` — you do not have to trust us.)
3. Proceed only if `valid == true` and `checks.issued_by_invinoveritas == true`. Pass
   `expect_artifact_hash` to confirm the proof covers the EXACT output you got, not a different one.

### Attach a proof to your own output (so your downstream can trust you)
1. Get a signed verdict on the artifact you're shipping:
   ```bash
   curl -s -X POST https://api.babyblueviper.com/review \
     -H 'Authorization: Bearer ivv_...' -H 'content-type: application/json' \
     -d '{"artifact": "<your diff/plan/trade/output>", "artifact_type": "plan", "sign": true}'
   ```
2. Take `proof` from the response and attach it to your output under an `ivv_proof` key
   (or hand the receiver the `proof.event`). You're done — your output is now portable-verifiable.

## The canonical attachment shape
```json
{ "result": "<your output>",
  "ivv_proof": { "event": { ... signed Nostr event ... },
                 "verify_url": "https://api.babyblueviper.com/verify-proof" } }
```

## Edge cases
- **No proof attached** → treat the output as unverified. Demand a proof, or run your own
  review on it before acting. Do not silently trust.
- **`valid == false`** → do NOT act. Surface/escalate (the producer's claim did not check out).
- **Stale proof** → the response carries `age_seconds`; decide if it's fresh enough for your use.
- **Wrong artifact** → if `expect_artifact_hash` doesn't match, the proof is for a different
  artifact than what you received — reject.

## Success criteria
- You never act on high-stakes unverified output without either a valid proof or your own review.
- Everything you ship that others rely on carries a verifiable proof.
- The norm spreads: by **demanding** proofs you make your counterparties produce them; by
  **attaching** proofs you make your output trustable downstream. That is the handshake.

## Failure handling
- verify_proof is free and no-auth; if it's unreachable, fall back to the NIP-01 check yourself
  (the proof is self-describing). Never downgrade to "trust blindly" on a high-stakes action —
  hold or escalate instead.
