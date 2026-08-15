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
│   ├── approval_verifier.py           # resolve + verify CLI, local imports only
│   ├── deployment_approval_example.py # v2 digest / BIP-340 / verify (local copy)
│   └── resolve_agents_cli_plan.py     # effective-plan adapter (local copy)
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
agents-cli deploy   (same flags that produced the plan)
```

`modify` returns to resolve. A previous approval must not carry over.
`reject` or a failed verify stops without deploy.

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
`source_revision` for a production approval. A plan resolved from
agents-cli state alone will therefore be **refused** until a human or
policy supplies those via `--supplements`. That is the point of
fail-closed, not a gap to paper over.

`--supplements` will error if you try to override a field the resolver
already mapped.

### What the adapter will not pretend to do

- Call `gcloud` / ADC for project resolution (only `--project` and
  `GOOGLE_CLOUD_PROJECT`)
- Read live Cloud Run / Agent Runtime state on update (unset sizing flags
  preserve live values there; `defaults_mode=create` is the first-deploy
  shape)
- Read Terraform state for GKE names or sizing

```bash
python3 scripts/resolve_agents_cli_plan.py --demo
python3 scripts/resolve_agents_cli_plan.py --mapping-table
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
