# Attribution ledger -- draft v2

**Status: DRAFT, not yet placed anywhere permanent.** Posted for review in `damon:general`
(trustless-ai Telegram group), 2026-08-25, per the split Merlini named: the ledger's **format**
should be an open commons standard nobody owns (invinoveritas included); **operating** a
conformant instance of it is a vendor/build lane. This draft is the format half. Comments welcome
before it moves anywhere -- Merlini and Pavlo are reviewing, not co-authoring.

## Why this exists

The group already does this by hand, in prose, in Damon's v0.3.x companion doc's §13: every row
states what someone found/said/built, credits the actor, and names who independently confirmed it.
That's the right shape -- the problem is it only exists as prose in one document, so nothing else
(a value-sharing formula, a future audit, a stranger checking a claim) can read it structurally.
This draft generalizes that shape into a machine-checkable format.

## v2 revision history, honestly (not glossed over)

- **v0**: `claim / actor / verified_by / timestamp / surface / type / evidence`, `surface` as a
  free-text string, no stable entry identity.
- **v1**: added `edge-schema.json` -- causal edges (dependency / verified_application /
  enabling_provenance) between two pieces of work, after Pavlo and Merlini posted that exact
  requirement while v0 was already being drafted. Caught on a next-pass re-read, not before
  announcing v0 -- a real process gap, corrected same pass, not defended as-is.
- **v2** (this version): Pavlo's mechanical-not-prose-only round on v1 -- six specific,
  correct gaps, all incorporated:
  1. `verified_application` edges now schema-REQUIRE non-empty `edge_verified_by` and all three
     causal-evidence fields, via real JSON Schema `if`/`then`, not a description field someone has
     to read and honor.
  2. `evidence` objects reject unknown properties (`additionalProperties: false`).
  3. Ledger entries now carry a deterministic `entry_id` -- content-addressed
     (`sha256:` + hex(sha256(RFC 8785 JCS bytes of every other field)), the exact same
     construction this repo already uses for `decision_ref`/`artifact_hash` in
     `services/proof_signing.py::sign_payload`, reused rather than invented. Edges reference this
     exact identity instead of a free-form id/commit/hash string.
  4. `surface` is now a structured object (`{classification, identifier}`) with a closed
     `classification` enum (`commons` / `vertice_product` / `vendor` / `external`), not free text
     -- so a value-sharing formula reading `surface` can never conflate a Vertice product surface
     with a commons repo by inference.
  5. `counts_toward_vertice_split`'s derivation rule now ALSO requires resolving `target` to its
     ledger entry and checking `surface.classification == "vertice_product"` -- v1's rule checked
     `edge_type` and `edge_verified_by` but never actually looked at what the edge's target
     surface was, which meant a verified_application edge aimed at a non-Vertice surface would
     have incorrectly counted.
  6. `verified_by`/`edge_verified_by` array items can now be either a bare name string (v1-
     compatible) or `{name, evidence_ref}` -- moving toward "evidence-bearing verification refs,
     not only names," without breaking the simpler form when no separate verification artifact
     exists yet (Pavlo: "should eventually resolve to..." -- read as directional, not
     immediately-mandatory, so both forms stay valid).

**A real, honest consequence of tightening the identity model: the one edge example from v1 no
longer has a valid referent.** v1's `edges.jsonl` had a `dependency` edge with `source_entry`/
`target` as bare strings ("trustless-ai/agent-ercs (SDK)", "invinoveritas services/
vantage_resolution.py imports"). Under v2's rule that both ends of an edge must be real,
independently-verified ledger `entry_id`s, that example is no longer valid -- there was never a
proper ledger entry on either side of it, just a description. Rather than force a fabricated pair
of entries into existence to keep an example around, `edges.jsonl` has been removed entirely for
this version. **No edge example exists in this draft right now, and that's disclosed rather than
patched over** -- it's a real signal the stricter model is doing its job (forcing real recorded
entries to exist before an edge can reference them), not a flaw. A real edge example will exist
once two real ledger entries genuinely on either side of a dependency/application/enabling
relationship get written -- happy to build that pair for real once a genuine case shows up (e.g.
if/when a real verified-application edge onto a Vertice surface happens).

## v2.1: quick mechanical fixes, real gaps flagged for a validator (2026-08-25, Pavlo's second round)

Pavlo reviewed the actual v2 commit (not just the description) and split the remaining gaps
correctly into two classes: schema-text gaps (fixable here) and ledger-level gaps (need a real
validator with access to the full entry set, which JSON Schema alone cannot express). Fixed the
schema-text ones same pass:

- `evidence.commit` now has `pattern: "^[0-9a-f]{40}$"` -- a real constraint, not just a
  description saying "full immutable SHA."
- `evidence` now has an `anyOf` requiring at least one real carrier (`commit`/`url`/`recompute`/
  `hash`) present -- fixes a real gap where `minProperties: 1` let `{"accessibility": ...}` alone
  satisfy the evidence requirement with no actual evidence in it. Verified this actually rejects
  (tested against `jsonschema`, not assumed).
- `notes` is now explicitly documented as EXCLUDED from the `entry_id` preimage -- resolving an
  ambiguity Pavlo named (can a later correction/comment be added without changing an entry's own
  identity? yes, because it was never part of the hashed content).

**Honestly still open, correctly identified as needing a real validator, not more schema text:**
recomputing `entry_id` from its own JCS preimage and rejecting a pattern-valid-but-wrong digest;
referential integrity (does `source_entry`/`target` actually resolve to a real entry, with
UNRESOLVED as its own distinct state rather than silently deriving `counts_toward_vertice_split =
false`); mechanically rejecting `actor == sole verified_by` (JSON Schema without a `$data`
extension genuinely cannot compare an array's contents against a sibling field's value --
confirmed this is a real limitation, not laziness); append-only/supersession semantics for adding
a verifier to `verified_by` after an entry already has a citable `entry_id` (a real design
question -- adding a verifier changes the preimage, which changes `entry_id`, which breaks any
edge that already referenced the old one); and committing the synthetic pass/fail cases as real,
runnable conformance vectors rather than a reported result. These need actual code, not another
schema revision -- logged as the next real build, not deferred indefinitely.

## The rules this format enforces, and why

1. **`entry_id` is deterministic and content-addressed**, not assigned. Same claim recorded twice,
   byte-identical, necessarily produces the same `entry_id` -- that's intentional signal (a
   duplicate claim), not a collision bug to guard against.
