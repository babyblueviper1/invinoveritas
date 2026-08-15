# `google_agents_cli_deploy_readiness_aisp`

AISP skill package for [google/agents-cli#48](https://github.com/google/agents-cli/issues/48):
an `agents-cli` deployment-approval and plan-binding candidate skill (not the
complete deployment-readiness lifecycle — see Scope below) that composes a
**real agents-cli plan resolver** with the already-tested v2 signed-approval
verifier, and declares the `sys.io.confirm` / `sys.assert` red lines
optimization2026 specified. "Conforming" is reserved for after official AISP
validation evidence is posted, per his review — this is a candidate package.

This lives in *our* repo as a runnable prototype. It is not a PR against
`google/agents-cli` (not our repo, not asked for).

```
google_agents_cli_deploy_readiness_aisp/
├── aisp.aisop.json          # AISOP flow + aisp_contract.non_negotiable
├── README.md                # this file
├── SKILL.md                 # coding-agent guide (agents-cli skill register)
├── scripts/
│   ├── approval_verifier.py           # resolve + verify + deploy-check, local imports only
│   ├── deployment_approval_example.py # v2 digest / BIP-340 / verify (local copy)
│   ├── resolve_agents_cli_plan.py     # effective-plan adapter (local copy)
│   └── test_deploy_binding.py         # A→B service_account drift must refuse
├── schemas/
│   ├── approval-response.schema.json
│   └── effective-deployment-plan.schema.json
└── evals/
    └── vectors/             # real copies of the v2 fixtures, not a symlink
```

Self-contained: everything under this directory is a real file, not a
symlink or a `sys.path` reach into the parent `examples/aisp-deployment-approval/`
directory. Verified by copying this whole folder to an isolated location with
zero access to the outer directory and running `scripts/approval_verifier.py
--demo` there — full resolve → refuse-incomplete → supplement → build →
verify → tamper-fail sequence passes. Fixed 2026-08-15 in response to
optimization2026's packaging review (the two sibling modules and the
`evals/vectors` symlink previously reached outside the Skill Folder).

## How it composes with `agents-cli deploy`

```
CLI flags + agents-cli-manifest.yaml
        ↓
resolve_agents_cli_plan.py          ← prototype adapter, honest coverage
        ↓
effective plan (mapped fields only)
        ↓
sys.io.confirm  options=['approve','reject','modify']
        ↓
raw USER_ANSWER
        ↓
approve → scripts/approval_verifier.py verify   (LLM does not judge crypto)
        ↓
sys.assert on approval_verification.valid
        ↓
scripts/approval_verifier.py deploy-check
        (re-resolve live flags+manifest, compare every execution-relevant
         field to the already-approved plan; refuse on any divergence)
        ↓
agents-cli deploy   (only if deploy-check reports bound=true)
```

`modify` returns to resolve. A previous approval must not carry over.
`reject`, a failed verify, or a failed deploy-check stops without deploy.

There is no native `agents-cli deploy --plan-json`. The deploy-check is
the adapter-level substitute: the human approved a resolved plan, and
deploy is refused unless a *fresh* resolve of the live flags/manifest
still produces the same execution-relevant values. Approving a projection
and then running a drifted flag set is the gap this closes.

The human-response Runtime is SoulBot's existing `sys.io.confirm` path, not
this package. The v2 script does not need to become the human channel.

## What is real (tested)

- Plan digest (`sha256` of a JCS-safe-canonicalized load-bearing subset)
- BIP-340 Schnorr approval envelope (`build_approval_response` /
  `verify_approval`)
- Independent `approved_scope` checks, signed `approval_conditions`,
  domain separation, in-memory replay demo, fail-closed required-field
  validation, JCS-safe subset enforcement
- Fixed fixtures under `evals/vectors/` — real copies of the v2 fixtures,
  not a symlink

Run the existing v2 suite:

