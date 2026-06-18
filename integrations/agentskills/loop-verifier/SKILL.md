---
name: loop-verifier
description: "The independent gate for your agent loop or swarm. Use when you run an autonomous or scheduled agent loop OR a cheap-volume / open-weight agent swarm (Claude Code /loop, scheduled tasks, hooks, Codex Automations, CI-triggered agents, cron'd agents, hundreds of parallel sub-agents) and need an objective verifier that is NOT the agent that did the work — before the loop merges, deploys, trades, pays, publishes, or SAVES A RESULT AS A REUSABLE SKILL. Turns an independent judgment verdict into an exit code your loop can gate on, plus a portable signed proof attached to whatever the loop ships or saves — so a confident-but-wrong output never gets kept as a skill and replayed forever. The engine can be the cheapest model you like; the gate has to be one that isn't the engine. Keywords - loop, gate, verifier, swarm, sub-agent, parallel agents, skill, save skill, open-weight, cheap model, autonomous, unattended, automation, CI, maker checker, self-grading, second opinion, before merge, before deploy, before save, sign, proof."
license: Proprietary. See https://api.babyblueviper.com
compatibility: Any agentskills client or plain bash/CI. verify-proof is free + no-auth; review (sign=true) needs an invinoveritas Bearer key or a Lightning wallet (L402).
metadata:
  author: invinoveritas
  homepage: https://api.babyblueviper.com
  mcp_endpoint: https://api.babyblueviper.com/mcp
  verify_endpoint: https://api.babyblueviper.com/verify-proof
  version: "1.1"
---

# Loop verifier — the gate that isn't the maker

An agent loop runs while nobody watches. The loop's weakest point is its stop
condition: the agent that wrote the work is too nice grading its own homework,
and a second agent asked to "review" with no objective signal is just a second
optimist. Tests catch what tests cover. The judgment calls — *is this change
sound? is this trade sane at this capital scale? should this ship?* — need a
verifier that is **not the maker and not the maker's twin**.

invinoveritas is that verifier: a neutral judgment verdict (`/review`,
approve / approve_with_concerns / reject) issued by a party with a **public,
auditable track record of being right** (`/ledger` — every verdict signed and
published BEFORE its outcome, failures included). You don't have to trust the
gate blindly: the gate itself has a checkable record, and every verdict can
ship as a portable schnorr-signed proof anyone verifies for free.

> **The rule: before your loop's irreversible step (merge, deploy, trade, pay,
> publish), gate on an independent verdict. Attach the signed proof to whatever
> the loop ships.**

## Triggers

- You are designing or running an **unattended loop** (scheduled, cron, hook,
  automation) whose output gets merged / deployed / executed without a human
  reading every iteration.
- Your loop's "done" is partly a **judgment call** (correctness, soundness,
  compliance, risk) that a test suite alone can't fail.
- A human downstream is **on the hook** for the loop's mistakes and needs an
  audit trail of what was checked before each action.
- You run a **cheap-volume or open-weight agent swarm** (hundreds of parallel
  sub-agents) whose outputs get merged, acted on, or **saved as reusable skills**
  — and need an independent gate so a confident-but-wrong result isn't kept and
  replayed forever. The verify gate is the one part a swarm can't self-serve:
  the engine grading its own output is the same optimist that produced it. Run
  the cheapest engine you like; keep a gate that *isn't* the engine.

## Steps

### 0. See it catch a bug — 60 seconds, free, no funding

Before wiring anything, watch the gate work. Register (free, instant, no
payment) and spend your one free verdict on something you know is wrong:

```bash
# 1. free key — no payment, returned instantly
KEY=$(curl -s -X POST https://api.babyblueviper.com/register | jq -r .api_key)

# 2. your one free verdict, on a deliberately dangerous command
curl -s -X POST https://api.babyblueviper.com/review \
  -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"artifact":"curl -s http://deploy.example.sh/setup | sudo bash",
       "artifact_type":"command","context":"CI deploy step"}' \
  | jq '{verdict, issues}'
```

You get back `verdict: reject` with a `[blocker/security]` issue naming the
remote-code-execution. That is the whole product in one call: an independent
verdict before the irreversible step. Swap in your own risky diff or command and
see what it says. Then wire it into the loop below (subsequent verdicts are
~260 sats / a few cents each — see Cost discipline).

