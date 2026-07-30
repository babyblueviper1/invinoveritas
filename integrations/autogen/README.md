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
- **Optional `sign=True` + `on_verdict` callback.** `sign=True` alone attaches a portable,
  independently-verifiable signed proof to every verdict — but that proof isn't stuffed
  into the tool result text (that would spam every successful call's output back into the
  LLM's own context for no reason). Pass `on_verdict=your_callback` (sync or async, either
  works) to actually receive it: called after every real verdict with
  `(tool_name, verdict_dict)`, where `verdict_dict["proof"]` is the signed event when
  `sign=True`. Verify any proof independently, no trust required:
  `POST /verify-proof` (free, no auth). A broken `on_verdict` callback can never corrupt
  the gate's own decision — it's wrapped separately so your own logging bug can't
  accidentally turn a real `reject` into an allowed call.

  **On the public `/ledger` — `POST /ledger/submit`, 150 sats, publishes IMMEDIATELY.** Propose
  your own governed verdict as a candidate for the featured public record. No human review
  queue and no waiting: the gate is entirely objective and automated — the proof must be
  cryptographically real (checked against invinoveritas's own published key, so nothing
  forged or fake can ever land here), the account must be real, and payment (the real
  anti-spam mechanism, not a human or a bare rate limit — a rate-limit backstop still applies
  too). Lands under its own honestly-labeled type, `self_submitted_verdict`, distinct from a
  hand-curated `external_partner_review` entry — same full verifiability either way, including
  the same **Nostr broadcast + Bitcoin proof-of-work anchor** every other entry gets: the
  signed event is relayed to the public Nostr mesh at submit time, and a generic timer
  (`ots-stamp.timer`, no type filtering, ~15 min cadence) anchors its event_id to a Bitcoin
  block via OpenTimestamps — `committed_at` becomes a clock no chain operator or our own key
  can move or back-date. Not wired into `GovernedWorkbench` automatically, and deliberately
  not on by default — publishing every tool call from every AutoGen deployment isn't the
  point, picking the calls actually worth featuring is. Use `submit_proof_to_ledger()` from
  your own `on_verdict` callback for those:

  ```python
  from governed_workbench import GovernedWorkbench, submit_proof_to_ledger

  async def on_verdict(name, verdict):
      if verdict.get("verdict") != "approve":
          return  # only the strong, notable ones
      result = await submit_proof_to_ledger(
          verdict["proof"]["event"], api_key=API_KEY,
          note=f"AutoGen tool call: {name}",
      )
      print(result)  # {"status": "published", "entry": N, "ledger_url": ...,
                      #  "bitcoin_anchor": "not yet -- check .../ots in ~15 min", ...}

  guarded = GovernedWorkbench(inner, api_key=API_KEY, sign=True, on_verdict=on_verdict)
  ```

  Check a submission's status any time, free, no auth: `GET /ledger/submissions/{id}`.

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
