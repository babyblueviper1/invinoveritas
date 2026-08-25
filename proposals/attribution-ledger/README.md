# Attribution ledger -- draft v1

**Status: DRAFT, not yet placed anywhere permanent.** Posted for review in `damon:general`
(trustless-ai Telegram group), 2026-08-25, per the split Merlini named: the ledger's **format**
should be an open commons standard nobody owns (invinoveritas included); **operating** a
conformant instance of it is a vendor/build lane. This draft is the format half. Comments welcome
before it moves anywhere -- Merlini is reviewing as a reviewer, not a spec-author.

## Why this exists

The group already does this by hand, in prose, in Damon's v0.3.x companion doc's §13: every row
states what someone found/said/built, credits the actor, and names who independently confirmed it.
That's the right shape -- the problem is it only exists as prose in one document, so nothing else
(a value-sharing formula, a future audit, a stranger checking a claim) can read it structurally.
This draft generalizes that shape into a machine-checkable format:

```
claim / actor / verified_by / timestamp / surface / type / evidence
```

## The rules this format enforces, and why

1. **`verified_by` is required and non-empty.** An entry with nobody independently confirming it
   is a self-assertion, not a ledger row. "That's not a trust question, it's a recompute question"
   (Merlini, damon:general 2026-08-25) -- the whole reason this format is worth building at all is
   that a claim/actor/verified_by/timestamp record can be checked by a stranger without trusting
   the operator, same reason `/review` verdicts are signed and independently re-verifiable rather
   than just asserted.

2. **An actor cannot be the sole `verified_by` for their own claim.** Self-verification alone
   collapses the whole point of the field.

3. **`type` is one of five, each first-class, none requiring a commit:** `find` / `prove` / `audit`
   / `verify` / `build`. This is the load-bearing correction Pavlo raised and Merlini locked in:
   discovery, audit, spec-correction, and independent verification are product/commons
   contributions in full, whether or not the person who did them typed the final commit. `git blame`
   structurally cannot see the other four -- that's not an oversight in git, it's the wrong tool for
   the job, which is why this format exists as its own thing rather than as a git convention.

4. **`surface` is explicit, always, never inferred.** This is the field a value-sharing formula
   reads to answer "was there verified work done ON this specific surface" -- Merlini's own
   precise boundary: "counts" is triggered by verified work on the surface, never by a product
   merely depending on or being built with outside work. A commons-repo entry and a named company's
   product-surface entry are never conflated by guessing from context.

5. **`evidence` must give a stranger something to check, not just a claim.** A commit hash, a URL
   to a real artifact, a stated recompute procedure, or a content hash -- whichever fits the entry,
   but at least one, always.

## Real examples (`examples.jsonl`)

Four entries, drawn from actual events the same day this draft was written, not fabricated for
illustration -- all four validate cleanly against `schema.json`:

- Two `find`/`build` entries from the erc-8309.envelope inventory fix (Merlini found the exact gap,
  babyblueviper1 built and shipped the fix, each verified by the other).
- One `find` entry on a real, live bug (`encode_json_utf8_lf`'s code-point-vs-UTF-16 sort
  divergence), independently reproduced by Merlini before he agreed rather than taken on faith.
- One `verify` entry from a real cross-project interop exchange with safal207 (Causal-Memory-Layer)
  on crewAI#4877 -- an independent reproduction of a published `decision_ref` hash, with zero
  import from either side's code.

**A fifth real case, deliberately left OUT of `examples.jsonl` -- worth naming explicitly, because
it's the format working as designed, not a gap.** babyblueviper1 posted a reciprocal verification
back to safal207 on 2026-08-25T16:20:39Z (running his CML fixture through invinoveritas's own JCS
path, both legs byte-identical) -- a real claim, with real evidence, but as of this draft safal207
has not yet replied to confirm it. Per rule 1 above, that means it does **not** get a ledger entry
yet. This is the format doing its job: a claim sits as a claim, visible and evidenced, until an
independent party actually verifies it -- it does not get counted just because it was made in good
faith by a track record we trust. The entry gets added the moment a real `verified_by` exists, not
before.

## v1 update: edges (`edge-schema.json`, `edges.jsonl`)

**A real gap in v0, caught the honest way -- Pavlo and Merlini posted the requirement while v0
was being drafted, and it was missed on first announcement because the thread wasn't re-checked
right before posting.** Corrected same pass, not defended as-is.

v0's `schema.json` records ONE claim. It cannot represent what this conversation actually needed:
a foundation discovery/audit/method *deliberately applied* to a Vertice surface (Pavlo, msg 3343/
3345), or the reverse -- a Vertice/commercial surface that *enabled* foundation work to exist at
all (Merlini, msg 3344: "the dinamic.eth scaffolds, the boiler kit, ai.verticecriativo.pt gave the
opening to build some of it"). Those are causal edges between two pieces of work, not properties
of a single entry -- Pavlo's own framing: "contribution follows the reproduced causal edge, not
repository location or commit authorship."

`edge-schema.json` adds exactly that, with the rules specified in-thread kept precise:

- **`edge_type` is a closed enum** (Pavlo's explicit ask): `dependency` | `verified_application` |
  `enabling_provenance`. Only `verified_application` can ever count toward a Vertice split.
  `dependency` and `enabling_provenance` are recorded for an honest, bidirectional causal graph
  and never sized -- Merlini was explicit he's not asking to size the enabling direction, only to
  keep the record honest that provenance runs both ways.
- **`counts_toward_vertice_split` is never a stored field.** It's derived: true iff
  `edge_type == "verified_application"` AND `edge_verified_by` is non-empty AND all three evidence
  fields below are present. Every other edge_type is unconditionally false. See the schema's own
  `x-derivation-rule`.
- **A `verified_application` edge needs three specific evidence refs** (Pavlo, msg 3345, kept
  close to verbatim): the exact foundation contribution being applied, the exact Vertice surface/
  feature/release/claim it was applied to, and the independent verifier who reproduced *that
  causal link* -- not just the original claim, but that the application actually happened and
  actually caused the target.

One real example in `edges.jsonl` -- a `dependency` edge (invinoveritas using trustless-ai's
serializer-binding rule; using a rule isn't a verified application of a specific discovery, so it
stays unsized). **No `verified_application` or `enabling_provenance` example exists yet, and none
is fabricated here** -- Merlini's dinamic.eth/boiler-kit/ai.verticecriativo.pt case is real but I
don't have the exact references (which specific foundation work, which specific surface, on what
date) to construct a real entry rather than an invented-looking one. That's an open item for
Merlini to fill in with the real specifics if he wants a worked example of his own case.

## Open questions for review (not resolved by this draft)

- **Where does this live?** Explicitly not decided here -- `$id` in `schema.json` is a placeholder.
  Likely a trustless-ai org repo, since the whole point is that it isn't owned by invinoveritas or
  Vertice specifically.
- **Does `verified_by` need its own evidence field**, or is a name in the array enough (with the
  underlying verification's own evidence living in a separate entry)? Left simple for v0 -- an
  entry that verifies another claim can itself be a `type: "verify"` row with its own `evidence`,
  which is how the safal207 examples above are actually structured, rather than requiring
  verification evidence to live nested inside the claim it verifies.
- **Multi-surface entries** (work that touches both a commons repo and a company's product surface
  in one PR) aren't modeled -- `surface` is a single string. Worth deciding whether that needs
  splitting into two entries or a real array field once a real case shows up.
- **What operates the reference instance, and where.** Explicitly out of scope for this draft --
  that's the vendor/build lane, a separate conversation once this format itself is settled.
