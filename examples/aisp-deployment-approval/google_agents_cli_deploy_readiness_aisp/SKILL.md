---
name: google-agents-cli-deploy-readiness-aisp
description: >
  This skill should be used when the user wants to "deploy with human approval",
  "verify a deployment approval", "resolve the effective agents-cli deploy plan",
  or needs a forced-blocking gate before `agents-cli deploy`.
  Covers resolving CLI flags + agents-cli-manifest.yaml into a plan, presenting
  that plan at sys.io.confirm, and refusing to deploy unless signed approval
  evidence verifies against the current plan.
  Part of the AISP companion to the Google ADK (Agent Development Kit) skills suite.
  Do NOT use for the deploy mechanics themselves (use google-agents-cli-deploy),
  evaluation (use google-agents-cli-eval), or project scaffolding
  (use google-agents-cli-scaffold).
metadata:
  author: babyblueviper1 / invinoveritas
  license: Apache-2.0
  version: 0.1.0
  protocol: AISP V1.0.0
  issue: https://github.com/google/agents-cli/issues/48
  requires:
    bins:
      - agents-cli
      - python3
    install: "uv tool install google-agents-cli && pip install coincurve pyyaml"
    python:
      - coincurve
---

# ADK Deploy Readiness (signed human approval)

> **Requires:** `agents-cli` (`uv tool install google-agents-cli`) and `pip install coincurve`.
> The executable source of truth for the AISP flow is same-folder `aisp.aisop.json`.
> This file is the Agent Skills / coding-agent guide, in the same register as
> `/google-agents-cli-deploy`.

> Prefer `agents-cli` for the actual deploy. This skill does **not** replace
> `/google-agents-cli-deploy`. It adds the missing runtime enforcement for
> that skill's standing instruction: **Never run `agents-cli deploy` without
> explicit human approval.**

### Reference Files

| File | Contents |
|------|----------|
| `aisp.aisop.json` | AISOP flow + `aisp_contract.non_negotiable` (the red lines) |
| `../resolve_agents_cli_plan.py` | Effective-plan resolver (prototype; honest coverage gaps) |
| `../deployment_approval_example.py` | v2 digest / BIP-340 sign / verify (tested) |
| `scripts/approval_verifier.py` | Thin composition wrapper the AISOP node calls |
| `schemas/approval-response.schema.json` | Approval-envelope JSON shape |
| `schemas/effective-deployment-plan.schema.json` | Load-bearing plan shape + mapped-vs-absent notes |
| `evals/vectors/` | Fixed v2 cross-language fixtures (symlink, not regenerated) |

---

## Why this exists

`/google-agents-cli-deploy` tells the coding agent to notify the human and wait
for explicit approval, then run `agents-cli deploy`. That instruction has **no
corresponding runtime gate** in `cmd_deploy.py` — the only `click.confirm()`
there checks *which GCP project* was resolved (`--no-confirm-project`), not
*whether to deploy at all*. The same skill also tells the agent to pass
`--no-confirm-project` so it can run unattended.

Concrete failure mode: a coding agent under time pressure, or one whose
context got compacted past the skill instruction, calls
`agents-cli deploy --no-confirm-project` straight through. No human ever
sees the plan, and nothing downstream can distinguish "a human approved this"
from "the agent decided approval wasn't needed this time."

This skill closes that gap **outside** agents-cli (we do not have write
access there) by composing three real pieces:

1. Resolve the **effective** plan from real CLI flags + `agents-cli-manifest.yaml`.
2. Block at `sys.io.confirm` with `options=['approve','reject','modify']`.
3. `sys.assert` on the structured result of the v2 verifier — the LLM does
   not decide that a signature "looks valid."

---

## Deploy-with-approval workflow

**Task tracking:** Keep a task list. Skipping resolve or verify is how an
unapproved deploy sneaks through.

1. If prototype (no deployment target), first enhance: `agents-cli scaffold enhance . --deployment-target <target>`
2. Collect the exact `agents-cli deploy` flags you are about to pass, and load `agents-cli-manifest.yaml`.
3. Resolve the effective plan:
   ```bash
   python3 scripts/approval_verifier.py resolve \
     --flags flags.json \
     --manifest /path/to/agents-cli-manifest.yaml
   ```
4. **Notify the human** with the complete resolved plan, including which
   load-bearing fields the resolver could **not** map (those are absent, not
   fabricated).
5. **Wait for explicit approval** via `sys.io.confirm`. Do not auto-approve.
   The human replies with one of:
   - `approve { ...approval envelope... }`
   - `reject { "reason": "..." }`
   - `modify { "region": "europe-west1", "reason": "..." }`
