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

Both artifacts are pinned to `spec_version: 0.3.3` — see **Runtime pins** below; this
was not true at the moment it was first claimed.

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

## A kill must be an assertion, not an error (2026-08-24)

`M6` was recorded as KILLED on **"1 error"** rather than "1 failed". Pavlo asked whether the red was
actually caused by the JCS violation. It was not.

M6's replacement string contained a backslash-n, and **`re.sub` processes escapes in the
replacement** — so it emitted a real newline into the middle of a bytes literal, producing an
unterminated string and a `SyntaxError`. pytest reported a collection error, the gate saw not-green,
and counted it KILLED. **The mutant never tested the trailing-byte claim; it broke the file.** The
honest history of the previous artifact is *15/16 plus one vacuous kill*, not 16/16.

This is the vacuous-digest defect one level up, inside the gate whose entire job is proving tests
are load-bearing: any mutation that fails to parse kills every mutant trivially, so a gate that
accepts an error as a kill can report 100% while testing nothing.

Both gates now require the red to be an **assertion failure**. A mutation that only breaks the
module is reported as `VACUOUS` and is **not** counted as a kill. After fixing the escaping, all 16
and all 4 report `1 failed` — so no other mutant was vacuous, and the current numbers are earned.

## Runtime pins

`vectors-consumer-mutations.json` previously had **no `spec_version` field at all** while this
README claimed both artifacts carried one — a documentation claim about a machine-readable property
the machine never asserted. Both now carry `0.3.3`.

`SPEC_VERSION` in `vantage_resolution.py` was still `0.2.2`, flowing into every emitted envelope and
verdict `version` and into the V1 policy version. The test that "covered" it compared output to the
same constant — a self-reference can only confirm the code agrees with itself, never that the
constant is stale. Now pinned **literally**.

`Verdict.to_obj()` emitted `schema: SPEC_ID`. The table said the document id is not a schema while
every verdict on the wire claimed it was one. Now emits `erc-8309.verdict`, pinned by a test, with
the envelope's `erc-8309.envelope` pinned alongside so a future realignment cannot fix one emitter
and silently leave the other behind.

## Kill classification is phase-bound (2026-08-25)

A mutant counts as KILLED only when the red lands **in that mutant's own mapped enforcing test,
during the call phase**:

```
pattern does not apply ............................ NOT_APPLIED
mutated module fails py_compile ................... VACUOUS
collect / import / setup fails before the call .... VACUOUS
call phase fails IN A MAPPED ENFORCING TEST ....... KILLED
call phase executes cleanly ....................... SURVIVED
```

Ladder by Merlini; `expected_kill_tests` and the teardown exclusion by Pavlo.

Classification reads a conftest hook recording `(nodeid, when, outcome, exception_class)` per
test. It previously matched the word "failed" in pytest's summary line — which agreed with the
sound rule on every live mutant, and only because pytest happens to map call-phase failures to
"failed" and pre-call breakage to "error". Correct by coincidence of another tool's formatting is
not correct by construction.

`when` is the load-bearing field. A raise during the **call** phase can be the violated behaviour
itself — a `ValueError` where a never-raise MUST is enforced — and is a genuine kill. The same
exception at collect or setup means the claim was never evaluated.

`expected_kill_tests` values are **measured, not asserted**: every mutant was run and its failing
nodeid recorded. 14 of 16 spec mutants are clean 1:1. `M6` reds four tests (honest collateral —
the mutation makes JCS emit a trailing byte, so everything JCS-dependent breaks). `M11` reds its
own enforcer *and* `M4`'s, leaving it one deleted test from being certified entirely by a test
written for a different MUST.

Wiring this found a real harness bug immediately: `M11` flipped to SURVIVED because the suite ran
under `-x`, which stops at the first failure — so `M4`'s enforcer aborted the run before `M11`'s
own mapped test could execute. That is the collection-error case in a second costume, and `-x` is
now removed from both gates.

Collateral failures are recorded rather than discarded; they measure a mutation's blast radius
against its mapped claim. Four independent tallies are asserted to sum to the mutant total as a
**hard generator failure**, never a reported field — a count derived by subtraction can hide a
category nobody named, and this artifact named two in a single day.

## §5 schemas — envelope and verdict (2026-08-25)

```
python scripts/vantage_schema_check.py
```

`conformance/erc-8309-vantage/schema/` carries the two §5 schemas. They were **derived from the
bytes the emitters actually produce**, then run back against them — not written from the prose and
assumed to match. This round produced three separate cases where text and runtime disagreed (the
six-binding table, `SPEC_VERSION` stale at 0.2.2, `Verdict.to_obj` emitting the document id), so
the schema is checked in **both** directions:

- both live emitters validate — otherwise the schema describes an implementation nobody has;
- **9 deliberately nonconformant objects are each rejected by the clause they violate** — otherwise
  the schema is decorative. A schema that accepts everything validates nothing, which is the same
  defect as a conformance test that cannot go red.

Constraints are **unrepresentable rather than discouraged**, per §2: the document identifier cannot
appear as `schema` (`const`), E5 cannot be a signed-timestamp window, E3 cannot claim global
independence, §6 has no collapsed state to name, and an insufficient-observation verdict cannot
omit its §9 inspected-set commitment.

Each schema **names its own serializer** in an `x-canonical-serializer` block, and a test asserts
the declared binding matches what `encode_for` actually does. §5 binds the serializer explicitly
per schema and never infers it — so a schema that does not name its own forces every consumer to
infer one, which is exactly the defect the per-schema rule was ratified to remove.

`erc-8309.envelope` and `erc-8309.verdict` are separate schemas with separate `$id`s. Two schemas
that share a serializer are still two bindings — the six-vs-seven correction, at schema level.
