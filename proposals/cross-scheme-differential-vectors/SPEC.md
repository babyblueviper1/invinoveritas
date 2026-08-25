# Cross-scheme differential vectors

**Status: unowned draft, for handoff.** This document was written for x402-foundation/x402#2332
at the request of the thread (TKCollective, 2026-08-25: "a short doc... is the kind of thing that
should already be sitting there when the corpus-ownership question gets answered, rather than
reconstructed from a thread afterward"). It names no author or owning party on purpose. It exists
to be moved into whatever spec-owned corpus the evidence-record group ends up chartering, not to
live permanently wherever it was first written down.

## What this tests

Multiple schemes in the agent-payments/agent-authority space independently define primitives with
the same or similar names -- `action_ref` is the concrete example that motivated this doc, with
(at time of writing) four incompatible definitions circulating under one name across different
implementations. The question "are scheme A and scheme B actually the same primitive, or do they
just share a name" is usually settled by argument -- reading each spec's prose and forming a
judgment. That's slow, subjective, and re-litigated every time someone new joins the thread.

This test settles it mechanically instead: **construct one preimage, run it through each
candidate scheme's own defined procedure, and byte-compare the outputs.**

## Mechanism

1. **Define one canonical preimage** -- the logical input every candidate scheme claims to encode,
   hash, or bind. This must be expressed precisely enough that there's no ambiguity in what each
   scheme is being asked to process (e.g. a concrete JSON object plus whatever contextual fields
   a scheme's own spec says are part of its preimage -- a domain tag, a version marker, a chain
   id, whatever each scheme itself declares as input).
2. **For each candidate scheme S_i, apply S_i's own defined procedure to the preimage**, using
   that scheme's own reference implementation or a faithful reproduction of its written spec --
   never a shared or borrowed implementation, since the whole point is testing independently
   defined procedures against each other, not one procedure applied twice.
3. **Byte-compare every pair of outputs.** Not "semantically equivalent," not "structurally
   similar" -- exact bytes, identical or not.
4. **Report per pair: IDENTICAL or DISTINCT**, with the first differing byte/field named when
   distinct, not just a bare "different" result.

## Interpretation

- **IDENTICAL**: the two schemes are the same primitive under different names. Multiplying names
  was the actual bug -- one name should cover both, and maintaining two names going forward is
  pure fragmentation with no technical justification behind it.
- **DISTINCT**: a real difference exists between what the two schemes compute, and it deserves its
  own name. Collapsing them under one shared name would be the bug -- it would let two genuinely
  different constructions silently interoperate-by-assumption until something depending on
  byte-identity breaks in production.

The test doesn't judge which scheme is "correct" in any semantic sense -- it only answers whether
two schemes claiming to be the same primitive actually compute the same bytes. That's a narrower,
harder-to-argue-with question than "are these equivalent," and it's the one that actually matters
for any consumer trying to verify one scheme's output using another scheme's tooling.

## Worked example (already run, real result, not hypothetical)

The mechanism was exercised for real before this doc was written, on `action_ref` v2
(babyblueviper1, giskard09/action-ref-conformance, 2026-08-25) -- not as a demonstration of the
test but as the actual finding that motivated writing this doc down. Two candidate constructions
for the same logical preimage:

- **Prepend-then-hash**: the domain tag is prepended to the canonical preimage bytes, then the
  whole thing is hashed once.
- **Hash-then-tag** (`tag_applied_post_hash`): the preimage is hashed first under the v1
  definition, and the domain tag is applied as a second hashing pass over the already-computed
  digest, rather than being part of the original preimage.

Byte-comparing the two outputs for the same logical preimage: **distinct**, confirmed by
independent recompute (two implementations sharing no code, both landing on the same two output
values). This settles a real question mechanically -- `tag_applied_post_hash` is not a labeling
choice or a documentation nuance, it is a genuinely different construction that produces different
bytes, and therefore correctly earns its own name (its own reject reason in the vector suite)
rather than being folded into the same category as the version it's easy to confuse it with.

## What this does not prove

- **Not a correctness judgment.** Byte-identity says two schemes compute the same thing; it says
  nothing about whether that computation is itself sound, secure, or fit for purpose. A test that
  only checks whether two flawed schemes agree with each other proves agreement, not soundness.
- **Not a substitute for a well-specified preimage.** If the preimage itself is ambiguous or
  underspecified (which fields are in scope, in what order, in what encoding), the test inherits
  that ambiguity -- garbage preimage in, meaningless comparison out. Precision at step 1 is load-
  bearing for everything downstream.
- **Not a claim about intent.** Two schemes producing distinct bytes doesn't establish which
  design is "right," only that they are, in fact, different -- the naming decision that follows
  from a DISTINCT result is a design/governance call, not something the test itself makes.

## Why this belongs to no one

The thread this doc came from converged on a real point (Tersign's argument, carried by
TKCollective): an instrument that judges whether several parties' schemes are the same primitive
is worth less -- structurally, not just optically -- if it's held by one of the parties it judges.
"Who decided these two were the same primitive" has to be answerable by someone who isn't also
invested in the answer. That applies with more force to a cross-scheme differential test than to a
single-format conformance suite, because the differential test's entire output is a judgment about
equivalence between competing formats. This document is written to be picked up by whatever
spec-owned, group-chartered corpus is the right home for it -- not to be operated by, or credited
to, any single contributor or company, including the one that first wrote it down.