6. On `approve`: pass the **raw** approval payload (not an LLM paraphrase) to
   ```bash
   python3 scripts/approval_verifier.py verify \
     --flags flags.json \
     --manifest /path/to/agents-cli-manifest.yaml \
     --approval approval.json
   ```
   Proceed only if `valid` is true.
7. On `modify`: apply the requested changes, **re-resolve**, and return to
   step 4. A previous approval must never silently carry over.
8. On `reject` or a failed verify: **stop**. Do not run `agents-cli deploy`.
9. Once verified: `agents-cli deploy` with the **same flags** that produced
   the plan.

**IMPORTANT**: Never run `agents-cli deploy` without an explicit human
decision on the resolved plan. Never treat a verified approval for plan A as
authorization for plan B.

> **Do NOT invent missing plan fields.** `rollback_plan`, `eval_evidence`,
> `python_version`, `environment`, and `observability_requirements` have no
> first-class agents-cli source today. Leave them absent, or supply them
> only via `--supplements` as an explicit out-of-band human/policy fill.
> `build_approval_response` will refuse a production approval that is still
> missing `rollback_plan` or `source_revision` — that is the fail-closed
> behavior, not a bug.

---

## Flag / manifest mapping (what the resolver actually knows)

CLI flags override manifest values where both exist. That is the same rule
`cmd_deploy.py` uses (`--deployment-target` overrides
`create_params.deployment_target`; `--region` overrides `region`;
`--service-name` overrides `name`).

| Load-bearing field | Real agents-cli source | Status |
|--------------------|------------------------|--------|
| `deployment_target` | `--deployment-target` / `create_params.deployment_target` | mapped |
| `gcp_project` | `--project` (then `GOOGLE_CLOUD_PROJECT`; not ADC/gcloud) | mapped |
| `region` | `--region` / manifest `region` (create default `us-east1`) | mapped |
| `service_name` | `--service-name` / manifest `name` (create fallback `agent`; rejected on GKE) | mapped |
| `service_account` | `--service-account` | mapped |
| `resource_sizing` | `--cpu --memory --min-instances --max-instances --concurrency` (create defaults from `deploy/_utils.py`; rejected on GKE) | mapped |
| `network_exposure` | `--iap`, `--network-attachment`, `--dns-peering-*`, Cloud Run hardcoded `--no-allow-unauthenticated` | mapped (assembled dict) |
| `secret_policy_digest` | `--secrets` (digest of secret *ids*, never values) | mapped |
| `source_revision` | `--image` only (image URI, not a git SHA) | **partial** |
| `environment` | — | **absent** |
| `python_version` | — (`language` is a family, not a version) | **absent** |
| `eval_evidence` | — (separate `agents-cli eval` family) | **absent** |
| `rollback_plan` | — (prose in `/google-agents-cli-deploy`, no flag) | **absent** |
| `observability_requirements` | — (separate observability skill) | **absent** |

Print the same table from the resolver:

```bash
python3 ../resolve_agents_cli_plan.py --mapping-table
```

---

## What is real vs. what is a prototype

- **Real, tested:** the v2 digest / BIP-340 signature / structured
  verification, including tamper, scope-forgery, replay, presentational-edit,
  and JCS-safe-subset tests. Fixtures in `evals/vectors/` are the committed
  v2 vectors, reused not regenerated.
- **Real, but a prototype adapter:** `resolve_agents_cli_plan.py`. It reads
  the public `cmd_deploy.py` option set and the public manifest schema. It
  does **not** call `gcloud`, does **not** read live Cloud Run state on
  update, and does **not** invent sources for the absent fields above. A
  native `agents-cli deploy --plan-json` would replace this adapter.
- **Not this package:** the human-response Runtime. That already exists in
  SoulBot (`sys.io.confirm` → `WAITING_USER` → raw `USER_ANSWER`). This
  skill declares the confirm step; it does not reimplement the Runtime.
- **Not this package:** IdP authentication of `approver`. Optional
  higher-assurance policy, not an AISP core primitive.

---

## Related Skills

- `/google-agents-cli-deploy` — Deployment targets, flags, CI/CD, rollback prose
- `/google-agents-cli-eval` — Evaluation methodology; not consumed by deploy today
- `/google-agents-cli-observability` — Cloud Trace, logging, BigQuery Analytics
- `/google-agents-cli-scaffold` — Project creation / `agents-cli-manifest.yaml`
- `/google-agents-cli-workflow` — Development workflow and operational rules
