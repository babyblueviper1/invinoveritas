# Three-party action-binding — adversarial conformance vectors v0.1

Hosted here at giskard09's suggestion on [microsoft/agent-governance-toolkit#3805](https://github.com/microsoft/agent-governance-toolkit/issues/3805) — *"neither of us has a natural home for a three-party adversarial vector, so take the offer: put it up on your end."*

```
python build_vectors.py     # regenerate vectors.json — deterministic, diffable
python check.py             # reference runner, stdlib only, no network
```

## What it tests

Three independent mechanisms bind *"what an agent did"*:

| coordinate | binds |
|---|---|
| `action_ref` | domain-separated hash over (agent_id, action_type, scope) |
| `evidence_ref` | where the effect is claimed to be observable |
| `args_digest` | the arguments the action was authorized with |

Each is sound in isolation. **Each takes its inputs from the party being verified.** So a caller who reports the right *shape* but the wrong *object* produces a record that verifies under all three and still describes something that did not happen.

That is not a flaw in any one mechanism — it's a property of composing three self-reported coordinates, and it is visible only by cross-reading them. giskard09 found the same shape in `argentum-core` by self-audit ([aacaf69](https://github.com/giskard09/argentum-core/commit/aacaf698c3539d4611bb5fe1f87217ddf9bc8e3e)): *"a caller who reports the right shape but the wrong object produces a self-consistent action_ref that passes verification."*

## Negatives declare why they must fail

Every negative carries `expected_reject_reason`, and a conformant runner must report **which** check rejected — not merely that one did.

**"5/5 rejected" is not evidence.** A vector that fails to *parse* is rejected for a reason unrelated to the property it tests. With four independent implementations this gets worse, not better: a vector can be a real negative under one parser and a parse error under another, while the fixture reports green everywhere.

| id | expected_reject_reason |
|---|---|
| `N1-right-shape-wrong-object` | `cross-coordinate-mismatch` — **the seam** |
| `N2-untagged-hash-as-v2` | `missing-domain-separation` |
| `N3-tag-applied-after-hashing` | `domain-tag-not-prefixed` |
| `N4-evidence-ref-unresolvable` | `evidence-not-retrievable` |
| `N5-canary-fails-for-the-wrong-reason` | `cross-coordinate-mismatch` |

## N5 is the meta-check, and it discriminates

`N5` carries the **same seam defect as N1** *and* is structurally malformed. A runner that validates structure first — the natural way to write one — rejects it on the malformed field and never demonstrates it can see the seam at all. Verified against both runners:

```
N5 under a STRUCTURE-FIRST runner : malformed-action-ref
N5 under the fixture's runner     : cross-coordinate-mismatch
```

Both "reject". Only one has demonstrated the capability under test, and **in an aggregate count they are indistinguishable.** If your runner cannot tell these apart, that is the finding — not a failure to be papered over.

This is the same defect class that produced a vacuous mutation kill in our own ERC-8309 gate: a mutant scored KILLED for a week because a `SyntaxError` made the suite go red, so it broke the file rather than violating the claim it was written to test.

## Named non-goal

**`config_hash` / tools-list rug-pull is out of scope, deliberately.** All three mechanisms here bind *the action*. A rug-pull changes what the action's **name resolved to** — a different object — so no amount of tightening action-binding can reach it. Stated as a non-goal rather than an open item so a green run here is never read as covering it.

## Reproducing

`build_vectors.py` is deterministic — no clock, no randomness, no network — so any implementation can regenerate and diff rather than trust the committed file. Canonicalization is stated explicitly (sorted-key JSON, `(',',':')` separators, UTF-8, no trailing byte), because "canonical" unqualified is how two implementations agree on a word and disagree on bytes.

Breakage reports are the point. Run your own verifier against `vectors.json` and report what disagrees.
