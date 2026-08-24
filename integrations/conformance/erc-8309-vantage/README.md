# ERC-8309 vantage-authority companion — reference consumer + mutation gates

Reference implementation for the companion spec **v0.3.3** (Damon Zwicker; working group Merlini /
Pavlo / Jimmy Shi / Fede). Self-contained: nothing here imports the rest of the platform, so both
gates can be reproduced without cloning anything else.

```
python -m pytest tests/ -q                       # 42 + 14 conformance vectors
python scripts/vantage_spec_mutations.py         # surface 1 gate
python scripts/vantage_vectors_mutations.py      # surface 2 gate
```

Both scripts regenerate the JSON under `conformance/erc-8309-vantage/`. Each mutant is applied to a
copy of the module and the suite is actually run against it — a mutant counts as KILLED only if a
test really goes red, never because a table says so.

## Coverage, reported by surface — never as one total

| surface | implementation under test | mutants | result |
|---|---|---|---|
| executable profile / serializer semantics | `services/vantage_resolution.py` | 16 | 16 KILLED |
| vector-artifact obligations | `services/vantage_vectors_consumer.py` | 4 | 4 KILLED |
| provenance class | — | 0 **by design** | discharged by reproducibility, v0.1 scope only |

**Zero-by-design is not zero-by-missing.** The provenance-class MUSTs carry 0 mutants deliberately:
a code mutant cannot express "this vector was derived the wrong way." Manufacturing a vacuous
mutant to complete a count would be the §9 defect one level up.

## Binding universe — v0.3.3 §5's exact seven names

Realigned 2026-08-24. The previously published table carried **six** bindings, collapsing
`erc-8309.envelope` and `erc-8309.verdict` into one document-id entry — **inference inside the
artifact whose own rule is "bound explicitly per schema, never inferred"** (found Pavlo, from the
generated artifacts rather than from the prose). Six = stale, seven = aligned. The names below are
transcribed from the v0.3.3 §5 bytes.

| binding | serializer | golden-set state |
|---|---|---|
| `erc-8309.envelope` | RFC 8785 JCS | no denominator yet |
| `erc-8309.verdict` | RFC 8785 JCS | no denominator yet |
| `decision_ref` | RFC 8785 JCS | no denominator yet |
| `crc.claim` | RFC 8785 JCS | no denominator yet |
| `ccip.attestation.unsigned.v1` | `encodeJsonUtf8Lf` | no denominator yet |
| `tsei.frozen-artifact` | `encodeJsonUtf8Lf` | no denominator yet |
| `recompute-kit.artifact` | `encodeJsonUtf8Lf` | no denominator yet |

**0 of 7 bindings have a conforming published vector set.** `complete` is computed over all
bindings, so an inventory covering a subset can never print complete. The document id
`erc-8309-vantage-authority-companion` is deliberately **not** a binding — passing it where a
schema is expected raises, and a test pins that.

## M6 was replaced, not relabeled

The old M6 removed `encodeJsonUtf8Lf`'s trailing LF. After the v0.3 per-schema split the companion
asserts **nothing** about the LF form beyond its binding assignments, so that mutation tested a MUST
the document no longer makes; relabeling it would have left "coverage of nothing wearing a green
digit" (Merlini). The replacement, `M6-jcs-trailing-byte-appended`, mutates the claim the companion
**does** make — a JCS-bound schema's canonical bytes are RFC 8785 with no trailing byte — by
appending `0x0a` to the JCS encoder's output. The current suite kills it. The exactly-one-LF mutant
belongs to the future LF byte-contract gate.

Both artifacts are pinned to `spec_version: 0.3.3`.

## The wrong-serializer obligation is PARTIALLY discharged

Two obligations, one discharged, one open — never blurred into done:

- **Distinguishability — discharged.** Mutation-tested and *earned* by recompute-and-compare: the
  conforming bytes are recomputed under the bound serializer from the demonstration object, so a set
  whose `failure_digest` equals that recomputation is rejected for a reason rather than by
  declaration (mutant V3).
- **Alternate-serializer equality — open, not yet provable.** The consumer checks the
  `failure_digest` for *inequality* against the conforming JCS digest. It does not recompute the
  failure side under the LF form and require *equality*, because a schema bound to one serializer
  gives it no second serializer to recompute with. So it cannot today distinguish "this is the LF
  reading of the same object" from "these are arbitrary bytes that merely differ." Both pass.
  Blocked on the full `encodeJsonUtf8Lf` byte contract being specified and bound in its own
  normative artifact.

## The gate found a hole in its own suite on the first run

`V2-adversarial-pair-optional` SURVIVED. Recorded rather than quietly fixed, because the enforcing
artifact is audited against its own rule first.

For a *list* input the `len(vectors) < 2` guard is shadowed by the serializer-count guard below it —
equivalent there. For a **non-list** it is the only protection, and nothing in the suite exercised
that shape. Adding it exposed a real defect underneath: `check_binding_set`'s `or []` iterated a
truthy non-list, so a function whose contract is that it never raises did. Both fixed; V2 now dies
to genuine coverage, not to a weakened mutant.
