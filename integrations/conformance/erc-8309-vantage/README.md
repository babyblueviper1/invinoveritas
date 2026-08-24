# ERC-8309 vantage-authority companion — reference consumer + mutation gates

Reference implementation for the companion spec (Damon Zwicker; working group Merlini / Pavlo /
Jimmy Shi / Fede). Self-contained: nothing here imports the rest of the platform, so the gates can
be reproduced without cloning anything else.

```
python -m pytest tests/ -q                       # 38 + 14 conformance vectors
python scripts/vantage_spec_mutations.py         # surface 1 gate
python scripts/vantage_vectors_mutations.py      # surface 2 gate
```

Both scripts regenerate the JSON under `conformance/erc-8309-vantage/`. Each mutant is applied to a
copy of the module and the suite is actually run against it — a mutant counts as KILLED only if a
test really goes red, never because a table says so.

## Coverage, reported by surface — never as one total

A single number across two implementations-under-test is how "16/16" came to read as coverage it
did not have. The count was true. Its scope was `services/vantage_resolution.py`, which never
touches the vectors artifact, so three of the spec's normative MUSTs had no enforcing vector
anywhere and structurally could not have had one.

| surface | implementation under test | mutants | result |
|---|---|---|---|
| executable profile / serializer semantics | `services/vantage_resolution.py` | 16 | 16 KILLED |
| vector-artifact obligations | `services/vantage_vectors_consumer.py` | 4 | 4 KILLED |
| provenance class | — | 0 **by design** | discharged differently, see below |

**Zero-by-design is not zero-by-missing.** The provenance-class MUSTs (a required artifact, an
independently reproducible derivation) carry 0 mutants deliberately: a code mutant cannot express
"this vector was derived the wrong way." Manufacturing a vacuous mutant to complete a count would
be the §9 defect one level up. That leg discharges by the definition-derived artifact existing and
being independently reproducible — scoped to canonical-form-adversarial-vectors v0.1 and its
demonstration object only, and explicitly non-transferable.

## The vectors surface

Three MUSTs constrain the artifact and its consumer rather than the resolution module:

- `bytes_hex` REQUIRED as the normative hashable carrier
- the adversarial PAIR must be present
- a digest produced under the unbound serializer MUST be rejected

(A fourth from Merlini's map — an unbound schema MUST raise — is already banked as M15 on surface
one. Three are outstanding here, not four.)

The module is a **consumer**, not a validator of convenience: every MUST is expressed as a path
that REJECTS, because a checker that can only pass proves nothing when mutated. Rejection of the
wrong-serializer digest is *earned* — the conforming bytes are recomputed under the bound
serializer from the demonstration object and compared — not asserted.

`V4-inventory-state-collapse` is not one of the three. It exists because if the inventory below
stops distinguishing "no set at all" from "a set that fails," the report collapses back into a
single blank and the whole by-surface exercise is undone.

## Golden-set inventory — three states, structurally

| binding | state |
|---|---|
| `ccip.attestation.unsigned.v1` | no denominator yet |
| `crc.claim` | no denominator yet |
| `decision_ref` | no denominator yet |
| `erc-8309-vantage-authority-companion` | no denominator yet |
| `recompute-kit.artifact` | no denominator yet |
| `tsei.frozen-artifact` | no denominator yet |

**0 of 6 bindings have a conforming published vector set.** The three values — *has a conforming
set* / *needs a conforming set* / *no denominator yet* — are kept distinct in the emitted JSON so
"missing" and "not applicable yet" can never share a blank, and `complete` is computed over all
bindings so an inventory covering one binding can never print complete. A complete validator over
an incomplete inventory still under-discharges §5.

## The gate found a hole in its own suite on the first run

`V2-adversarial-pair-optional` SURVIVED. Recorded rather than quietly fixed, because the enforcing
artifact is audited against its own rule first.

For a *list* input the `len(vectors) < 2` guard is shadowed by the serializer-count guard below it,
so removing it changes nothing — equivalent there. For a **non-list** input it is the only
protection, and nothing in the suite exercised that shape. Adding it exposed a real defect
underneath: `check_binding_set`'s `or []` iterated a truthy non-list, so a function whose contract
is that it never raises did. Both are fixed and V2 now dies to genuine coverage, not to a weakened
mutant.