```bash
pip install coincurve
python3 scripts/deployment_approval_example.py
```

Run the composition (resolve a real-shaped plan, refuse it as incomplete,
supplement only the honestly-absent fields, build, verify, tamper):

```bash
python3 scripts/approval_verifier.py --demo
```

## What is a prototype (honest coverage)

`resolve_agents_cli_plan.py` is an adapter over the **public**
`cmd_deploy.py` option set and the **public** manifest template, cloned
fresh from `https://github.com/google/agents-cli` on 2026-08-13. It is not
wired into agents-cli and does not claim to be a native `--plan-json`.

### Mapped (real 1:1 or documented merge)

| Field | CLI flag | Manifest key |
|-------|----------|--------------|
| `deployment_target` | `--deployment-target` / `-d` | `create_params.deployment_target` |
| `gcp_project` | `--project` (then `GOOGLE_CLOUD_PROJECT`) | — |
| `region` | `--region` | `region` (create default `us-east1`) |
| `service_name` | `--service-name` | `name` (create fallback `agent`; rejected on GKE) |
| `service_account` | `--service-account` | — |
| `resource_sizing` | `--cpu --memory --min-instances --max-instances --concurrency` | — (create defaults from `deploy/_utils.py`; rejected on GKE) |
| `network_exposure` | `--iap`, `--network-attachment`, `--dns-peering-*`, Cloud Run hardcoded `--no-allow-unauthenticated` | — (assembled JCS-safe dict) |
| `secret_policy_digest` | `--secrets` | — (sha256 of secret **ids**, never values) |

**Precedence, explicit:** a CLI flag overrides the manifest value for the
same field. That is what `cmd_deploy.py` does
(`cfg.deployment_target = deployment_target` when the flag is set;
`region = region or cfg.region`; `resolve_service_name(cfg, override)`).

### Partial

| Field | What exists | What does not |
|-------|-------------|----------------|
| `source_revision` | `--image` (container URI; Cloud Run / GKE only) | git SHA, source digest, a `--source-revision` flag. From-source deploys (`--source .`) capture no revision. `pyproject.toml [project].version` is `AGENT_VERSION`, not mapped. |

### Honestly absent (left out of `plan`, not fabricated)

| Field | Why |
|-------|-----|
| `environment` | No `--environment` on deploy. staging/prod are infra/CI-CD project IDs. |
| `python_version` | `language` is `python\|go\|java\|typescript`. Scaffold `requires-python` is a range (`>=3.11,<3.14`), not a pin. |
| `eval_evidence` | Separate `agents-cli eval` family. `deploy` does not read grade artifacts. |
| `rollback_plan` | No flag, no manifest key, no `agents-cli rollback`. The deploy skill's rollback section is prose. |
| `observability_requirements` | Separate observability skill / `infra single-project`. |

`validate_plan_completeness` still requires `rollback_plan` and
`source_revision` for a production approval. `rollback_plan` is a
policy supplement (no agents-cli source). `source_revision` is an
execution input — it only appears when `--image` was passed; it cannot
be invented via `--supplements`. A from-source deploy has no captured
revision and stays incomplete. That is the point of fail-closed, not a
gap to paper over.

`--supplements` is split in two:

| Category | Fields | Allowed? |
|----------|--------|----------|
| Policy / evidence | `environment`, `eval_evidence`, `rollback_plan`, `observability_requirements`, `python_version` | Yes, only when honestly absent |
| Execution input | `deployment_target`, `gcp_project`, `region`, `service_name`, `service_account`, `source_revision`, `resource_sizing`, `network_exposure`, `secret_policy_digest` | **No.** Must come from CLI flags / manifest so they bind to deploy. |

`--supplements` will error if you try to override a field the resolver
already mapped, **or** if you try to inject an execution input that
never came from agents-cli. The deploy-check then re-resolves live
flags/manifest and refuses if any execution-relevant field has drifted
from the approved plan (e.g. approved `service_account=A`, live flags
now resolve to `B`).

