# GovernedWorkbench — an invinoveritas `/review` gate for AutoGen

An independent, signed pre-action verdict on every AutoGen tool call, before it runs.
Not a fork of AutoGen, not a patch — a `Workbench` wrapper that works **today** against
the currently-published `autogen-core`/`autogen-agentchat` (verified against `0.7.5`,
2026-07-30), because `AssistantAgent` already accepts any `Workbench` via its
`workbench=` constructor argument.

## Why a `Workbench` wrapper

AgentChat's *only* tool-execution code path is `Workbench.call_tool()` /
`call_tool_stream()` — `AssistantAgent._execute_tool_call` iterates
`self._workbench` and calls one of those two methods, whether the tool came from a
plain `tools=[...]` list (auto-wrapped into a `StaticStreamWorkbench`), an MCP server
(`McpWorkbench`), or anything else. Wrapping at this single seam gates *every* tool
passed to the agent, with no per-tool wiring.

This mirrors the community's own stated need — see AutoGen issues
[#4894](https://github.com/microsoft/autogen/issues/4894),
[#5891](https://github.com/microsoft/autogen/issues/5891), and
[#7405](https://github.com/microsoft/autogen/issues/7405) / open PR
[#7881](https://github.com/microsoft/autogen/pull/7881) — none of which have shipped a
`Workbench`-level approval mechanism as of 2026-07-30. `GovernedWorkbench` is usable
right now without waiting on any of them to merge, and (per #7405's own "Integration
Point 2") is a natural complement to #7881's `BaseTool`-level `GuardrailProvider` work
if that lands upstream later — different layer, same idea, not a competing design.

## Install

```bash
pip install httpx autogen-core autogen-agentchat
# GovernedWorkbench itself is a single file, drop governed_workbench.py into your project
# (a PyPI package is a reasonable next step once this has real external usage).
```

Get a free API key (3 calls free, no payment, instant):
```bash
curl -s -X POST https://api.babyblueviper.com/register -d '{"agent_id":"my-autogen-agent"}' | jq -r .api_key
```

## Use

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_core.tools import StaticStreamWorkbench, FunctionTool
from governed_workbench import GovernedWorkbench

def deploy(target: str) -> str: ...

inner = StaticStreamWorkbench(tools=[FunctionTool(deploy, description="deploy to target")])
guarded = GovernedWorkbench(inner, api_key="ivv_...", mode="gate")

agent = AssistantAgent("worker", model_client=my_model_client, workbench=guarded)
# every tool call now goes through an independent /review verdict first.
# a `reject` verdict blocks the real tool from running; approve/approve_with_concerns
# always delegate through, unchanged.
```

## Design

- **Fail-open, always.** Any problem on the `/review` side — network error, timeout,
  malformed response, missing API key — and the tool call proceeds exactly as if
  ungated. A safety integration that can itself hang or crash your agent loop is worse
  than none; this can only ever add a bounded amount of latency (`timeout_s`, default
  15s) or do nothing at all.
- **`mode="gate"` (default) vs `mode="advisory"`.** Gate mode blocks on a real `reject`
  verdict — the actual point of a safety-approval integration. Advisory mode never
  blocks, only logs the verdict — useful for a dry-run rollout before flipping to gate.
- **Never overrides an `approve`.** Only `reject` (in gate mode) blocks; `approve` and
  `approve_with_concerns` always delegate through to the real tool.
- **`should_review` callback** to skip specific tool names (e.g. read-only ones) without
  spending a call on them.
- **Optional `sign=True`** attaches a portable, independently-verifiable signed proof to
  every verdict (verify at `POST /verify-proof`, free, no auth) — so a downstream
  consumer of the agent's output can confirm the gate actually ran, without trusting the
  agent or invinoveritas.

**Honest limitation:** `AssistantAgent`'s streaming tool-call path only activates for a
workbench that is `isinstance(wb, StaticStreamWorkbench)` specifically. Since
`GovernedWorkbench` *wraps* a workbench rather than *being* one, it always goes through
the plain (non-streaming) `call_tool()` path — same behavior as `autogen-ext`'s own
`McpWorkbench`, for the identical structural reason. The final result is unaffected;
only a `StreamTool`'s intermediate progress events aren't surfaced.

## Tests

```bash
pip install pytest pytest-asyncio
python -m pytest tests/test_governed_workbench.py -v   # offline, deterministic, no network
IVV_API_KEY=ivv_... python tests/dogfood_live.py        # live, real calls against the real API
```

The live dogfood test fires a real benign tool call (approved, real result returned)
and a real dangerous one (a `curl | sudo bash` deploy step — same canonical example the
[loop-verifier](../agentskills/loop-verifier/SKILL.md) skill uses) against the actual
`https://api.babyblueviper.com/review` endpoint and confirms it gets blocked before the
dangerous tool ever executes.

## What invinoveritas is

The verification layer for autonomous agents: an independent, model-agnostic verdict
*before* an irreversible action (`/review`), a signed proof *after* (`/prove`), and a
public, Nostr- and Bitcoin-anchored track record (`/ledger`) checkable without trusting
us. Full docs: https://api.babyblueviper.com/llms.txt
