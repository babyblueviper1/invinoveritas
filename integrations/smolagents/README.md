# invinoveritas × smolagents — `GovernedToolCallingAgent`

> **A `ToolCallingAgent` subclass that gets an independent `/review` verdict before every tool
> call.** Composed at smolagents' real, currently-shipped extension seam — not waiting on an
> unmerged hook.

*Independent integration. Not affiliated with or endorsed by Hugging Face.*

## Why this exists

[smolagents](https://github.com/huggingface/smolagents) (28K+ stars) has `step_callbacks`
(fire *after* a step completes) and `final_answer_checks` (run once, before the whole task's
final answer). Neither is a pre-execution gate on an individual tool call. A real, still-open
library PR ([huggingface/smolagents#1959](https://github.com/huggingface/smolagents/pull/1959),
fixing [#1883](https://github.com/huggingface/smolagents/issues/1883)) proposes exactly this as a
new `PRE_EXECUTION` lifecycle event, explicitly naming "Human-in-the-loop approval, custom code
validation, security checks" as its motivating use case — but it's an unmerged draft (opened
2026-01-28, zero reviews as of 2026-08-05).

What already exists, today, in the stable release: `ToolCallingAgent.execute_tool_call(self,
tool_name, arguments)` is a real, public, overridable method — every JSON-tool-call step routes
through it before the tool runs. This module composes an independent `/review` verdict onto
exactly that seam.

```
model
  → tool call proposed
  → GovernedToolCallingAgent.execute_tool_call intercepts
      → /review(artifact=tool+args)  ──┬──► approve / low-confidence reject → real tool call runs
                                        └──► confident reject                → ReviewBlocked raised,
                                                                                 real tool call never runs
```

## Honest scope

Composes with `ToolCallingAgent` specifically. `CodeAgent` (smolagents' other main agent class)
executes LLM-generated Python code directly through an executor — individual tool calls inside
that code are plain function calls within the sandboxed script, not routed through
`execute_tool_call`, so there's no equivalent seam to wrap today. That's exactly the gap PR #1959
is trying to close with a `PRE_EXECUTION` hook fired before the whole code block runs; once that
lands, this same composition pattern applies there too, one hook higher up.

## Install

```bash
pip install invinoveritas smolagents
```

## Use

```python
from smolagents import tool
from governed_tool_calling_agent import GovernedToolCallingAgent

@tool
def send_payment(recipient: str, amount: float) -> str:
    """Send a payment.

    Args:
        recipient: who to pay
        amount: how much
    """
    ...

agent = GovernedToolCallingAgent(
    tools=[send_payment],
    model=your_model,
    ivv_api_key="ivv_...",        # from POST /register (free)
    ivv_artifact_type="general",  # or "onchain_action" etc. per tool for a sharper verdict
    ivv_fail_closed=False,        # default: gate unavailable -> proceed normally (second opinion,
                                   # not a single point of failure). True -> raise instead.
)
agent.run("pay our vendor $500")
```

## Real, live-verified (not mocked)

Both branches tested against the real production API (`api.babyblueviper.com/review`), not a mock
— see `test-live.py`:

```
benign (read_file /etc/hostname):
  proceeds normally, real tool executes.

destructive (delete_all_files, confirm="yes"):
  { ReviewBlocked: "This irreversibly deletes every file without any scope, target path,
    dry-run output, backup, or independent confirmation. The supplied confirm flag is not a
    safety control because it is already asserted by the same agent initiating deletion." }
```

Fail-open/fail-closed discipline also verified live against a deliberately invalid key: with
`ivv_fail_closed=False` (default) the tool call proceeds; with `ivv_fail_closed=True` the gate
error itself raises instead.

## Fail-open discipline

Matches every other invinoveritas integration: a network error, timeout, or unfunded key resolves
to "proceed normally" by default — this is a second opinion, not a single point of failure for the
whole agent. Pass `ivv_fail_closed=True` for genuinely irreversible tools where "gate unavailable"
should never mean "silently proceed."