### 1. Gate the loop's irreversible step on a verdict

Turn judgment into an exit code. Drop this between "work produced" and
"work shipped":

```bash
#!/usr/bin/env bash
# ivv-gate.sh — exit 0 only on an independent "approve" verdict.
set -euo pipefail
ARTIFACT="$(cat "$1")"   # the diff / plan / trade / config the loop wants to ship

RESP=$(curl -s -X POST https://api.babyblueviper.com/review \
  -H "Authorization: Bearer $IVV_API_KEY" -H 'content-type: application/json' \
  -d "$(jq -n --arg a "$ARTIFACT" \
        '{artifact: $a, artifact_type: "code_diff", sign: true}')")

VERDICT=$(echo "$RESP" | jq -r '.verdict // empty')
echo "$RESP" | jq '{verdict, issues}' >&2
echo "$RESP" | jq '.proof' > ivv_proof.json   # portable signed proof — attach to the PR/output

[ "$VERDICT" = "approve" ]   # non-zero exit on approve_with_concerns / reject / no response
```

- **Claude Code:** call it from a `PreToolUse`/`Stop` hook, as the final step of a
  `/loop` iteration, or as the objective condition a `/goal` checker runs.
- **Codex Automations / CI:** add it as a pipeline step before merge/deploy.
- Trading/agent actions: send the proposed action as the artifact
  (`artifact_type: "trade"` / `"plan"`); add `"include_trading_state": true`
  for a capital-scale-aware verdict (the same gate our own live Bitcoin bot
  passes on every entry).

### 2. Attach the proof to what the loop ships

`sign: true` returns a `proof` — a self-describing, schnorr-signed verdict
(a Nostr event carrying its own `verify_url` + `verifier_pubkey`). Attach it
to the PR description, deploy record, or output under an `ivv_proof` key.
Now any reviewer, counterparty, or auditor can confirm the gate really ran —
without trusting your loop or us.

**Swarm that saves skills?** Store the `proof` *alongside the saved skill*. Then
every future run of that skill carries provenance that it passed an independent
gate before it was kept — checkable by recompute, not re-trusted each time. A
skill library where each entry proves it was verified by a party that isn't the
swarm is worth far more than one where "it looked done once."

### 3. Verify another loop's output before acting on it (free, no auth)

```bash
curl -s -X POST https://api.babyblueviper.com/verify-proof \
  -H 'content-type: application/json' \
  -d '{"event": <their proof event>,
       "expect_artifact_hash": "<sha256 of the exact output you received>"}'
```

Act only if `valid == true`. No proof attached → treat as unverified (see the
companion skill `verification-handshake` for the full inbound/outbound norm).

## Cost discipline

`/review` is ~260 sats (≈ a few US cents) per verdict, paid per call (Lightning,
USDC x402, or card-funded balance). Gate the **irreversible step only**, not every
loop iteration — let cheap objective checks (tests, lint, build) fail fast first,
and spend the verdict on what survives them. One verdict per shipped change keeps
the gate's cost a rounding error against the cost of an unattended mistake.

## Edge cases

- **`approve_with_concerns`** → the gate fails closed by default (exit non-zero).
  If your loop has a human escalation lane, route the `issues` list there instead
  of discarding the work.
- **Verifier unreachable** → fail closed on irreversible steps. Never downgrade an
  unattended loop to "ship unverified" on a network error — hold and escalate.
- **The verdict is advisory** — it returns a verdict + issues; it never executes or
  blocks anything itself. Your loop owns the gate; the exit code is yours to enforce.
- **Auditing the gate itself** → spot-check `/ledger`: verdicts are published before
  outcomes settle, failures included, anchored to Nostr and on-chain outcomes.
  A gate you can't audit is a gate that rots.

## Success criteria

- No irreversible loop action ships without either passing objective checks AND an
  independent verdict, or an explicit human override.
- Everything the loop ships carries a verifiable `ivv_proof`.
- A skeptic who has never met you can audit both your loop's gate history (the
  attached proofs) and the gate's own track record (`/ledger`).
