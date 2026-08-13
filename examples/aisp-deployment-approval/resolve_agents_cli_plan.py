#!/usr/bin/env python3
"""Resolve an effective agents-cli deployment plan from REAL CLI + manifest state.

This is the adapter optimization2026 named as the largest remaining integration
item on google/agents-cli#48 (2026-08-13): the human must approve the values
`agents-cli deploy` will actually execute after resolving CLI flags, the
checked-in `agents-cli-manifest.yaml`, and the CLI's own documented defaults —
not a hardcoded example dict and not an LLM paraphrase of the command string.

Verified against a fresh clone of https://github.com/google/agents-cli
(`src/google/agents/cli/deploy/cmd_deploy.py` and
`src/google/agents/cli/scaffold/base_templates/_shared/agents-cli-manifest.yaml`)
on 2026-08-13. This module does NOT live in agents-cli and is not wired into
it — we have no write access there. It is a standalone, runnable prototype
an AISOP flow can call.

Precedence (explicit, not implicit)
-----------------------------------
A CLI flag is an explicit human override of a checked-in default. Where the
same field has both a `cmd_deploy.py` flag and a manifest key, the flag wins.
That is what agents-cli itself does: `_load_deploy_config` assigns
`cfg.deployment_target = deployment_target` when the flag is set
(`cmd_deploy.py` ~156-157: "explicit flag overrides the manifest"), and
`region = region or cfg.region` (`cmd_deploy.py` ~493). Same rule for
`--service-name` vs manifest `name` (`resolve_service_name` in
`deploy/_utils.py`).

Honesty about gaps
------------------
`LOAD_BEARING_FIELDS` in `deployment_approval_example.py` is the approval
profile's schema, not agents-cli's schema. Several of those fields have NO
first-class source in agents-cli today. This resolver does not invent one.
Unmapped fields are omitted from `plan` (absence, not a fabricated null-with-
a-fake-source), matching this repo's `pq_companion_status` discipline:
not-applicable is absence.

What this will NOT do
---------------------
- Call `gcloud` / ADC to resolve `--project` when the flag is absent. That
  live lookup is real in agents-cli (`resolve_gcp_project`) but is not
  reproducible in a standalone adapter. The documented `GOOGLE_CLOUD_PROJECT`
  env fallback IS applied, because it is a real, checkable source in
  `src/google/agents/cli/_gcp_project.py`. ADC / `gcloud config` are not.
- Read `pyproject.toml [project].version` into `source_revision` or
  `python_version`. `get_project_version()` is the package version injected
  as `AGENT_VERSION`, not a git SHA and not a Python interpreter version.
- Map `language: python` or scaffold `requires-python = ">=3.11,<3.14"` to
  `python_version`. Those are a language family and a range, not a pin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any


# Same tuple as deployment_approval_example.LOAD_BEARING_FIELDS — kept as a
# local copy so this module stays importable without coincurve. Do not drift.
LOAD_BEARING_FIELDS = (
    "deployment_target",
    "environment",
    "gcp_project",
    "region",
    "service_name",
    "source_revision",
    "python_version",
    "service_account",
    "network_exposure",
    "secret_policy_digest",
    "resource_sizing",
    "eval_evidence",
    "rollback_plan",
    "observability_requirements",
)

# Documented create-time defaults from deploy/_utils.py. On Cloud Run *update*
# and Agent Runtime *update*, unset sizing flags are omitted so the live
# service is preserved — `defaults_mode="create"` is therefore "what a first
# deploy would execute", not "what every deploy would execute".
DEFAULT_CPU = "1"
DEFAULT_MEMORY = "4Gi"
DEFAULT_MIN_INSTANCES = 1
DEFAULT_MAX_INSTANCES = 10
DEFAULT_CONCURRENCY = 8
DEFAULT_REGION = "us-east1"  # ProjectConfig.region and the manifest template
DEFAULT_SERVICE_NAME = "agent"  # resolve_service_name fallback, no manifest
VALID_TARGETS = ("agent_runtime", "cloud_run", "gke")

# Click dest names (and hyphenated CLI spellings) from cmd_deploy.py ~278-434.
# Values we do not map onto LOAD_BEARING_FIELDS are still recognized so they
# can be reported as "real flag, no load-bearing home" rather than ignored.
_FLAG_ALIASES: dict[str, str] = {
    "project": "project",
    "--project": "project",
    "region": "region",
    "--region": "region",
    "deployment_target": "deployment_target",
    "--deployment-target": "deployment_target",
    "-d": "deployment_target",
    "secrets": "secrets",
    "--secrets": "secrets",
    "agent_identity": "agent_identity",
    "--agent-identity": "agent_identity",
    "update_env_vars": "update_env_vars",
    "--update-env-vars": "update_env_vars",
    "iap": "iap",
    "--iap": "iap",
    "port": "port",
    "--port": "port",
    "memory": "memory",
    "--memory": "memory",
    "cpu": "cpu",
    "--cpu": "cpu",
    "min_instances": "min_instances",
    "--min-instances": "min_instances",
    "max_instances": "max_instances",
    "--max-instances": "max_instances",
    "concurrency": "concurrency",
    "--concurrency": "concurrency",
    "service_account": "service_account",
    "--service-account": "service_account",
    "service_name": "service_name",
    "service_name_override": "service_name",
    "--service-name": "service_name",
    "image": "image",
    "--image": "image",
    "build_args": "build_args",
    "--build-args": "build_args",
    "cluster_name": "cluster_name",
    "--cluster-name": "cluster_name",
    "dry_run": "dry_run",
    "--dry-run": "dry_run",
    "-n": "dry_run",
    "list_deployments": "list_deployments",
    "--list": "list_deployments",
    "no_wait": "no_wait",
    "--no-wait": "no_wait",
    "status": "status",
    "--status": "status",
    "interactive": "interactive",
    "--interactive": "interactive",
    "-i": "interactive",
    "no_confirm_project": "no_confirm_project",
    "--no-confirm-project": "no_confirm_project",
    "network_attachment": "network_attachment",
    "--network-attachment": "network_attachment",
    "dns_peering_domain": "dns_peering_domain",
    "--dns-peering-domain": "dns_peering_domain",
    "dns_peering_project": "dns_peering_project",
    "--dns-peering-project": "dns_peering_project",
    "dns_peering_network": "dns_peering_network",
    "--dns-peering-network": "dns_peering_network",
}

# Flags that exist on `agents-cli deploy` but have no LOAD_BEARING_FIELDS home.
# Listed so a caller can see we read them and chose not to invent a mapping.
UNMAPPED_CLI_FLAGS = (
    "agent_identity",
    "update_env_vars",
    "port",
    "build_args",
    "cluster_name",
    "dry_run",
    "list_deployments",
    "no_wait",
    "status",
    "interactive",
    "no_confirm_project",
)

# Static field-by-field mapping. `status` is one of:
#   mapped   — a real 1:1 (or documented-merge) source exists
#   partial  — a real source covers only part of the field's meaning
#   absent   — no first-class agents-cli source; do not invent one
FIELD_MAPPING: tuple[dict[str, str], ...] = (
    {
        "field": "deployment_target",
        "status": "mapped",
        "cli": "--deployment-target / -d  (click.Choice: agent_runtime|cloud_run|gke)",
        "manifest": "create_params.deployment_target",
        "notes": "CLI overrides manifest. cmd_deploy.py ~156-157.",
    },
    {
        "field": "environment",
        "status": "absent",
        "cli": "",
        "manifest": "",
        "notes": "No --environment on deploy. staging/prod exist only as "
                 "infra/CI-CD Terraform projects (cmd_cicd.py), not as a "
                 "deploy-time plan field.",
    },
    {
        "field": "gcp_project",
        "status": "mapped",
        "cli": "--project",
        "manifest": "",
        "notes": "No manifest key. agents-cli then falls back to "
                 "GOOGLE_CLOUD_PROJECT, then ADC/gcloud. This adapter applies "
                 "the flag and the env var only — it does not call gcloud.",
    },
    {
        "field": "region",
        "status": "mapped",
        "cli": "--region",
        "manifest": "region  (template default: us-east1)",
        "notes": "CLI overrides manifest. ProjectConfig.region default is "
                 "us-east1 when neither is set (cmd_deploy.py ~493).",
    },
    {
        "field": "service_name",
        "status": "mapped",
        "cli": "--service-name",
        "manifest": "name",
        "notes": "resolve_service_name: override or cfg.project_name or "
                 "'agent'. --service-name is rejected for GKE "
                 "(cmd_deploy.py ~174-181).",
    },
    {
        "field": "source_revision",
        "status": "partial",
        "cli": "--image  (container image URI; Cloud Run / GKE only)",
        "manifest": "",
        "notes": "agents-cli has no git-SHA / source-revision flag. When "
                 "--image is set it skips the source build and that URI is "
                 "the closest real 'what will run' identifier. From-source "
                 "deploys (`gcloud run deploy --source .`) capture no "
                 "revision. pyproject [project].version is AGENT_VERSION, "
                 "not a source revision — not mapped here.",
    },
    {
        "field": "python_version",
        "status": "absent",
        "cli": "",
        "manifest": "language  (python|go|java|typescript — a family, not a version)",
        "notes": "No --python-version. Scaffold pyproject has requires-python "
                 "'>=3.11,<3.14' (a range, not a pin). Mapping either to "
                 "python_version would fabricate a specific interpreter.",
    },
    {
        "field": "service_account",
        "status": "mapped",
        "cli": "--service-account",
        "manifest": "",
        "notes": "No manifest key. Unset means the platform default SA, which "
                 "this adapter cannot resolve without live GCP.",
    },
    {
        "field": "network_exposure",
        "status": "mapped",
        "cli": "--iap; --network-attachment; --dns-peering-domain/"
               "project/network; Cloud Run always passes --no-allow-unauthenticated",
        "manifest": "",
        "notes": "Not a single first-class field. Assembled as a JCS-safe "
                 "string-valued dict from the flags agents-cli actually "
                 "sends. Bools are stored as 'enabled'/'disabled' strings "
                 "because the approval digest forbids JSON bools.",
    },
    {
        "field": "secret_policy_digest",
        "status": "mapped",
        "cli": "--secrets  (ENV=SECRET or ENV=SECRET:VERSION)",
        "manifest": "",
        "notes": "sha256 of the JCS-safe-canonicalized {ENV: {secret, version}} "
                 "map. Digests secret *identifiers*, never secret values. "
                 "GKE rejects --secrets (cmd_deploy.py ~553-558).",
    },
    {
        "field": "resource_sizing",
        "status": "mapped",
        "cli": "--cpu --memory --min-instances --max-instances --concurrency",
        "manifest": "",
        "notes": "Create defaults from deploy/_utils.py: cpu=1, memory=4Gi, "
                 "min=1, max=10, concurrency=8. On update, unset flags are "
                 "omitted (live values preserved). GKE rejects these flags "
                 "(cmd_deploy.py ~576-590) — Terraform owns GKE sizing, so "
                 "this field stays absent for target=gke.",
    },
    {
        "field": "eval_evidence",
        "status": "absent",
        "cli": "",
        "manifest": "",
        "notes": "Not a deploy concept. Evaluation is a separate command "
                 "family (`agents-cli eval generate|grade|compare|...`). "
                 "deploy never reads artifacts/grade_results/.",
    },
    {
        "field": "rollback_plan",
        "status": "absent",
        "cli": "",
        "manifest": "",
        "notes": "No --rollback, no manifest key, no `agents-cli rollback`. "
                 "The deploy skill documents git-revert / gcloud traffic "
                 "shift / kubectl rollout undo as prose recovery, not as a "
                 "structured plan field. There is no `agents-cli rollback "
                 "--to` (the v2 example's rollback_plan string is illustrative).",
    },
    {
        "field": "observability_requirements",
        "status": "absent",
        "cli": "",
        "manifest": "",
        "notes": "Owned by the separate observability skill and "
                 "`agents-cli infra single-project`. deploy injects "
                 "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false as a default "
                 "env var — that is not a first-class observability plan.",
    },
)

ABSENT_FIELDS: tuple[str, ...] = tuple(
    row["field"] for row in FIELD_MAPPING if row["status"] == "absent"
)


def mapping_table() -> tuple[dict[str, str], ...]:
    """The field-by-field mapping, for docs and `--mapping-table`."""
    return FIELD_MAPPING


@dataclass
class ResolveResult:
    """Effective plan plus an honest coverage record.

    `plan` contains only fields that have a real source in this resolution.
    Unmapped LOAD_BEARING_FIELDS are listed in `absent_fields` and are NOT
    inserted as null. Extra keys (`_resolver` is never added to `plan`) stay
    off the digest surface — `compute_plan_digest` only reads LOAD_BEARING_FIELDS.
    """

    plan: dict[str, Any]
    coverage: dict[str, dict[str, Any]]
    absent_fields: list[str]
    unmapped_cli_flags_present: list[str]
    warnings: list[str] = field(default_factory=list)
    defaults_mode: str = "create"
    precedence: str = (
        "CLI flags override manifest values where both exist for the same field "
        "(a flag is an explicit human override of a checked-in default)."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "coverage": self.coverage,
            "absent_fields": self.absent_fields,
            "unmapped_cli_flags_present": self.unmapped_cli_flags_present,
            "warnings": self.warnings,
            "defaults_mode": self.defaults_mode,
            "precedence": self.precedence,
        }


def normalize_cli_flags(cli_flags: dict[str, Any] | None) -> dict[str, Any]:
    """Accept click dest names or hyphenated `--flag` spellings."""
    if not cli_flags:
        return {}
    out: dict[str, Any] = {}
    unknown: list[str] = []
    for raw_key, value in cli_flags.items():
        key = str(raw_key).strip()
        dest = _FLAG_ALIASES.get(key) or _FLAG_ALIASES.get(key.replace("_", "-"))
        if dest is None:
            # Allow already-normalized dest names that we simply don't alias twice
            dest = key if key in {v for v in _FLAG_ALIASES.values()} else None
        if dest is None:
            unknown.append(key)
            continue
        if dest in out and out[dest] != value:
            raise ValueError(
                f"conflicting values for CLI dest {dest!r}: {out[dest]!r} vs {value!r}"
            )
        out[dest] = value
    if unknown:
        raise ValueError(
            f"unrecognized CLI flag name(s) {unknown} — expected cmd_deploy.py "
            f"option dests or spellings such as --project / --deployment-target"
        )
    return out


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _manifest_create_params(manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not manifest:
        return {}
    params = manifest.get("create_params") or {}
    return params if isinstance(params, dict) else {}


def _parse_secrets(secrets_string: str) -> dict[str, dict[str, str]]:
    """Mirror agent_runtime.parse_secrets: ENV=SECRET or ENV=SECRET:VERSION."""
    result: dict[str, dict[str, str]] = {}
    for pair in secrets_string.split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            raise ValueError(f"malformed --secrets pair {pair!r} (expected ENV=SECRET[:VERSION])")
        env, spec = pair.split("=", 1)
        env, spec = env.strip(), spec.strip()
        if ":" not in spec:
            secret_id, version = spec, "latest"
        else:
            secret_id, _, version = spec.rpartition(":")
        result[env] = {"secret": secret_id, "version": version}
    return result


def _secret_policy_digest(secrets_string: str) -> str:
    parsed = _parse_secrets(secrets_string)
    # Restricted JCS-safe subset (str keys, str values) — same serialization
    # contract as deployment_approval_example._canon, implemented locally so
    # this module does not import coincurve.
    canon = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _set_mapped(
    coverage: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    name: str,
    value: Any,
    source: str,
    notes: str = "",
) -> None:
    plan[name] = value
    coverage[name] = {"status": "mapped", "source": source, "notes": notes}


def _mark_absent(
    coverage: dict[str, dict[str, Any]],
    name: str,
    notes: str,
) -> None:
    coverage[name] = {"status": "absent", "source": None, "notes": notes}


def _mark_partial(
    coverage: dict[str, dict[str, Any]],
    plan: dict[str, Any],
    name: str,
    value: Any,
    source: str,
    notes: str,
) -> None:
    plan[name] = value
    coverage[name] = {"status": "partial", "source": source, "notes": notes}


def resolve_agents_cli_plan(
    cli_flags: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    *,
    defaults_mode: str = "create",
    environ: dict[str, str] | None = None,
) -> ResolveResult:
    """Merge parsed `agents-cli deploy` flags + a loaded manifest into a plan.

    Args:
        cli_flags: click dest names (`project`, `deployment_target`, ...) or
            hyphenated spellings (`--project`, `--deployment-target`). A
            missing / null / empty value means "flag not passed".
        manifest: dict loaded from `agents-cli-manifest.yaml` (the real
            schema: `name`, `acli_version`, `agent_directory`, `region`,
            `base_template`, `generated_at`, `language`, `create_params`).
            Pass None / {} for a flags-only (no-manifest) deploy — agents-cli
            allows that when `--deployment-target` is set.
        defaults_mode: `"create"` applies the documented first-deploy defaults
            (region=us-east1, service_name='agent', Cloud Run / Agent Runtime
            sizing). `"explicit_only"` emits only values that were actually
            passed as a flag or present in the manifest. Neither mode invents
            sources for ABSENT_FIELDS.
        environ: optional env mapping; defaults to `os.environ`. Used only
            for the documented `GOOGLE_CLOUD_PROJECT` fallback.

    Returns:
        ResolveResult. `plan` omits unmapped fields.

    Raises:
        ValueError: on combinations agents-cli itself rejects (GKE +
            --service-name, GKE + sizing flags, Agent Runtime + --image,
            GKE + --secrets, incomplete DNS peering, unknown flags).
    """
    if defaults_mode not in ("create", "explicit_only"):
        raise ValueError("defaults_mode must be 'create' or 'explicit_only'")

    flags = normalize_cli_flags(cli_flags)
    manifest = manifest or {}
    create_params = _manifest_create_params(manifest)
    env = environ if environ is not None else os.environ

    plan: dict[str, Any] = {}
    coverage: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    # --- deployment_target ------------------------------------------------
    if _present(flags.get("deployment_target")):
        target = flags["deployment_target"]
        _set_mapped(
            coverage, plan, "deployment_target", target,
            "cli:--deployment-target",
            "CLI flag overrides create_params.deployment_target.",
        )
    elif _present(create_params.get("deployment_target")):
        target = create_params["deployment_target"]
        _set_mapped(
            coverage, plan, "deployment_target", target,
            "manifest:create_params.deployment_target",
        )
    else:
        target = None
        _mark_absent(
            coverage, "deployment_target",
            "Neither --deployment-target nor create_params.deployment_target "
            "is set. agents-cli would fail require_deployment_target().",
        )
    if target is not None and target not in VALID_TARGETS:
        raise ValueError(
            f"deployment_target {target!r} is not one of {VALID_TARGETS} "
            f"(cmd_deploy.py click.Choice)"
        )

    # Combinations the real CLI rejects — fail here too, don't silently map.
    if target == "gke" and _present(flags.get("service_name")):
        raise ValueError(
            "--service-name is not supported for GKE deployments "
            "(cmd_deploy.py ~174-181). GKE names are Terraform-owned."
        )
    if target == "agent_runtime" and _present(flags.get("image")):
        raise ValueError(
            "--image is not supported for Agent Runtime deployments "
            "(cmd_deploy.py ~567-571). Agent Runtime builds from the project Dockerfile."
        )
    if target == "gke" and _present(flags.get("secrets")):
        raise ValueError(
            "--secrets is only supported for Agent Runtime and Cloud Run "
            "(cmd_deploy.py ~553-558)."
        )
    if target == "gke":
        gke_sizing = {
            "--cpu": flags.get("cpu"),
            "--memory": flags.get("memory"),
            "--min-instances": flags.get("min_instances"),
            "--max-instances": flags.get("max_instances"),
            "--concurrency": flags.get("concurrency"),
        }
        misused = [name for name, value in gke_sizing.items() if _present(value)]
        if misused:
            raise ValueError(
                f"{', '.join(misused)} not supported for GKE deployments "
                f"(cmd_deploy.py ~576-590). Size via Terraform / HPA."
            )

    # --- environment : no source -----------------------------------------
    _mark_absent(
        coverage, "environment",
        "No --environment flag and no manifest key. CI/CD staging/prod are "
        "infra project IDs, not a deploy-time plan field.",
    )

    # --- gcp_project ------------------------------------------------------
    if _present(flags.get("project")):
        _set_mapped(
            coverage, plan, "gcp_project", flags["project"],
            "cli:--project",
        )
    elif _present(env.get("GOOGLE_CLOUD_PROJECT")):
        _set_mapped(
            coverage, plan, "gcp_project", env["GOOGLE_CLOUD_PROJECT"],
            "env:GOOGLE_CLOUD_PROJECT",
            "Documented fallback in resolve_gcp_project() after --project. "
            "ADC / gcloud config are NOT applied by this adapter.",
        )
    else:
        _mark_absent(
            coverage, "gcp_project",
            "No --project and no GOOGLE_CLOUD_PROJECT. agents-cli would next "
            "ask ADC / `gcloud config get-value project` — this adapter does not.",
        )

    # --- region -----------------------------------------------------------
    if _present(flags.get("region")):
        _set_mapped(
            coverage, plan, "region", flags["region"],
            "cli:--region",
            "CLI flag overrides manifest region.",
        )
    elif _present(manifest.get("region")):
        _set_mapped(
            coverage, plan, "region", manifest["region"],
            "manifest:region",
        )
    elif defaults_mode == "create":
        _set_mapped(
            coverage, plan, "region", DEFAULT_REGION,
            "agents-cli-default:region=us-east1",
            "ProjectConfig.region and the scaffold manifest template default. "
            "Applied only in defaults_mode='create'.",
        )
    else:
        _mark_absent(
            coverage, "region",
            "No --region, no manifest region, defaults_mode='explicit_only'.",
        )

    # --- service_name -----------------------------------------------------
    if _present(flags.get("service_name")):
        _set_mapped(
            coverage, plan, "service_name", flags["service_name"],
            "cli:--service-name",
            "CLI flag overrides manifest name.",
        )
    elif _present(manifest.get("name")):
        _set_mapped(
            coverage, plan, "service_name", manifest["name"],
            "manifest:name",
        )
    elif defaults_mode == "create":
        _set_mapped(
            coverage, plan, "service_name", DEFAULT_SERVICE_NAME,
            "agents-cli-default:service_name=agent",
            "resolve_service_name fallback when deploying without a manifest.",
        )
    else:
        _mark_absent(
            coverage, "service_name",
            "No --service-name, no manifest name, defaults_mode='explicit_only'.",
        )

    # --- source_revision : --image only, and only partially --------------
    if _present(flags.get("image")):
        _mark_partial(
            coverage, plan, "source_revision", flags["image"],
            "cli:--image",
            "Image URI, not a git SHA. agents-cli has no source-revision flag. "
            "From-source deploys capture no revision.",
        )
    else:
        _mark_absent(
            coverage, "source_revision",
            "No --image. A from-source deploy (`--source .`) has no first-class "
            "revision in agents-cli. Not mapping AGENT_VERSION / git HEAD.",
        )

    # --- python_version : no source --------------------------------------
    lang = manifest.get("language")
    extra = f" Manifest language={lang!r} is a family, not a version." if lang else ""
    _mark_absent(
        coverage, "python_version",
        "No --python-version and no pinned interpreter in the deploy path." + extra,
    )

    # --- service_account --------------------------------------------------
    if _present(flags.get("service_account")):
        _set_mapped(
            coverage, plan, "service_account", flags["service_account"],
            "cli:--service-account",
        )
    else:
        _mark_absent(
            coverage, "service_account",
            "No --service-account. agents-cli leaves this unset and the "
            "platform default SA is used — not resolvable without live GCP.",
        )

    # --- network_exposure -------------------------------------------------
    network: dict[str, Any] = {}
    net_sources: list[str] = []
    if target == "cloud_run":
        # cmd_deploy.py ~684: args.append("--no-allow-unauthenticated")
        network["ingress"] = "authenticated"
        net_sources.append("cli-hardcoded:--no-allow-unauthenticated")
    if flags.get("iap"):
        if target not in (None, "cloud_run"):
            warnings.append(
                "--iap is documented as Cloud Run only; included because the "
                "flag was explicitly passed."
            )
        network["iap"] = "enabled"
        net_sources.append("cli:--iap")
    if _present(flags.get("network_attachment")):
        if target not in (None, "agent_runtime"):
            raise ValueError(
                "--network-attachment and --dns-peering-* are only supported "
                "for Agent Runtime (cmd_deploy.py ~547-551)."
            )
        network["network_attachment"] = flags["network_attachment"]
        net_sources.append("cli:--network-attachment")
        dns_flags = {
            "dns_peering_domain": flags.get("dns_peering_domain"),
            "dns_peering_project": flags.get("dns_peering_project"),
            "dns_peering_network": flags.get("dns_peering_network"),
        }
        present_dns = {k: v for k, v in dns_flags.items() if _present(v)}
        if present_dns and len(present_dns) != 3:
            missing = [k for k, v in dns_flags.items() if not _present(v)]
            raise ValueError(
                f"Incomplete DNS peering configuration — missing {missing} "
                f"(cmd_deploy.py ~107-119). All three flags must be provided together."
            )
        if present_dns:
            network["dns_peering_domain"] = flags["dns_peering_domain"]
            network["dns_peering_project"] = flags["dns_peering_project"]
            network["dns_peering_network"] = flags["dns_peering_network"]
            net_sources.append("cli:--dns-peering-*")
    elif any(
        _present(flags.get(k))
        for k in ("dns_peering_domain", "dns_peering_project", "dns_peering_network")
    ):
        raise ValueError(
            "--dns-peering-* require --network-attachment (cmd_deploy.py ~97-102)."
        )

    if network:
        _set_mapped(
            coverage, plan, "network_exposure", network,
            "+".join(net_sources),
            "Assembled from real deploy flags / hardcoded Cloud Run ingress. "
            "String values only (JCS-safe subset; no JSON bools).",
        )
    else:
        _mark_absent(
            coverage, "network_exposure",
            "No networking flags and target is not cloud_run (so the hardcoded "
            "--no-allow-unauthenticated does not apply).",
        )

    # --- secret_policy_digest --------------------------------------------
    if _present(flags.get("secrets")):
        digest = _secret_policy_digest(str(flags["secrets"]))
        _set_mapped(
            coverage, plan, "secret_policy_digest", digest,
            "cli:--secrets",
            "sha256 of JCS-canon({ENV: {secret, version}}). Identifiers only.",
        )
    else:
        _mark_absent(
            coverage, "secret_policy_digest",
            "No --secrets. An empty secret map is not a policy — omitted.",
        )

    # --- resource_sizing -------------------------------------------------
    if target == "gke":
        _mark_absent(
            coverage, "resource_sizing",
            "GKE sizing is Terraform / HPA owned. Deploy flags are rejected. "
            "Not fabricating a Terraform-state read.",
        )
    else:
        sizing: dict[str, Any] = {}
        sizing_sources: list[str] = []
        explicit = {
            "cpu": flags.get("cpu"),
            "memory": flags.get("memory"),
            "min_instances": flags.get("min_instances"),
            "max_instances": flags.get("max_instances"),
            "concurrency": flags.get("concurrency"),
        }
        create_defaults = {
            "cpu": DEFAULT_CPU,
            "memory": DEFAULT_MEMORY,
            "min_instances": DEFAULT_MIN_INSTANCES,
            "max_instances": DEFAULT_MAX_INSTANCES,
            "concurrency": DEFAULT_CONCURRENCY,
        }
        for key, value in explicit.items():
            if _present(value):
                # Keep cpu/memory as strings (CLI type). Counts stay ints.
                sizing[key] = value
                sizing_sources.append(f"cli:--{key.replace('_', '-')}")
            elif defaults_mode == "create" and target in ("agent_runtime", "cloud_run"):
                sizing[key] = create_defaults[key]
                sizing_sources.append(f"agents-cli-default:{key}")
        if sizing:
            note = (
                "Create-time defaults applied for unset keys."
                if any(s.startswith("agents-cli-default:") for s in sizing_sources)
                else "Only explicitly passed sizing flags."
            )
            if defaults_mode == "create":
                note += (
                    " On Cloud Run / Agent Runtime *update*, unset flags are "
                    "omitted and live values are preserved — this is the "
                    "first-deploy shape, not a live-reconcile."
                )
            _set_mapped(
                coverage, plan, "resource_sizing", sizing,
                "+".join(sizing_sources) if sizing_sources else "agents-cli-default",
                note,
            )
        else:
            _mark_absent(
                coverage, "resource_sizing",
                "No sizing flags and defaults_mode='explicit_only' (or no target).",
            )

    # --- eval_evidence / rollback_plan / observability : no source -------
    _mark_absent(
        coverage, "eval_evidence",
        "Not a deploy concept. `agents-cli eval` is a separate command family "
        "and deploy does not consume its artifacts.",
    )
    _mark_absent(
        coverage, "rollback_plan",
        "No first-class rollback field. The deploy skill's Rollback & Recovery "
        "section is prose (git revert / gcloud traffic shift / kubectl undo).",
    )
    _mark_absent(
        coverage, "observability_requirements",
        "Owned by the observability skill / infra single-project, not deploy.",
    )

    absent_fields = [name for name in LOAD_BEARING_FIELDS if name not in plan]
    unmapped_present = [
        name for name in UNMAPPED_CLI_FLAGS if _present(flags.get(name))
    ]
    if unmapped_present:
        warnings.append(
            "Real deploy flags were passed that have no LOAD_BEARING_FIELDS "
            f"home and were left out of the plan: {unmapped_present}"
        )

    # Manifest keys that exist but do not map to the approval profile.
    leftover_manifest = [
        k for k in ("acli_version", "agent_directory", "base_template",
                    "generated_at", "language")
        if k in manifest
    ]
    leftover_create = [
        k for k in ("session_type", "cicd_runner", "is_a2a",
                    "agent_guidance_filename")
        if k in create_params
    ]
    if leftover_manifest or leftover_create:
        warnings.append(
            "Manifest keys read and not mapped onto LOAD_BEARING_FIELDS "
            f"(real schema, no approval-profile home): "
            f"top-level={leftover_manifest} create_params={leftover_create}"
        )

    return ResolveResult(
        plan=plan,
        coverage=coverage,
        absent_fields=absent_fields,
        unmapped_cli_flags_present=unmapped_present,
        warnings=warnings,
        defaults_mode=defaults_mode,
    )


def load_manifest(path: str) -> dict[str, Any]:
    """Load a YAML or JSON agents-cli-manifest.yaml."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith((".json",)):
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise SystemExit(
                "PyYAML is required to load a .yaml manifest. "
                "pip install pyyaml, or pass a JSON manifest."
            ) from exc
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse as a mapping")
    return data


