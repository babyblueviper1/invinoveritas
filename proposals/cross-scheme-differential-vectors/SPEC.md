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

**Revised (2026-08-25, real correction from TKCollective, x402-foundation/x402#2332): a single
preimage is enough to prove DISTINCT, but not enough to prove IDENTICAL.** If two procedures
produce different bytes on one input, they are different procedures -- nothing more is needed. But
if they agree on one input, that establishes agreement on that input, not sameness of the
primitive in general; two RFC-8785-compliant implementations can agree on a flat ASCII object and
still diverge on number formatting near a precision boundary, unicode normalization of keys, or
absent-versus-null. This is the same asymmetry independently named by meloliva14 the same day, in
a different domain (x402-foundation/tsc#4): "a false IDENTICAL is reachable and a false DISTINCT
is not, so the error is one-directional and invisible from inside a single comparison." The
mechanism below is written to that constraint from the start rather than patched after the fact.

1. **Define a preimage SET, not a single preimage** -- chosen specifically to exercise the points
   where two procedures claiming to be the same primitive are actually likely to diverge:
   non-ASCII keys, combining characters, integers at or near a serializer's precision boundary,
   empty-versus-absent members, nesting depth, and whatever else the specific primitive under test
   is known to be sensitive to. A set exists to make the IDENTICAL verdict earn its strength the
   same way the DISTINCT verdict already has it for free.
2. **For each candidate scheme S_i, apply S_i's own defined procedure to every preimage in the
   set**, using that scheme's own reference implementation or a faithful reproduction of its
   written spec -- never a shared or borrowed implementation, since the whole point is testing
   independently defined procedures against each other, not one procedure applied twice.
3. **Byte-compare every pair of outputs, per preimage.** Not "semantically equivalent," not
   "structurally similar" -- exact bytes, identical or not.
4. **Report per pair, per preimage: IDENTICAL or DISTINCT**, with the first differing byte/field
   named when distinct. The aggregate report MUST name the exact preimage set it held over --
   "IDENTICAL" with no stated set is exactly the unsound single-preimage claim this revision
   exists to prevent.

## Interpretation

- **DISTINCT is sound from a single preimage.** One disagreeing pair of bytes is enough -- the two
  procedures are different, full stop, and this doesn't get stronger or weaker by testing more
  preimages. Collapsing two DISTINCT schemes under one shared name would be the bug -- it would
  let two genuinely different constructions silently interoperate-by-assumption until something
  depending on byte-identity breaks in production.
- **IDENTICAL requires the whole preimage set, and is scoped to it.** "IDENTICAL across set S"
  means the two schemes agree on every preimage in S -- it does NOT mean the two schemes are the
  same primitive in general, only that no divergence was found within S. A stranger who wants a
  stronger claim can extend S with a preimage that stresses whatever S didn't cover; that's a
  legitimate way to falsify a prior IDENTICAL result, not a contradiction of it.

The test doesn't judge which scheme is "correct" in any semantic sense -- it only answers whether
two schemes claiming to be the same primitive actually compute the same bytes, over the set tested.
That's a narrower, harder-to-argue-with question than "are these equivalent," and it's the one
that actually matters for any consumer trying to verify one scheme's output using another scheme's
tooling -- with the honest caveat that IDENTICAL's strength is bounded by how well the set was
chosen to find real divergence, while DISTINCT's strength is not bounded at all.

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

**Worth being explicit about, per the revision above: this worked example only ever needed to
prove DISTINCT, which a single preimage genuinely suffices for.** It is not an example of a sound
single-preimage IDENTICAL claim, because no such claim was made here -- had the two constructions
happened to agree on this one preimage, that result alone would not have licensed "these are the
same primitive," only "these agree on this input." The set-based requirement above exists for the
IDENTICAL branch specifically; this example's soundness was never resting on it.

## What this does not prove

- **An IDENTICAL verdict is bounded by the preimage set, never a general claim.** "IDENTICAL
  across set S" means no divergence was found within S -- it is not evidence-free proof that no
  divergence exists anywhere. The asymmetry is real and one-directional: a false DISTINCT is not
  reachable (a genuine byte disagreement cannot be an artifact of the test), but a false IDENTICAL
  is reachable whenever S doesn't happen to include the input two procedures actually disagree on.
  Treat every IDENTICAL result as "agrees on everything tested so far," not "proven the same."
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
