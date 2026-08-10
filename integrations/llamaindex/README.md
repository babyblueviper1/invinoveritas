# invinoveritas /review gate for LlamaIndex

A reference implementation gating a LlamaIndex agent tool call behind an independent
`/review` verdict, using the framework's own documented human-in-the-loop event pair
(`InputRequiredEvent` / `HumanResponseEvent` -- `llama_index.core.workflow`).

Verified directly against `llama-index-core==0.14.23`'s actual `call_tool` step
(`agent/workflow/base_agent.py`): it goes straight from receiving a `ToolCall` event to
invoking the tool -- no pre-execution hook exists anywhere in the framework itself. The one
documented extension point is inside the tool function, via `ctx.wait_for_event(...)` (see
`run-llama/llama_index#18636` and the maintainer's own `human_in_the_loop` docs page). Every
existing example wires this to a REAL waiting human, unconditionally, for every gated call.

**What this adds:** the same event pair, but a human is only actually asked when an
independent `/review` verdict is uncertain or negative. A clean, high-confidence approve
resolves automatically -- no human in the loop for the common case. Mirrors the
"escalate only when needed" composition already shipped for AgentScope's
`on_check_permission` middleware and Qwen-Agent's `PythonExecutor` `confirm_callback`.

```python
from llama_index.core.workflow import Context
from review_gate import review_gate

async def delete_file(ctx: Context, path: str) -> str:
    """Delete a file at the given path."""
    result = await review_gate(ctx, tool_name="delete_file", arguments={"path": path},
                                artifact_type="shell_command")
    if result.blocked:
        return f"BLOCKED: {result.summary}"
    # ... real deletion logic
    return f"Deleted {path}"
```

## Two real bugs found and fixed while building this, both confirmed by direct testing

**1. Step replay re-fires side effects before `wait_for_event`.** llama-index-core's
workflow engine REPLAYS a step from the top every time `ctx.wait_for_event(...)` checks
against a newly arrived event -- confirmed directly: a step containing ONLY an in-memory
`wait_for_event` call (no network I/O at all) was still entered twice for a single human
response. Any side effect placed before `wait_for_event` in the same step -- like a real,
billed `/review` call -- gets re-executed on every replay unless memoized. Fixed by caching
the `/review` response in `ctx.store` (keyed by tool name + a hash of the arguments) BEFORE
ever reaching `wait_for_event`.

**2. A fresh `waiter_id` per call breaks across replays.** A naive `waiter_id =
uuid.uuid4()` generated INSIDE the step changes on every replay -- so a `HumanResponseEvent`
matched against the first `waiter_id` never matches the second one the replay generates,
hanging forever (confirmed: this reproduced the exact hang, independent of the billing bug
above). Fixed by deriving `waiter_id` from the same stable cache key used for memoization,
so it's identical across every replay of the same logical call.

Both are real, reproducible framework-level gotchas, not mistakes specific to this module --
worth knowing before building anything else on `ctx.wait_for_event` in this framework
version. See `run-llama/llama_index#22070` for a related (but distinct) symptom of the same
underlying replay semantics, reported upstream alongside this module.

## Fail-open discipline

Matches every other invinoveritas integration: any `/review`-side problem (network error,
timeout, malformed response, missing key) proceeds as if approved, never silently hangs or
blocks a tool call because our service had a bad moment.

## Live-verified

`test_review_gate_live.py` drives both branches against the real production API
(`api.babyblueviper.com`), not mocked:
- A benign read-only call (`list_files`) -- auto-approves on a clean verdict, or escalates
  and resolves cleanly on a `approve_with_concerns` one (real judgment variance observed
  live, not a fixed script).
- A destructive call (`delete_file` on `/`) -- escalates via `InputRequiredEvent` with the
  real verdict attached, resolves `blocked=True` once a simulated human says no.

```
python3 -m venv venv && venv/bin/pip install llama-index-core httpx
export IVV_API_KEY=...   # register free: POST https://api.babyblueviper.com/register
venv/bin/python test_review_gate_live.py
```
