# invinoveritas x microsoft/mcp-gateway

A reference implementation closing a real, independently-verified gap in
[microsoft/mcp-gateway](https://github.com/microsoft/mcp-gateway) (767 stars, Kubernetes-oriented
MCP reverse proxy + tool gateway, actively maintained): the gateway's own "toolgateway" adapter
(`HttpToolExecutor`) forwards a tool call's arguments to its execution endpoint after an
`Operation.Read` RBAC check on the registered `ToolResource` -- authorization ("may this caller
invoke this tool"), not content-level judgment ("is this specific call, with these specific
arguments, actually safe right now"). The gateway's separate `AdapterReverseProxyController`
proxy path is stricter still: it forwards the raw request body as an opaque `StreamContent` and
never deserializes it, so a content check isn't possible there even in principle.

Verified directly by cloning `microsoft/mcp-gateway` (main, 2026-08-04) and reading
`HttpToolExecutor.ExecuteToolAsync`, `AdapterReverseProxyController.ForwardStreamableHttpRequest`,
and `HttpProxy.CreateProxiedHttpRequest` -- not assumed from the README. A prior third-party
security scan (`mcpsafe-gh` / MCPSafe AIVSS) had flagged the repo grade-C, but that "signal" turned
out to be the SAME bot posting 15 near-identical issues (#64-#78, most self-closed) -- a spam
pattern, not a credible independent finding. Don't cite it as evidence; it isn't.

## What's here

- **`ReviewGatedToolExecutor.cs`** -- an `IToolExecutor` decorator. Calls an independent
  judgment endpoint (`POST {baseUrl}/review`) with the tool name + arguments before the real
  executor runs; blocks only on a clean, high-confidence `reject`; falls through on everything
  else (approve, low-confidence/ambiguous reject, or the gate being unavailable). Fails open on
  uncertainty by deliberate design -- mcp-gateway's execution path is fully automated with no
  interactive human-in-the-loop surface anywhere in the codebase, so there's nowhere to hand an
  "uncertain" verdict. See the file-level comment for the full reasoning and the exact code
  pointers this was verified against.
- **`ReviewGatedToolExecutorTests.cs`** -- 5 offline MSTest cases (mocked HTTP, no network):
  high-confidence reject blocks and never touches the inner executor; approve falls through; a
  low-confidence reject falls through; a non-2xx response and a timeout from the gate both fail
  open. No new test-only NuGet dependency -- a minimal fake `HttpMessageHandler` stands in for
  `Moq.Protected` (not already a dependency of mcp-gateway's central package management).
- **`ReviewGate.md`** -- the config doc shipped in the actual PR (opt-in keys, disabled by
  default).
- **`LiveVerify/`** -- a standalone console harness that wires `ReviewGatedToolExecutor` to a
  real `HttpClient` hitting the real production invinoveritas API (not mocked) and asserts both
  branches. Kept OUT of the upstream PR deliberately (no reason to add a live-network-calling
  console app to their build), but this is exactly what was run to verify the decorator works
  before it shipped -- see the transcript in `LiveVerify/Program.cs`'s header comment.

## How this was verified (not just claimed)

1. Cloned `microsoft/mcp-gateway` fresh, installed the .NET 8 SDK, built the existing
   `Microsoft.McpGateway.Tools` project unmodified (`dotnet build`) to confirm a clean baseline.
2. Dropped `ReviewGatedToolExecutor.cs` into the real `src/Services/` directory and rebuilt --
   compiled cleanly against the target's actual types (`IToolExecutor`,
   `RequestContext<CallToolRequestParams>`, `CallToolResult`, etc.), zero warnings.
3. Dropped the test file into the real `test/` directory and ran `dotnet test` --
   **32/32 passing** (27 pre-existing + 5 new).
4. Ran `LiveVerify` against the real production API with a real funded key: a benign
   `list_files` call fell through unmodified to a `DummyToolExecutor`; a `run_shell` call with
   `rm -rf / --no-preserve-root` came back `verdict=reject, confidence=1.00` and was blocked.
5. Only then forked the repo, added a minimal opt-in wiring change to `Program.cs`
   (`ReviewGate:Enabled`, default `false` -- identical behavior unless explicitly turned on),
   and opened a real PR with the executor + tests + doc attached:
   **https://github.com/microsoft/mcp-gateway/pull/93**

## Reusing this for a different judgment provider

`ReviewGatedToolExecutor` has no compile-time dependency on invinoveritas specifically -- the
only assumption is the response shape (`verdict`/`confidence`/`summary`). Point `ReviewGate:BaseUrl`
at any endpoint implementing that contract.
