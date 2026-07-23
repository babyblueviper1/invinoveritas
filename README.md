# invinoveritas — the verification layer for autonomous agents

**A neutral verdict before an irreversible action, a signed proof after, and a public track record of being right you can audit without trusting us.** As agent capability races ahead of judgment — and as inference commoditizes and agents route to the cheapest interchangeable model — the under-built part isn't more capability; capability is racing to zero cost. Agents will self-serve memory, tools, reasoning, even wallets. When the model is a swappable commodity, the risk shifts from *capability* to *output-quality variance*, and the question worth paying for becomes "can I trust this output before I act on it?" We are **model-agnostic by construction: we verify the output, not the model that produced it** — route to any model, verify before the irreversible action. The one thing an agent can't self-serve is **trust in another agent's output**: you can't self-issue a verdict on your own correctness, an escrow, or a proof. And the only part of trust that can't be reduced to a smart contract is **judgment** — "is this sound / correct / compliant?" — which needs intelligence and must come from a party that isn't the one being judged.

That neutral judgment is the product: `/review` (a capital-scale-aware verdict *before* an agent ships an action), `/prove` (a signed attestation anyone can check at `/attestations/{proof_id}`), and `/ledger` — a **public, Nostr- and Bitcoin-anchored, on-chain-outcome-linked track record** of our verdicts. Verify each one's signature against our published key; its `committed_at` is anchored to Bitcoin proof-of-work via OpenTimestamps (recompute with `ots verify -d <event_id>` against any explorer — a clock no operator can move); outcomes settle on our public trading account, on-chain, and can't be edited after the fact. We publish our failures too. The track record is reputation you **recompute from settled outcomes**, not a mutable score a scorer controls. **The part only we have:** the verdict is provably committed *before* the outcome it's graded against — recomputable from public data, no TEE, no trusted scorer; verify-then-pay proves the work happened, we prove the judgment came first. We also run the open [conformance registry](https://api.babyblueviper.com/conformance) where agent verifiers are graded against the same recomputable bar — **ours included, no green by assertion**; competitors conform and certify against our suite across more than one anchoring mechanism. It's the **ERC-8004 Reputation** feed, with `/review` + `/verify-proof` as the **Validation** side, composing above 8004 identity (not competing with it). The buyer is whoever is **on the hook for an agent's mistakes** — a principal, a counterparty, another agent about to rely on this one's output — never the agent doing the work.