def load_flags(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse as a JSON object")
    return data


def _print_mapping_table() -> None:
    print(f"{'field':<28} {'status':<8} cli / manifest")
    print("-" * 88)
    for row in FIELD_MAPPING:
        src = row["cli"] or "(none)"
        if row["manifest"]:
            src += "  |  " + row["manifest"]
        print(f"{row['field']:<28} {row['status']:<8} {src}")
        print(f"{'':28}          {row['notes']}")
        print()


def _demo() -> None:
    """Two realistic scenarios with real printed output, not asserted-only."""
    print("=== FIELD MAPPING (verified against google/agents-cli cmd_deploy.py + manifest template) ===\n")
    _print_mapping_table()

    print("=" * 88)
    print("SCENARIO 1 — CLI flags only (no manifest; --deployment-target required)")
    print("=" * 88)
    flags_only = {
        "--deployment-target": "cloud_run",
        "--project": "company-prod",
        "--region": "us-central1",
        "--service-name": "support-agent",
        "--service-account": "support-agent-sa@company-prod.iam.gserviceaccount.com",
        "--image": "us-central1-docker.pkg.dev/company-prod/support-agent/support-agent:abc123",
        "--cpu": "2",
        "--memory": "4Gi",
        "--max-instances": 10,
        "--secrets": "API_KEY=support-agent-api-key,DB_PASS=support-db:2",
        "--iap": True,
    }
    result1 = resolve_agents_cli_plan(flags_only, None, defaults_mode="create")
    print(json.dumps(result1.to_dict(), indent=2, sort_keys=True))

    print()
    print("=" * 88)
    print("SCENARIO 2 — manifest defaults + CLI overrides (flag wins)")
    print("=" * 88)
    manifest = {
        "name": "support-agent",
        "acli_version": "0.5.0",
        "agent_directory": "app",
        "region": "us-east1",
        "base_template": "adk",
        "generated_at": "2026-08-01T00:00:00Z",
        "language": "python",
        "create_params": {
            "deployment_target": "agent_runtime",
            "session_type": "none",
            "cicd_runner": "github_actions",
            "is_a2a": True,
            "agent_guidance_filename": "GEMINI.md",
        },
    }
    overrides = {
        "--deployment-target": "agent_runtime",  # same as manifest; explicit
        "--region": "us-central1",               # overrides manifest us-east1
        "--project": "company-prod",
        "--service-account": "support-agent-sa@company-prod.iam.gserviceaccount.com",
        "--service-name": "support-agent-canary",  # overrides manifest name
        "--network-attachment": (
            "projects/company-prod/regions/us-central1/networkAttachments/agent-psc"
        ),
        "--dns-peering-domain": "my-internal.corp.",
        "--dns-peering-project": "company-shared-vpc",
        "--dns-peering-network": "prod-vpc",
        "--cpu": "4",
        "--memory": "16Gi",
        "--concurrency": 16,
    }
    result2 = resolve_agents_cli_plan(overrides, manifest, defaults_mode="create")
    print(json.dumps(result2.to_dict(), indent=2, sort_keys=True))

    # Prove the override actually happened, with real values.
    assert result2.plan["region"] == "us-central1", result2.plan
    assert result2.coverage["region"]["source"] == "cli:--region"
    assert result2.plan["service_name"] == "support-agent-canary"
    assert result2.coverage["service_name"]["source"] == "cli:--service-name"
    assert result2.plan["deployment_target"] == "agent_runtime"
    assert "rollback_plan" not in result2.plan
    assert "eval_evidence" not in result2.plan
    assert "python_version" not in result2.plan
    assert "environment" not in result2.plan
    assert "observability_requirements" not in result2.plan
    assert "rollback_plan" in result2.absent_fields
    print()
    print("Override check: region us-east1 (manifest) -> us-central1 (flag). "
          "service_name support-agent (manifest) -> support-agent-canary (flag).")
    print(f"Honestly absent (no agents-cli source): {result2.absent_fields}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Resolve an effective agents-cli deployment plan from CLI flags + manifest."
    )
    ap.add_argument("--flags", help="JSON object of cmd_deploy.py-style flags")
    ap.add_argument("--manifest", help="Path to agents-cli-manifest.yaml (or .json)")
    ap.add_argument(
        "--defaults-mode",
        choices=("create", "explicit_only"),
        default="create",
        help="create: apply documented first-deploy defaults. "
             "explicit_only: only values actually passed or in the manifest.",
    )
    ap.add_argument("--mapping-table", action="store_true",
                    help="print the static field-mapping table and exit")
    ap.add_argument("--demo", action="store_true",
                    help="run two realistic scenarios and print real output")
    args = ap.parse_args()

    if args.mapping_table:
        _print_mapping_table()
        return
    if args.demo:
        _demo()
        return
    if not args.flags and not args.manifest:
        ap.error("pass --flags and/or --manifest, or --demo / --mapping-table")

    flags = load_flags(args.flags) if args.flags else {}
    manifest = load_manifest(args.manifest) if args.manifest else {}
    result = resolve_agents_cli_plan(
        flags, manifest, defaults_mode=args.defaults_mode
    )
    json.dump(result.to_dict(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
