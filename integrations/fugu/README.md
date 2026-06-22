# invinoveritas × Sakana Fugu — the independent gate an orchestrator can't self-staff

[Sakana Fugu](https://sakana.ai/fugu) orchestrates a pool of frontier models (GPT-5.5,
Claude Opus, Gemini 3.1 Pro, …) behind **one OpenAI-compatible API** — and **its routing is
withheld by design** ("the underlying models Fugu selects and its coordination logic are
proprietary and not exposed by design"). Fugu's TRINITY layer even assigns a **Verifier** role
— but it's *in-pool*: one swapped model grading the others.

The one role an orchestrator **cannot** self-staff is an **independent** verifier *outside* the
pool. You can't sign your own homework, and an opaque pool grading itself is the same optimist
that produced the work. This adapter is that gate: it runs Fugu as the engine, then — before any
irreversible step — gets a neutral, capital/risk-aware verdict from
[invinoveritas](https://api.babyblueviper.com) (`/review`) plus a **portable, schnorr-signed
proof** anyone re-checks for free (`/verify-proof`), with no trust in Fugu *or* us.

Why it matters more for an orchestrator than a single model:

- **Opaque routing → attribution gap.** When a consequential action came from an undisclosed
  model the user can't see, "which model produced this, committed when" is unanswerable from
  the inside. The signed verdict pins what was checked, before the outcome is known.
- **"Routes around export controls" → more oversight, not less.** A deployer routing around
  vendor restrictions needs *stronger* documented oversight (EU AI Act, Colorado AI Act), not
  weaker. The proof is the recomputable oversight evidence.

## Install

```bash
pip install requests        # the adapter is zero-framework; Fugu is OpenAI-compatible
export FUGU_API_KEY=...      # from https://console.sakana.ai
export IVV_API_KEY=$(curl -s -X POST https://api.babyblueviper.com/register | jq -r .api_key)
```

`verify_proof` is free and needs no key; `review` (with `sign=true`) needs the free invinoveritas
Bearer key above (or a Lightning wallet via L402). ~260 sats (a few cents) per verdict.

## Use it

```python
from fugu_verified import fugu_verified

res = fugu_verified(
    task="Write a migration that drops the legacy `sessions` table and backfills `auth_events`.",
    artifact_type="code_diff",          # code_diff | command | trade | plan | text
    context="production database, single run",
    require="approve",                  # gate: block unless verdict is at least this good
    fugu_model="fugu-ultra",
)

if res["blocked"]:
    raise SystemExit(f"Fugu output blocked by independent verdict: {res['verdict']} — {res['issues']}")

print(res["output"])          # Fugu's answer, now independently cleared
# res["proof"] is a portable signed verdict — attach it to the PR / action / audit log
```

Drop it between **"Fugu produced work"** and **"work ships"** (merge, deploy, trade, pay,
publish). The gate turns an opaque orchestration into something a downstream human-on-the-hook
can audit: re-run `verify-proof` against the sha256 of the exact output to confirm the gate ran
on *this* artifact.

## The rule

> Run the cheapest / most-orchestrated engine you like. Keep a gate that **isn't** the engine,
> and ship the proof of what it checked.

Same gate our own live Bitcoin trading bot runs on itself (`include_trading_state=true` for a
capital-scale-aware verdict). Track record is public and recomputable: `https://api.babyblueviper.com/ledger`.