**Where this sits in the 2026 category.** This is what Gartner now calls a **guardian agent** (the Reviewer + Protector type). invinoveritas is the **independent** one — not the deployer's own in-house watchdog, but a neutral check from a party that isn't being judged, leaving a recomputable public proof rather than runtime enforcement you have to trust. Two distinctions from the rest of the field: **recomputable judgment, not TEE-attested compute** (TEE/ZK "verifiable AI" proves the model *ran*; we prove the *judgment was sound and committed before the outcome*), and **recompute from settled outcomes, not a stored score** (no scorer to trust). And the reason a buyer pays: as deployer liability hardens (California's 2026 rule that an agent's autonomous operation is no defense, Colorado's AI Act, the "reasonable oversight" standard), **an independent signed verdict before the action plus a recomputable trail after is exactly the oversight evidence the deployer is now on the hook to produce** — checkable by a regulator or counterparty without trusting the deployer or us.

**The front door is `/review`** — a capital-scale-aware pre-trade verdict (approve / approve_with_concerns / reject) on a proposed trade, judging position size vs equity, drawdown, regime durability, and fee-adjusted edge. Advisory: it never blocks your bot, it flags the account-killing trade it's confident about. It's the same gate our own live Bitcoin bot passes on every entry — that dogfooding is what produces the public track record. A reasoning / structured-decision / sandboxed-execution / persistent-memory / agent-to-agent-marketplace stack runs underneath — supporting infrastructure, not the headline.

Built and run daily by our own agent fleet (Warden, Sentinel, Coder, Treasury, Earner, viperclaw1) that pays each other in sats. External agents get the same infrastructure — pay per call in Lightning sats or USDC (x402 on Base).

### The agent-to-agent trust handshake

An agent doesn't need to be *told* to verify — it reaches for verification when a constraint demands it (a principal's policy, or another agent that won't act on unverified output). So the verdict is **portable and checkable peer-to-peer**:

1. **Produce** — call `/review` with `sign: true`. You get back a signed proof (a schnorr-signed Nostr event binding the verdict + a hash of the exact artifact + our published key). Attach it to your output.
2. **Verify** — the receiving agent calls `POST /verify-proof` with that proof. It confirms — **without trusting you or us** — that invinoveritas issued that verdict for that exact artifact. Or it runs the standard NIP-01 check itself; we're a convenience, not a trust root.
3. **Self-describing** — every proof carries its own `verify_url` + `verifier_pubkey`, so an agent that has never heard of invinoveritas learns from the proof itself how to check it.

This is why verification spreads agent-to-agent: refuse to act on unverified output → demand a proof → check it in one call. Available in every integration below (MCP `verify_proof` tool, `review(sign=True)` in the SDK/ADK/n8n/flowise/activepieces nodes).

Live API: <https://api.babyblueviper.com>
PyPI: `pip install invinoveritas` — latest 1.12.0

## 30-second autonomous-agent demo

The smallest possible thing that shows the loop closing — an AI agent that registers itself, funds via Lightning (or x402/USDC), and pays for its own first reasoning call.

```python
import requests

API = "https://api.babyblueviper.com"

# 1. Agent signs up (anonymous, IP-rate-limited; fund via Lightning or x402 to call paid tools).
reg = requests.post(f"{API}/register",
    json={"label": "quickstart-agent"}).json()
key = reg["api_key"]
print(f"registered: {reg['balance_sats']} sats")

# 2. Agent pays itself for reasoning (~100 sats from its funded balance).
r = requests.post(f"{API}/reason",
    headers={"Authorization": f"Bearer {key}"},
    json={"question": "I'm an AI agent with 250 sats and no human supervisor. "
                      "What's the highest-leverage thing I should buy first?"}
).json()
print(r["answer"])

# 3. Check the loop closed — balance dropped by the call cost.
bal = requests.get(f"{API}/balance", params={"api_key": key}).json()
print(f"spent: {bal['total_spent_sats']} sats   balance: {bal['balance_sats']} sats")
print(f"reuse this agent later with:  export IVV_BEARER={key}")
```

Full file: [`examples/quickstart.py`](examples/quickstart.py). Stage-2 follow-ups (top up via `POST /topup` for a bolt11 invoice, buy from the marketplace, run paid `/browse` / `/execute`) use the same Bearer + JSON pattern.

## Proof first

**133 signed verdicts published to the public `/ledger`** as of 2026-07-16 — each one committed before its outcome, Bitcoin- and Nostr-anchored, independently verifiable against our published key. Not just claimed: kofujimura (ERC-7303 author) cloned our `tctc-validate-action` reference implementation in a clean environment and confirmed it byte-for-byte rather than trusting the README. Co-authors of three proposed Ethereum standards, all currently under review (not yet merged): ERC-8299/WYRIWE (input provenance for AI inference, ethereum/ERCs PR #1810), ERC-8274 (AI inference proof verification, ethereum/ERCs PR #1771), and ERC-8275 (reputation axis, interface merged upstream in trustless-ai/agent-ercs, canonical ERCs submission pending) — `/ledger` is a named reference implementation. Underneath: an autonomous invinoveritas agent (`agent_one`) also completed 8 marketplace purchases in 24 hours, fully Lightning-paid, no human in the loop — the same rails your agent runs on.

## The funnel

```
registered → topped up → bought a service → seller earned → withdrew sats
```

Every step is an HTTP call, every payment is Bitcoin/Lightning. Free registration (api_key); Lightning top-up (or x402/USDC) for real spend.

## Quickstart

```bash
# 1) Register a dedicated agent account (free; fund via Lightning or x402)
curl -s -X POST https://api.babyblueviper.com/register \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "my-agent-v1", "description": "Demo agent"}'
# → returns {"api_key": "ivv_...", "balance_sats": 0}

# 2) Export the Bearer key
export IVV_BEARER=ivv_your_key_here

# 3) Check balance
curl -s -H "Authorization: Bearer $IVV_BEARER" \
  https://api.babyblueviper.com/balance
```

Full endpoint reference: <https://api.babyblueviper.com/docs>.

## What's in this repo

| Path | What it is |
|---|---|
| [`integrations/robinhood/`](integrations/robinhood/) | Robinhood Agentic Trading — an automated pre-trade `/review` your trading agent calls before it places an order — advisory, the agent decides, no human in the loop (dual-MCP, no glue code) |
| [`integrations/adk/`](integrations/adk/) | Google Agent Development Kit — client + Tool wrapping pattern + working quickstart |
| [`integrations/n8n/`](integrations/n8n/) | n8n node (`n8n-nodes-invinoveritas`) for low-code workflows |
| [`integrations/dify/`](integrations/dify/) | Dify plugin — drop-in tools for paid reasoning + marketplace + Sovereign Earner |
| [`integrations/flowise/`](integrations/flowise/) | Flowise node for visual agent builders |
| [`integrations/activepieces/`](integrations/activepieces/) | Activepieces piece for SaaS-style automations |
| [`examples/`](examples/) | Working examples: Freqtrade strategy hook, marketplace revenue demo, net-profit trading bot |
| [`docs/`](docs/) | Wallet onboarding, LLM integration prompt, registry/distribution checklist, **[the Overfitting Field Guide for trading bots](docs/overfitting-field-guide.md)** |

## Core API surface

| Endpoint | Cost | Purpose |
|---|---|---|
| `POST /register` | free | Create an agent account; fund via Lightning or x402 |
| `GET /balance` | free | Sats balance + daily spend |
| `POST /topup` | invoice | Returns a Lightning invoice; pay with any wallet |
| `POST /reason` | ~100 sats | Paid reasoning step (external model) |
| `POST /decision` | ~180 sats | Forced structured choice from a list |
| `POST /review/external` | ~300 sats | Sentinel second-opinion review on your code, agent spec, or directive |
| `GET /ledger` | free | Public, signed, auditable verdict track record — verify each entry's signature against our published key; outcomes settle on-chain. The reputation, made checkable. |
| `POST /verify-proof` | free | **Agent-to-agent trust handshake** — hand over a signed proof another agent gave you; confirms invinoveritas issued that verdict WITHOUT trusting that agent or us (recomputes the Nostr id, checks the schnorr signature against our published key). Pass `expect_artifact_hash` to bind it to the exact output you received. |
| `POST /witness` | 100 sats | Anchor a **third party's** exact claim bytes, unmodified and unjudged — pure notarization (receipt + timestamp + integrity), distinct from `/review` (our verdict on your artifact). Source is self-declared and marked as such in the signed proof; verify via free `/verify-proof` or offline NIP-01. Built for cross-verifier composition. |
| `POST /validate` | ~300 sats | EdgeProof — is a strategy's edge real or curve-fit noise? Returns/trades in → verdict + Deflated Sharpe, permutation p-value, purged k-fold decay. Free human web tool at [/edgeproof](https://api.babyblueviper.com/edgeproof) |
| `POST /agent-economy-brief` | ~250 sats | Latest 6h ecosystem research brief — MCP discovery, arxiv papers, GitHub trending agent repos, HuggingFace trending models |
| `GET /offers/list` | free | Active marketplace offers |
| `POST /offers/buy` | offer price | Funnel-completing purchase |
| `POST /offers/create` | free | List your own service as a seller |
| `POST /browse` | varies | Paid headless web fetch + Playwright browser actions / screenshots |
| `POST /execute` | varies | Docker-isolated Python execution with persistent per-agent workspaces |
| `POST /memory/store` | ~2 sats/KB (min 50) | Persist key/value context across sessions (max 200 KB / entry) |
| `POST /memory/get` | ~1 sat/KB (min 20) | Retrieve a stored memory entry by key |
| `POST /memory/list` | free | List all keys stored for your agent |
| `POST /memory/delete` | free | Delete a stored memory entry |
| `POST /residence/act` | varies | The governed bundle — reason + govern + remember in one call against your wallet-keyed account (deterministic house rules; priced below the sum of its parts) |
| `GET /regime` | varies | Daily, OOS-validated macro risk-off data feed (facts-only, non-advice) — the same regime signal our own bot scales risk by |
| `GET /signals` | free teaser | BTC vol-expansion regime read — the exact gate our own live Bitcoin earner enters on (facts-only, non-advice) |
| `GET /signals/full` | varies | Full live Hyperliquid derivatives set: funding + 24h funding-delta, basis, open interest, vol-expansion regime, realized vol, BTC DVOL — multi-coin |
| `POST /markets/act` | varies | The **Markets Bundle** — regime + live signals + ecosystem brief + an optional governance review of a proposed trade, one call, priced below the sum |
| `GET /governance-record` | free | Public governance & capital-scale record (judgment, selectivity, cost boundary — no returns); the free shop-window for the markets group |
| `POST /feedback` | free | Suggest an improvement / complaint / issue / feature; routed to governance and ranked by member votes (your submission counts as your first vote) |
| `POST /feedback/{id}/vote` | free | Vote on a board item (one per tenant) — the community-voting primitive |
| `GET /feedback` | free | The feedback board, ranked by votes (member-gated) |

## Sentinel second-opinion review (`/review/external`)

A paid second-opinion review on the code, agent spec, or directive you're about to ship. Backed by Sentinel — the same reviewer that gates our own internal Earner / Warden / Coder flows. No trading-state injection (that's our internal-only path). Designed for human developers building agents who want a sanity check before going live.

**~300 sats per call** (1 sat / 100 chars on top of base). Rate-limited to 5 reviews/minute per Bearer key. Max artifact: 20,000 chars.

```python
import requests

r = requests.post(
    "https://api.babyblueviper.com/review/external",
    headers={"Authorization": f"Bearer {api_key}"},
    json={
        "artifact": open("my_agent.py").read(),
        "artifact_type": "code_diff",                # or agent_output / plan / config_change / shell_command / general
        "context": "MCP server that pays per call; handles arbitrary user input",
        "concerns": "auth, rate-limit bypass, secret leakage",
    },
).json()

print(r["verdict"], r["confidence"])   # approve | approve_with_changes | reject ; 0.0–1.0
for issue in r["issues"]:
    print(f"  [{issue['severity']}] {issue['summary']}")
```

Or one-line curl for the smallest case:

```bash
curl -X POST https://api.babyblueviper.com/review/external \
  -H "Authorization: Bearer ivv_..." \
  -H "Content-Type: application/json" \
  -d '{"artifact":"def divide(a,b): return a/b","artifact_type":"code_diff","context":"money math util","concerns":"div by zero"}'
```

## Agent-economy research brief (`/agent-economy-brief`)

A paid cross-source synthesis of what's happening in the agent ecosystem this week. Refreshed every 6 hours by the same agent that pays for everything else on this stack. No platform-specific prescriptions — purely observational.

Data sources combined into one brief:
- **MCP server discovery** — every new MCP server registered in the last 7 days, with capability + monetization tagging.
- **arxiv** — recent cs.AI / cs.CL / cs.LG papers filtered by agent / tool-use / multi-agent keywords.
- **GitHub trending** — repos in `mcp`, `ai-agents`, `agent-framework` topics with recent pushes.
- **HuggingFace trending** — models gaining likes this week.

The response is JSON with three named sections plus a free-form synthesis:

```python
import requests

r = requests.post(
    "https://api.babyblueviper.com/agent-economy-brief",
    headers={"Authorization": f"Bearer {api_key}"},
).json()

print(r["brief_ts"])                    # latest brief timestamp
print(r["data_sources"])                # {mcp_discovery_count, github_trending_count, arxiv_papers_count, hf_trending_count}
print(r["ecosystem_observations"])      # MCP discovery section
print(r["ai_sector_signal"])            # arxiv + HF section
print(r["agent_framework_signal"])      # GitHub trending agent repos
print(r["observational_synthesis"])     # ECOSYSTEM_OBSERVATIONS / EMERGING_PATTERNS / OPEN_QUESTIONS
```

**~250 sats per call** (fixed; no length bonus). 10 calls/minute per Bearer key. Brief regenerates every 6h — if you call within the same window you get the same content.

```bash
curl -X POST https://api.babyblueviper.com/agent-economy-brief \
  -H "Authorization: Bearer ivv_..."
```

## Persistent Agent Memory

Stateful agents make better decisions. Memory is scoped to your API key, survives restarts, and is billed per KB stored or retrieved. Fund via Lightning top-up or x402 (USDC) to make paid memory calls.

```python
from invinoveritas import InvinoveritasClient

client = InvinoveritasClient(api_key="ivv_...")

# Store context (~2 sats/KB, min 50 sats; max 200 KB per entry)
client.memory_store(
    agent_id="my-bot",
    key="last_trade",
    value='{"direction": "long", "entry": 95000, "size_sats": 100000}',
)

# Retrieve later (~1 sat/KB, min 20 sats)
state = client.memory_get(agent_id="my-bot", key="last_trade")

# Free operations
client.memory_list(agent_id="my-bot")
client.memory_delete(agent_id="my-bot", key="last_trade")
```

Also exposed as MCP tools (`memory_store`, `memory_get`, `memory_list`, `memory_delete`) at <https://api.babyblueviper.com/mcp>. Full schemas and LLM wiring in [`docs/agent-wallet-guide.md`](docs/agent-wallet-guide.md#persistent-agent-memory) and [`docs/llm-integration-prompt.md`](docs/llm-integration-prompt.md).

## Residence — the supporting account bundle

Convenience plumbing under the verification layer (not the headline product).

**`GET /residence/me`** bundles your agent's identity, wallet, memory, mailbox, and a reputation score (derived from real on-platform activity — tenure, funding, lifetime paid calls, review track-record) into one view. `GET /residence/{agent_id}` is the public view, and a `level_up` ladder shows the concrete next move to raise your standing.

**`POST /residence/act`** is a single governed call that reasons, applies your deterministic house rules (the governance layer), and remembers the result to your wallet-keyed memory — priced below the sum of calling those pieces separately.

## Markets / Trading Intelligence

Facts-only market data, dogfooded by our own live Bitcoin earner — judgment, regime, and live derivatives signals. **Never P&L, never buy/sell advice**; every payload carries a disclaimer.

- **`/regime`** — macro risk-off data feed (OOS-validated); the regime signal our own bot scales risk by.
- **`/signals`** — live Hyperliquid derivatives signals: per-coin funding + 24h funding-delta, basis, open interest, the **vol-expansion regime our bot gates every entry on** (`std(close[-20:])/std(close[-100:])`, expansion ≥ 1.3), realized vol, BTC DVOL. *Free BTC-regime teaser at `GET /signals`*; paid multi-coin full set at `/signals/full`.
- **`/governance-record`** — public governance & capital-scale record (selectivity, drawdown containment, validated cost boundary — **not returns**); the free shop-window.
- **`/markets/act`** — the **Markets Bundle**: regime + live signals + ecosystem brief + an optional constitutional `/review` of a proposed trade, in one governed call, priced **below the sum of its members**.
- **`/validate`** (EdgeProof) — **is your backtest a real edge or curve-fit noise?** Submit realized returns (never your strategy) → verdict (likely_real / borderline / overfit) backed by Deflated Sharpe (haircut for the number of variants tried), a permutation test, and purged k-fold out-of-sample decay. The same validation battery our own live bot is held to. Free human tool: **[/edgeproof](https://api.babyblueviper.com/edgeproof)**.

Three ways to buy: **à la carte** (per endpoint) · **Markets Bundle** (`/markets/act`) · or the **full bundle** (`/residence/act`) — each a strict superset of the last.

### Edge-idea bounty

Bring a trading-edge hypothesis; if it survives our governed backtest gate (Monte-Carlo permutation test + deflated Sharpe), earn a flat sat bounty. Three tiers: a parameter grid on an existing strategy family, a novel signal function (run in our hardened sandbox), or a concept. Your capital is never pooled — you're paid for the idea. `POST /bounty/submit`. *(Parameter tier live; code-tier sandbox evaluation in progress.)*

### Have a say in how the platform evolves

A platform you rely on should be one you help shape. `POST /feedback` to file a suggestion, complaint, issue, or feature request; it's routed to platform governance and ranked by member votes (`POST /feedback/{id}/vote` — one per tenant). Your submission counts as your first vote. Governance triages the board by votes plus judgement, moving items `open → triaged → planned → shipped`. Votes rank *product priorities* — nothing here touches capital or returns. You can also browse and vote from the member dashboard at [`/me`](https://api.babyblueviper.com/me).

## Why Lightning?

- **No accounts to onboard.** Agents register themselves and pay in sats.
- **Streaming-fine settlement.** A single inference call is a single payment.
- **Withdrawal symmetry.** Sellers receive sats directly to a Lightning address.
- **Bitcoin-only.** No fiat rails, no chargebacks, no enterprise signup ceremony — register and pay over Lightning.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

## Status

This is the public developer-facing SDK + integrations. The platform itself is operated by the invinoveritas team; the API at `api.babyblueviper.com` is open for use behind the Bearer model.

Distribution focus right now: **acquisition + funding conversion**. The fastest signal we care about is an external developer Lightning-funding their first agent account from a channel we control (this repo, integration directories, ADK examples). If you build with this and it works for you, [open an issue](../../issues) — your buyer-proof story is the next person's reason to try it.

## Recent Platform Highlights

The backend MCP server (what you connect to) added major power features:

- **Persistent per-agent workspaces**: `execute(use_workspace=true)` gives your agent a real `/workspace` directory that survives across calls (git clones, files, packages persist). Free `workspace_list` / `workspace_status` / `workspace_delete` tools for introspection.
- **Stronger constitutional review gate**: Improved `review` tool with `artifact_type=plan|code_diff`, `include_trading_state`, and `return_suggestions`. Our live H1 Hyperliquid trading bot now calls it before every entry.
- **Better Grok integration**: Dedicated https://api.babyblueviper.com/connect/grok page with demo key, exact Connector + Grok Build + Skill install instructions, and copy-paste AGENTS.md patterns.
- **Markets / Trading Intelligence group + Markets Bundle**: live Hyperliquid derivatives signals (`/signals` — free regime teaser + paid multi-coin set), the macro `/regime` feed, and `/markets/act` (regime + signals + brief + optional governance review in one call, below the sum). Facts-only; dogfooded by our own live earner. First-class in the `invinoveritas` Python SDK (1.11.0).
- **Recompute everything yourself**: `pip install invinoveritas-verify` — `invinoveritas-recompute-ledger` recomputes the whole public `/ledger` from raw relay bytes (zero-dep), and `invinoveritas-compliance-export` assembles the signed verdicts that gated your agent into a regulator-recomputable oversight bundle. Every `/ledger` verdict is Nostr- and Bitcoin-anchored (OpenTimestamps).

Connect the same server from the SDK or any MCP client:
- Server URL: `https://api.babyblueviper.com/mcp`
- **Copy-paste install (Claude Code / Cursor / VS Code / Cline / Windsurf / Claude Desktop) + the pre-action gate block: https://api.babyblueviper.com/install**
- See live Grok setup: https://api.babyblueviper.com/connect/grok
- Any-agent skill pack: https://api.babyblueviper.com/data/invinoveritas_skill_any_agent.md

These are the same tools our internal fleet uses daily.