2. **`verified_by` is required and non-empty.** An entry with nobody independently confirming it
   is a self-assertion, not a ledger row.
3. **An actor cannot be the sole `verified_by` for their own claim.**
4. **`type` is one of five, each first-class, none requiring a commit:** `find` / `prove` / `audit`
   / `verify` / `build`.
5. **`surface` is a structured, closed classification, never inferred or free text.**
6. **`evidence` must give a stranger something to check, not just a claim** -- and, v2, must state
   explicitly whether that evidence is actually resolvable by a stranger (`accessibility`), since a
   real citation behind a private group's access is not equally checkable by everyone.
7. **Causal edges (`edge-schema.json`) are typed and asymmetric**: `dependency` (recorded, never
   counts), `verified_application` (the only type that can count, and only onto a
   `vertice_product`-classified target, schema-enforced), `enabling_provenance` (recorded, the
   honest reverse-direction case, never sized -- Merlini: "not asking to size that... enabling-
   into-the-commons gets recorded, not counted").

## Real examples (`examples.jsonl`)

Four entries, drawn from actual events the same day this draft was written, not fabricated for
illustration -- all four validate cleanly against `schema.json` (including real `entry_id`s
computed with `services/vantage_resolution.py::encode_jcs`, the same encoder used elsewhere in
this repo, checked before use, not assumed correct):

- Two `find`/`build` entries from the erc-8309.envelope inventory fix.
- One `find` entry on a real, live bug (`encode_json_utf8_lf`'s code-point-vs-UTF-16 sort
  divergence), independently reproduced by Merlini before he agreed rather than taken on faith.
- One `verify` entry from a real cross-project interop exchange with safal207
  (Causal-Memory-Layer) on crewAI#4877.

**A fifth real case, deliberately left OUT -- worth naming explicitly, because it's the format
working as designed, not a gap.** babyblueviper1 posted a reciprocal verification back to
safal207 on 2026-08-25T16:20:39Z (running his CML fixture through invinoveritas's own JCS path,
both legs byte-identical) -- a real claim, with real evidence, but as of this draft safal207 has
not yet replied to confirm it. Per rule 2 above, that means it does not get a ledger entry yet.

## Open questions for review (not resolved by this draft)

- **Where does this live?** Still explicitly not decided -- `$id` in both schema files stays a
  placeholder. Likely a trustless-ai org repo, since the whole point is that it isn't owned by
  invinoveritas or Vertice specifically.
- **Multi-surface entries** (work that touches both a commons repo and a company's product surface
  in one PR) aren't modeled -- `surface` is a single object, not an array. Worth deciding whether
  that needs splitting into two entries once a real case shows up.
- **`verified_by` fully moving to evidence-bearing refs** -- v2 allows but doesn't require the
  richer `{name, evidence_ref}` form. Whether that should tighten further (require evidence_ref
  once available, or always) is open.
- **What operates the reference instance, and where.** Explicitly out of scope for this draft --
  that's the vendor/build lane, a separate conversation once this format itself is settled.
