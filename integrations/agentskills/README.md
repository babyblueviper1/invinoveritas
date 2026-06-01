# invinoveritas — Agent Skill (agentskills.io standard)

`invinoveritas/` is a portable [Agent Skill](https://agentskills.io) (the open `SKILL.md`
standard, Anthropic-originated). One skill, usable unmodified by **any** agentskills-compatible
client — **Hermes**, Claude Code, Cursor, Codex, Goose, Letta, nanobot, and dozens more.

It teaches an agent **when and how to reach for invinoveritas' paid MCP tools** — above all
to call **`review`** (capital-scale-aware governance) *before any irreversible action*, plus
the facts-only markets group, sandboxed execution, wallet-keyed memory, and agent-to-agent
payments — all pay-per-call over Bitcoin Lightning or USDC (x402).

## Install (Hermes example)
```bash
# Skills live in ~/.hermes/skills/ for Hermes; other clients use their own skills dir.
cp -r invinoveritas ~/.hermes/skills/invinoveritas
```
Then wire the MCP server (see `invinoveritas/references/REFERENCE.md` or
[../hermes/README.md](../hermes/README.md)) so the tools the skill describes are callable.

## Structure
- `invinoveritas/SKILL.md` — metadata (`name`, `description`) + when/how-to-use instructions.
- `invinoveritas/references/REFERENCE.md` — full tool table, prices, payment rails, config variants (loaded on demand).

## Validate
```bash
# canonical validator (agentskills/agentskills):
skills-ref validate ./invinoveritas
```

Facts-only on all market tools — never P&L or buy/sell advice.