### Unmapped CLI flags (recognized, not captured)

These are real `cmd_deploy.py` options. The resolver accepts them
(`normalize_cli_flags`) and reports them on
`unmapped_cli_flags_present`. They do **not** enter the plan or the
approval digest. Named here so they are not a silent coverage hole.
Not mapped yet.

| Flag | Kind | Why it is not in the plan |
|------|------|---------------------------|
| `--update-env-vars` | execution-relevant | Env-var mutations at deploy. No load-bearing field today. |
| `--agent-identity` | execution-relevant | Agent identity. No load-bearing field today. |
| `--port` | execution-relevant | Container/service port. No load-bearing field today. |
| `--build-args` | execution-relevant | Source-build arguments. No load-bearing field today. |
| `--cluster-name` | execution-relevant | GKE cluster. No load-bearing field today. |
| `--no-wait` | control-flow | Does not change the deployed artifact. |
| `--dry-run` / `--list` / `--status` / `--interactive` / `--no-confirm-project` | control-flow | Not a deploy of a new artifact (or, for `--no-confirm-project`, only skips the GCP-project prompt). |

Print the same tables from the resolver:

```bash
python3 scripts/resolve_agents_cli_plan.py --mapping-table
```

### What the adapter will not pretend to do

- Call `gcloud` / ADC for project resolution (only `--project` and
  `GOOGLE_CLOUD_PROJECT`)
- Read live Cloud Run / Agent Runtime state on update (unset sizing flags
  preserve live values there; `defaults_mode=create` is the first-deploy
  shape)
- Read Terraform state for GKE names or sizing

```bash
python3 scripts/resolve_agents_cli_plan.py --demo
```

## Scope

This package implements deployment approval and plan-binding: resolve a
plan, block for a human decision, refuse to deploy unless signed evidence
verifies against that plan. It does not yet implement the full original
readiness proposal (eval-threshold enforcement, IAM role validation,
secrets-policy enforcement, Python build compatibility, rollback
executability, observability verification, post-deploy health validation,
runtime trace emission) — those are separate, larger gates layered on top
of this one, not yet built. Call this `agents-cli deployment approval and
plan-binding AISP skill`, not the complete deployment-readiness lifecycle,
per optimization2026's naming correction.

## AISP contract (verbatim from the 2026-08-13 review)

`aisp.aisop.json` carries optimization2026's exact function steps and two
non-negotiable rules, the second updated 2026-08-15 to resolve the
control-flow ambiguity his packaging review flagged (a failing `sys.assert`
inside `verify_approval.step2` could short-circuit before the graph's own
`verified{Evidence valid?}` routing node was reached):

```json
{
  "rule": "Do not deploy without an explicit human decision on the resolved deployment plan.",
  "enforced_by": "human_approval.step2:sys.io.confirm"
}
```

```json
{
  "rule": "When the human decision is approve, deployment must not proceed unless the attached approval evidence validates against the current effective deployment plan.",
  "enforced_by": "verified{Evidence valid?}:no->blocked, and redundantly by deploy.step1:sys.assert immediately before the irreversible action"
}
```

`human_approval.step2` is his exact `sys.io.confirm(..., options=['approve', 'reject', 'modify'])` line.
`verify_approval.step2` now just returns the structured verification result
(no assert) — `verified{}` and `deploy.step1`'s own `sys.assert` are the
sole gates on invalid evidence, matching his "Pattern A" recommendation.

The surrounding `[system, user]` envelope matches a real AISP skill
(`user.content.aisp_contract.profile = aisp.skill.v1`) so a SoulBot-class
runtime can load it. This package has not been executed on SoulBot.

## Identity

Authenticating `approver` against an IdP is optional higher-assurance
policy, not an AISP core primitive — same scoping as the review. The
envelope's `approver` field is a signed claim, not a verified identity.
