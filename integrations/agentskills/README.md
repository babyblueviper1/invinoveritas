# invinoveritas — Agent Skills (agentskills.io standard)

Portable [Agent Skills](https://agentskills.io) (the open `SKILL.md` standard,
Anthropic-originated), usable unmodified by **any** agentskills-compatible
client — **Hermes**, Claude Code, Cursor, Codex, Goose, Letta, nanobot, and dozens more.

Three skills, one idea — independent verification an agent can't self-serve:

- **`loop-verifier/`** — the independent gate for your **agent loop**. If you run
  unattended/scheduled agents (Claude Code `/loop`, hooks, Codex Automations, CI-triggered
  agents), this wires `review` as an objective exit-code gate before the loop's irreversible
  step (merge, deploy, trade, pay), with a portable signed proof attached to what ships.
- **`verification-handshake/`** — the agent-to-agent trust norm: **demand a proof on what
  you receive, attach a proof to what you ship.** `verify-proof` is free + no-auth.
- **`invinoveritas/`** — the full platform skill: when and how to reach for invinoveritas'
  paid MCP tools — above all **`review`** (capital-scale-aware governance) *before any
  irreversible action*, plus the facts-only markets group, sandboxed execution, wallet-keyed
  memory, and agent-to-agent payments — pay-per-call over Lightning, USDC (x402), or card.

## Install (Hermes example)
```bash
# Skills live in ~/.hermes/skills/ for Hermes; other clients use their own skills dir.
cp -r invinoveritas ~/.hermes/skills/invinoveritas        # or loop-verifier / verification-handshake
```
Then wire the MCP server (see `invinoveritas/references/REFERENCE.md` or
[../hermes/README.md](../hermes/README.md)) so the tools the skill describes are callable.
(`loop-verifier` and `verification-handshake` also work with zero MCP wiring — plain
`curl` against the REST API; `verify-proof` needs no auth at all.)

## Structure
- `loop-verifier/SKILL.md` — gate an autonomous loop's irreversible step on an independent verdict.
- `verification-handshake/SKILL.md` — demand a proof inbound, attach a proof outbound.
- `invinoveritas/SKILL.md` — metadata (`name`, `description`) + when/how-to-use instructions.
- `invinoveritas/references/REFERENCE.md` — full tool table, prices, payment rails, config variants (loaded on demand).

## Validate
```bash
# canonical validator (agentskills/agentskills):
skills-ref validate ./invinoveritas
```

Facts-only on all market tools — never P&L or buy/sell advice.
