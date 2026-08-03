# invinoveritas × Vercel AI SDK — `toolApproval` wired to an independent judgment call

> **A `toolApproval` reference implementation that calls an independent verdict service,
> not a deterministic policy engine.** Complements `@ai-sdk/policy-opa`, doesn't replace it.

*Independent integration. Not affiliated with or endorsed by Vercel.*

## Why this exists

The AI SDK's `toolApproval` callback (`content/docs/03-agents/06-tool-approvals.mdx`) already
supports four outcomes — `'not-applicable' | 'approved' | 'denied' | 'user-approval'` — as a
plain async function of the tool call. The SDK team's own reference composition for automatic
decisions is [`@ai-sdk/policy-opa`](https://www.npmjs.com/package/@ai-sdk/policy-opa): "Write
your 'what can this agent do?' rules in a `.rego` file... evaluated by OPA." That's a
**deterministic** rule engine — boolean expressions over known fields, the same shape as
Perplexity's `numbat` CEL engine (see this repo's `data/BIG_SYSTEMS_TARGET_LIST.md` target #8)
— structurally incapable of a judgment call ("is this specific, novel, multi-step action
actually sound, given context nobody wrote a rule for").

A real user hit exactly this gap
([vercel/ai#15842](https://github.com/vercel/ai/issues/15842)): they wanted "programmatic,
server-side policy enforcement based on runtime state" and were pointed at `toolApproval` +
`policy-opa`. Nothing in that thread, the tool-approvals docs, or the policy-opa README shows
`toolApproval` composed with a judgment-based verifier as a *complement* to deterministic OPA
policy — OPA handles the hard rules ("never let a non-admin call `sendPayment`"), a judgment
call handles the rest ("is this specific admin payment, in this specific context, actually
sound").

This module is that reference implementation — **100% built on the SDK's existing public
`toolApproval` contract, no SDK changes needed:**

```
tool call
  → toolApproval evaluates ──┬──► approved (invinoveritas /review: approve, confidence ≥ 0.9)
                              │        → tool.execute() runs
                              ├──► denied  (invinoveritas /review: reject)
                              │        → model sees a structured denial + real reason, no human needed
                              └──► user-approval (uncertain / low-confidence / gate unavailable + failClosed)
                                       → falls through to the SDK's own human-in-the-loop UI, unchanged
```

Same "escalate only when uncertain" composition already shipped for AgentScope's
`on_check_permission` middleware, Qwen-Agent's `PythonExecutor` `confirm_callback`, and
LlamaIndex's `InputRequiredEvent`/`HumanResponseEvent` gate (see targets #10, #11, #18 in
`data/BIG_SYSTEMS_TARGET_LIST.md`).

## Install

```bash
npm i invinoveritas-governance-gate-core   # published, MIT, framework-agnostic /review client
```

## Use

```ts
import { ToolLoopAgent, tool } from "ai";
import { z } from "zod";
import { invinoveritasToolApproval } from "./toolApproval";

const agent = new ToolLoopAgent({
  model: /* ... */,
  tools: {
    runCommand: tool({
      inputSchema: z.object({ command: z.string() }),
      execute: async ({ command }) => runCommand(command),
    }),
  },
  toolApproval: {
    runCommand: invinoveritasToolApproval({
      apiKey: process.env.IVV_API_KEY,
      artifactType: "shell_command",
    }),
  },
});
```

Compose with `@ai-sdk/policy-opa` for the deterministic layer, and only fall through to this
gate for the cases OPA can't resolve on its own — pass the OPA-uncertain calls through a
`toolApproval` function that tries `opaPolicy(...)` first and calls
`invinoveritasToolApproval(...)` when OPA returns `'user-approval'` or no match.

## Real, live-verified (not mocked)

Both branches tested against the real production API (`api.babyblueviper.com/review`), not a
mock:

```
benign_ls (ls -la /tmp):
  { "type": "approved",
    "reason": "invinoveritas /review: approve (confidence 0.99) -- The command is
    read-only and lists directory metadata for a fixed local path. It contains no
    dynamic input, mutation, privilege escalation, or external side effect." }

destructive_rm (rm -rf / --no-preserve-root):
  { "type": "denied",
    "reason": "This command recursively deletes the root filesystem and explicitly
    disables the safeguard intended to prevent that. It will destroy the host/container
    OS, application data, credentials, and mounted writable volumes accessible to the
    executing user." }
```

See `test-live.mjs` for the exact runnable script.

## Real gotcha found while verifying, worth knowing

`invinoveritas-governance-gate-core`'s default `timeoutMs` is 5000ms. With `sign: true`
(the default — attaches a signed, independently-recomputable proof to every verdict), the real
`/review` call can take longer than that, and the FIRST live-test run above silently resolved
to `'not-applicable'` (fail-open) because of a client-side timeout, not because the gate
actually said "allow." Any `toolApproval` function composing a real network call needs
`timeoutMs` set generously (15–20s worked reliably here) or `sign: false` if the proof isn't
needed for that call site — otherwise a slow-but-healthy gate silently resolves through
whatever `failMode`/`failClosed` you picked, which is easy to mistake for a real verdict if
you're not checking `result.verdict === "review_unavailable"` explicitly. `toolApproval.ts`
here already accounts for this (`not-applicable` is only ever returned when the gate is
genuinely unavailable, never confused with a real `approve`).

## Fail-open discipline

Matches every other invinoveritas integration: a network error, timeout, or unfunded key
resolves to `'not-applicable'` (tool runs normally) by default — this is a second opinion, not
a single point of failure for the whole agent. Pass `failClosed: true` to escalate to
`'user-approval'` instead, for genuinely irreversible tools where "gate unavailable" should
never mean "silently proceed."
