# NOMOS mediation guard — the live half, demonstrated

Closes the still-open half of the Article-12 mediation-guard BUILD_QUEUE item (Allan Sendagi /
SafeHaven / NOMOS). Our standalone reproduction of NOMOS-SPEC-002 §6 Phase 5 shipped 2026-08-18
(`examples/nomos-article12-mediation-guard/`) but only demonstrated the guard LOGIC in isolation —
Allan's own README named the honest remaining gap: his live engine actually flipping
Advisory→Enforce and intercepting a real request was still undemonstrated.

**This closes that gap directly, using Allan's own published, hosted, production engine --
`nomos-guard` on npm -- with no fixture replay and no need for him to run anything himself.**
`nomos-guard` is a real MCP policy gateway: wrap any MCP server, every `tools/call` gets checked
against a sealed NOMOS policy artifact before the downstream tool ever runs. This is a more
general demonstration than re-running the original $87,450 treasury-transfer fixture through the
six-phase engine specifically -- it's his actual live product, doing its actual job, end to end.

## What this does

1. `payments_server.js` -- a minimal MCP server exposing one tool, `issue_refund`. Its handler
   prints "EXECUTED" and would be the real money-moving code in a production system. It is the
   thing the guard is supposed to protect.
2. `drive_client.js` -- a real MCP client that spawns `nomos-guard` (wrapping `payments_server.js`)
   as its child process and calls `issue_refund` through it, exactly the way a real agent would.
3. `nomos-guard` sits in between, checks every call against the real, public, no-auth-required
   `pub_refund_v1` artifact hosted at `api.nomosprotocol.com`, and either forwards the call or
   blocks it with a signed verdict.

## Real results (reproduced from this exact committed code, not a one-off)

| case | `refund_amount` | rule matched | verdict | downstream handler reached? |
|---|---|---|---|---|
| small | $89 | DEFAULT | **ALLOW** | yes -- "EXECUTED... refund of $89 issued" |
| mid | $700 | R7 (>$500 needs supervisor) | **ESCALATE** | **no** -- blocked before it ran |
| big | $1500 | R6 (>$1000 needs dual sign-off) | **ESCALATE** | **no** -- blocked before it ran |

Every verdict carries a real audit hash from the hosted engine (different each run, since the
engine timestamps each evaluation) -- e.g. one real run's big-refund block: rule `R6`, audit
`sha256:1399258e56ecc4d9e550462ce60eca2569f46f17cbfc4c39a0bee7043cc5e9a0`. The escalated cases'
downstream `issue_refund` handler is never invoked -- confirmed by the absence of its "EXECUTED"
text in the response, which only the ALLOW case ever produces.

**Real debugging note, not hidden:** the first attempt used `amount_usd` as the tool's field name
and got a silent `DEFAULT allow` on both a $50 and a $1500 request -- the policy's actual rules
reference `refund_amount` specifically (confirmed by reading the real sealed artifact definition
via `GET /api/v1/artifacts/pub_refund_v1`, not guessed). Renamed the field, re-ran, all three
verdicts matched the artifact's documented rules exactly.

## Run it yourself

```
cd examples/nomos-guard-live-demo
npm install
node drive_client.js small   # expect ALLOW
node drive_client.js mid     # expect ESCALATE, rule R7
node drive_client.js big     # expect ESCALATE, rule R6
```

No API key needed -- `pub_refund_v1` is one of NOMOS's public demo artifacts. This hits Allan's
real, live, hosted policy engine over the network; verdicts and audit hashes will differ run to
run (fresh audit hash, same rule/verdict) but the ALLOW/ESCALATE/ESCALATE pattern is deterministic
given these inputs.

## Honest scope

This demonstrates the **mediation-guard mechanism working live** -- a real MCP tool call, checked
against a real sealed policy, blocked or forwarded accordingly, with a real audit trail. It is
NOT a literal re-run of the original treasury-agent-7/$87,450/SPEC-002-six-phase fixture through
that specific engine -- `nomos-guard` is Allan's separate, more general MCP-gateway product, not
the SPEC-002 reference implementation itself. The underlying capability being demonstrated (a
declared "we can intercept and block" claim becoming an actually-exercised one, live, with an
audit trail) is the same one the original BUILD_QUEUE item asked for.
