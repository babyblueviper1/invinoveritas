# Independent approval for MCP tool calls (Responses API)

The OpenAI Responses API, and servers that implement it such as [OGX](https://github.com/ogx-ai/ogx) (the Open GenAI
Stack, formerly Llama Stack), can hold a remote MCP tool call until someone approves it. Mark the server
`require_approval: "always"` and the response stops with an `mcp_approval_request`. The client answers with an
`mcp_approval_response` (`approve: true` or `false`) and continues with `previous_response_id`.

That answer is usually a person clicking a button, or code that always says yes. `approver.py` answers it with a
signed [invinoveritas](https://invinoveritas.dev) `/review` verdict instead:

- the verdict binds the exact call: tool `<server_label>/<name>`, the parsed arguments and your agent id
  (`action_binding`), so the signed proof says which call was approved;
- `approve` is true only when the verdict is in `proceed_on` (default `approve`, `approve_with_concerns`);
- each decision keeps the proof, which anyone can check for free at `POST /verify-proof` or offline against the
  published key, and `call_bound` confirms locally that the proof binds this tool and these arguments.

## Use

```python
from openai import OpenAI
from approver import run_with_approvals

client = OpenAI()                      # OGX: OpenAI(base_url="http://localhost:8321/v1", api_key="unused")
final, decisions = run_with_approvals(
    client,
    agent_id="refund-agent-prod",
    model="gpt-4.1-mini",
    tools=[{"type": "mcp", "server_label": "payments", "server_url": "https://payments.example/mcp",
            "require_approval": "always"}],
    input="Refund order 1042",
    review_kwargs={"context": "Support agent; policy: refunds up to $50 without escalation"},
)
for d in decisions:
    print(d.name, d.approve, d.verdict, d.call_bound, d.proof_event_id)
```

`IVV_API_KEY` holds an invinoveritas API key (`POST /register` returns one; a verdict is a paid call). For one request
at a time, use `review_request(item, agent_id=...)` and send `decision.response_item()` back yourself.

## When /review is unavailable

The default is to **reject** (`on_unavailable="reject"`). A tool marked `require_approval` was gated on purpose, so
approving it silently while the approver is down defeats the gate. Pass `on_unavailable="approve"` to fail open, or
a `human=lambda request, review: bool` callback to hand the decision to a person. The callback is also asked when a
verdict does not allow the call.

`mcp_approval_response` carries an optional `reason` on OGX. It is off by default (`include_reason=False`), so servers
that reject unknown fields are not affected.

## Live run (2026-10-12)

`gpt-4.1-mini` on the OpenAI Responses API, our own public MCP server (`https://api.babyblueviper.com/mcp/verify`,
`allowed_tools: ["ledger"]`, `require_approval: "always"`): the model asked to call `ledger` twice, each request got a
signed verdict (`approve_with_concerns`, then `approve`; `call_bound` true both times), the tool ran after each
approval, and the model answered. 15 s end to end. Proof event ids: `c0e86baa69ce610a…`, `98d877029f43b6b2…`.

## Test

```sh
python3 -m pytest -q test_approver.py     # 13 tests, offline: mocked /review and a fake Responses client
```

One test is pinned to a real `/review` proof, so the hash construction (`"sha256:"` + SHA-256 over RFC 8785 JCS of
the args, and over the tool name) matches the server. `call_bound` needs the `rfc8785` package; without it the field
is `None`.
