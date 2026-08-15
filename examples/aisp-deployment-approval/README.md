# AISP deployment-approval evidence profile — worked example

Answers [google/agents-cli#48](https://github.com/google/agents-cli/issues/48)'s request for a
real, cross-recomputable example of a skill-specific structured human-approval-response profile
riding inside `sys.io.confirm`.

Run it directly:

```bash
pip install coincurve
python3 deployment_approval_example.py
```

Write fixed, deterministic cross-language test vectors (same key/timestamps/nonce every run):

```bash
python3 deployment_approval_example.py --fixtures ./vectors
```

## v2 (2026-08-13) — the concrete next-improvements list from the thread

optimization2026 reviewed v1 and gave a detailed, numbered list of concrete next steps. The ones
that are self-contained (don't require `agents-cli`'s own internals or a real `sys.io.confirm`
host) are implemented here, each real and executed, not just described:

- **`approved_scope` verified independently** — `verify_approval()` now checks
  `approved_scope_matches_current_plan` and `approved_scope_digest_matches` separately from
  `plan_digest_matches`, closing the gap where a signer could display one `approved_scope` while
  a digest secretly covers a different plan. Demonstrated with a dedicated
  **SCOPE-FORGERY TEST** — editing `approved_scope` after signing breaks the signature itself
  (`signature_valid: false`), since scope is now inside the signed payload, not just the plan
  digest.
- **`key_id` separated from the public key** — `key_id` is an opaque registry label
  (`"release-key-2026-01"`); `public_key` carries the actual x-only hex the verifier needs. A real
  deployment can resolve `public_key` from a published registry by `key_id` instead of trusting
  the envelope's own copy.
- **Signed `approval_conditions` split from unsigned `display_note`** — "deploy only during the
  maintenance window" is load-bearing and now enters the signature; a spelling fix in a note does
  not.
- **Domain separation / replay protection** — `profile`, `skill_id`, `operation`, `plan_schema`,
  `audience`, `issued_at`, `nonce`, `max_uses` are all inside the signed payload, so an approval
  minted for this skill/operation can't be replayed against another. A **REPLAY TEST** shows the
  same nonce failing verification on its second use (`not_replayed: false`) via a demo
  `ReplayGuard` — explicitly documented as in-memory/per-process, not a claim that this alone
  solves production replay protection (that needs durable, shared storage).
- **Required-field fail-closed validation** — `validate_plan_completeness()` refuses to build an
  approval at all if a required production field (e.g. `rollback_plan`) is missing, rather than
  silently digesting it as `null`.
- **Canonicalization** — still deliberately **not** a full RFC 8785 implementation (that's a real
  dependency decision, not something to pull into a demo script casually). Instead this is
  optimization2026's own named fallback: a documented, enforced **JCS-safe restricted subset**
  (`str`/`int`/`dict[str,_]`/`list`/`None` only — no `float`, no `bool`-as-`bool`). A
  **JCS-SAFE ENFORCEMENT TEST** shows a `float` in a load-bearing field getting rejected outright
  rather than silently mis-serialized.
- **Fixed cross-language test vectors** (`--fixtures`) — a fixed, publicly-labeled TEST-ONLY
  private key, fixed timestamps, fixed nonce. **Real bug caught building this**: BIP-340 Schnorr
  signing mixes in 32 bytes of auxiliary randomness by default, so signing the identical message
  twice with the identical key produces two different (both valid) signatures — the first attempt
  at `--fixtures` silently produced a non-reproducible signature every run, which would have made
  the "byte-for-byte reproducible" claim false. Fixed by passing an explicit fixed
  `aux_randomness=b"\x00"*32` in the fixtures path only (the interactive demo keeps real
  randomness, which is what a real deployment wants). Verified: ran `--fixtures` twice into
  separate directories, `diff -r` reports identical output including the signature bytes.

Deliberately **not** attempted **in v2**, because they need optimization2026's own side to be real: (1)
wiring through an actual `sys.io.confirm` human-response channel, (2) resolving the plan from real
`agents-cli` state instead of a hardcoded dict, (8) authenticating the `approver` identity against
a real IdP. Named here rather than silently implied as covered.

## v3 integration prototype (2026-08-13) — still in this directory, still not agents-cli itself

The two items that were honestly open after v2 now have a runnable prototype next to this
example, not a PR against `google/agents-cli`:

- `resolve_agents_cli_plan.py` — merges real `cmd_deploy.py` flags + a loaded
  `agents-cli-manifest.yaml` into an effective plan. CLI flags override manifest values.
  Fields with no first-class agents-cli source (`rollback_plan`, `eval_evidence`,
  `python_version`, `environment`, `observability_requirements`) stay absent.
  Unmapped-but-real flags (`--update-env-vars`, `--agent-identity`, `--port`,
  `--build-args`, `--cluster-name`, `--no-wait`, …) are named in the mapping
  table, not silently dropped.
- `google_agents_cli_deploy_readiness_aisp/` — candidate AISP skill package
  (`aisp.aisop.json`, `SKILL.md`, `scripts/approval_verifier.py`, `schemas/`,
  `evals/vectors/` — real copies). `sys.io.confirm` /
  `sys.assert` steps and the `aisp_contract.non_negotiable` rules are
  optimization2026's exact text from the issue thread. Deploy-time
  `deploy-check` re-resolves live flags/manifest and refuses if any
  execution-relevant field has drifted from the approved plan.

```bash
python3 resolve_agents_cli_plan.py --demo
python3 google_agents_cli_deploy_readiness_aisp/scripts/approval_verifier.py --demo
```

(1) remains a wiring problem on the SoulBot Runtime, not a missing primitive.
(8) identity authentication remains optional policy, not built here.

## What v1 demonstrated (still true, extended not replaced)

1. **`compute_plan_digest()`** — a resolved deployment plan's load-bearing fields (deployment
   target, region, service, revision, etc.) get JCS-canonicalized and sha256'd. Presentational
   fields never enter the digest.
2. **`build_approval_response()`** — a human-approval envelope matching the shape from the issue
   thread, signed with a real BIP-340 schnorr signature (same primitive as Nostr/Bitcoin Taproot —
   `pip install coincurve`, no custom crypto).
3. **`verify_approval()`** — deterministic re-verification, returns a structured per-check result,
   never a bare boolean.
4. **A tamper test that must fail** — changes one load-bearing field (`region`) after signing and
   confirms verification correctly rejects it, naming the exact reason. A verifier with no failing
   case is a stamp, not a check.
5. **A presentational-only edit that must NOT invalidate approval** — editing the unsigned note
   after signing still verifies clean, since it was never part of the signed digest.
