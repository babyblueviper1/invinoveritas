# invinoveritas Review Plugin for cpex / ContextForge

> Author: babyblueviper1
> Version: 0.2.0

Gates `tool_pre_invoke` on an independent, signed pre-action verdict from
[invinoveritas](https://api.babyblueviper.com) — a judgment call about whether a
specific tool invocation is sound, not a static rule. Grew out of
[IBM/mcp-context-forge#5437](https://github.com/IBM/mcp-context-forge/issues/5437)
(Human in the loop Approval for tool execution): a `risk_tier`/`gate.mode` rule engine
can decide *whether* a human or policy needs to look at a call; it structurally cannot
decide *whether this specific, novel action is actually sound* — that needs a judgment
call, which is what `/review` does.

Originally shipped as [IBM/mcp-context-forge#6014](https://github.com/IBM/mcp-context-forge/pull/6014)
(closed, not merged — the maintainer pointed contributors at
[contextforge-org/cpex](https://github.com/contextforge-org/cpex) instead as the
shared plugin marketplace is built out). This is the canonical source until that
marketplace's submission model is finalized — see
[contextforge-org/cpex#159](https://github.com/contextforge-org/cpex/issues/159).

## Features

- Calls `POST /review` before every tool invocation with `{tool_name, arguments}` as the
  artifact.
- **Caller-identity enrichment (new, 0.2.0):** when the host gateway populates
  `PluginContext.user_context` (cpex's structured identity: user id/email, groups,
  roles, `is_admin`, `auth_method`, `service_account`, `delegation_chain`), a snapshot
  is folded into both the `/review` `context` string (for the human reviewer) and the
  hashed `artifact` JSON itself — so a `sign: true` proof commits to *who the gateway
  says was really behind this call*, not just the tool name and arguments. Two callers
  presenting different identities for identical arguments now produce different
  `artifact_hash`/`decision_ref` values, intentionally. Only fields the gateway
  explicitly set are included (via Pydantic's `model_fields_set`, not a raw
  None/empty check — a plain value check can't tell "confirmed not-admin" from
  "never told us," since `is_admin` defaults to `False` either way). Set
  `include_caller_identity: false` to opt out entirely; when the gateway never
  populates `user_context` at all, behavior is identical to the original 0.1.0 plugin.
  **Honest scope:** this does not change invinoveritas's own `/review` response
  `source_class` field — that's driven server-side by whether the *calling API key*
  is a registered mediator, a separate mechanism. This makes the review's evidentiary
  basis richer; it does not by itself upgrade the verdict's trust tier.
- A `reject` verdict blocks the call by default (`block_on_reject: true`); set to `false`
  for an advisory/observe-only rollout that never blocks, only annotates the result.
- **Fails open** on any `/review`-side problem (network error, timeout, malformed
  response, missing API key, or even identity-extraction blowing up) — the tool call
  proceeds ungated rather than hanging or crashing the gateway;
  `metadata["invinoveritas_review"] = "unavailable"` is set so this is visible, not
  silent.
- Optional `sign: true` attaches a portable, independently-verifiable signed proof
  (verify at `https://api.babyblueviper.com/verify-proof`, free, no auth) to every
  verdict.
- Zero framework changes — a normal `cpex.framework.Plugin` hooking `tool_pre_invoke`.

## Installation

1. Register free, instant, no payment: `POST https://api.babyblueviper.com/register`
2. Set `IVV_API_KEY` in your environment, or pass `api_key` directly in the plugin config
   below (env var is preferred — don't commit a key to `config.yaml`).
3. Add the plugin configuration to your gateway's `plugins/config.yaml`:

```yaml
plugins:
  - name: "InvinoveritasReviewPlugin"
    kind: "invinoveritas_review.InvinoveritasReviewPlugin"
    description: "Gates tool_pre_invoke on an independent invinoveritas /review verdict."
    version: "0.2.0"
    author: "babyblueviper1"
    hooks: ["tool_pre_invoke"]
    tags: ["plugin", "safety", "review", "human-in-the-loop"]
    mode: "enforce"  # enforce | permissive | disabled
    priority: 100
    config:
      base_url: "https://api.babyblueviper.com"
      block_on_reject: true
      sign: false
      artifact_type: "general"
      timeout_s: 15.0
      include_caller_identity: true
```

## Relationship to a rule-based PDP (e.g. `unified_pdp`)

This plugin is deliberately **not** a replacement for a rule engine — it answers a
different question. A PDP like `unified_pdp` decides *eligibility* (may this
actor/tool/resource combination happen at all, per policy) deterministically and fast.
`InvinoveritasReviewPlugin` decides *soundness for this specific payload* — the same
tool call with different arguments can be fine or genuinely risky, which a static rule
can't distinguish without an explosion of conditions. Run both: PDP first (cheap,
deterministic, denies the clearly-disallowed), review second (judgment, for what the PDP
lets through). Every `/review` verdict is independently checkable via
`/verify-proof` — recompute it yourself, don't trust the plugin's word for it.

## Testing

```bash
pip install cpex httpx pytest pytest-asyncio  # in an isolated venv
pytest integrations/contextforge-cpex/tests/test_invinoveritas_review.py -v
```

No live API key needed — all 11 tests run against `httpx.MockTransport`: the original 6
(reject-blocks, advisory-mode-never-blocks, approve-passes-through,
fail-open-on-timeout, fail-open-on-malformed-response, no-api-key-skips-the-call) plus 5
new ones covering caller-identity enrichment (folded into artifact+context, omitted when
no `user_context`, opt-out via config, `is_admin`-default-vs-explicit boundary,
extraction-failure still fails open).
