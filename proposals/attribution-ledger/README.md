# Attribution ledger -- draft v3

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

## Revision history, honestly (not glossed over)

- **v0**: `claim / actor / verified_by / timestamp / surface / type / evidence`, `surface` as a
  free-text string, no stable entry identity.
- **v1**: added `edge-schema.json` -- causal edges (dependency / verified_application /
  enabling_provenance) between two pieces of work, after Pavlo and Merlini posted that exact
  requirement while v0 was already being drafted. Caught on a next-pass re-read, not before
  announcing v0.
- **v2**: entries got a deterministic content-addressed `entry_id`; `surface` became a structured
  `{classification, identifier}` object; `verified_application` edges got real JSON Schema
  `if`/`then` enforcement; `verified_by` items could carry `evidence_ref`.
- **v2.1**: three quick mechanical fixes (commit-hash pattern, a real `evidence` carrier
  requirement, `notes` excluded from the `entry_id` preimage) from Pavlo's second review round,
  plus a list of genuinely ledger-level gaps (needing a real validator, not more schema) logged
  honestly rather than forced into schema text that can't express them.
- **v3** (this version, 2026-08-25): **the commons stops at attribution; sizing is out.**

## v3: removing `counts_toward_vertice_split` -- the real reason, not a cosmetic rename

v2's `counts_toward_vertice_split` derivation rule hardcoded a single company's compensation logic
(Vertice's) into a format whose own README opened by calling itself "an open commons standard
nobody owns." Merlini named the concrete asymmetry this produced, grounded in his own real work
that week: he verified a v2 production-grounding receipt on ReceiptOS's own artifact, and separate
erc-8309-envelope vectors he built landed in invinoveritas. Both are the exact same SHAPE of edge
the format was built to size toward Vertice -- except the v2 taxonomy had no classification that
could ever let either of them count. `vertice_product` was a named special case; everything else
(`vendor`, `external`) was structurally excluded from ever counting, no matter how real or how well
verified. The format didn't just privilege one party's sizing -- it couldn't even express anyone
else's.

Two fixes were on the table. (A) generalize `counts_toward_vertice_split` into an owner-keyed
version, with a `commercial_product` classification carrying an `owner_id`. (B) remove sizing from
the commons format entirely -- attribution and causal provenance only; each surface's own owner
reads the same shared record and applies their own private compensation policy on top. Both Pavlo
and Merlini converged on (B), and it's the right call: sizing is inherently one party's business
logic, and putting it in a commons format is a category error regardless of whose logic it is.

**What changed:**
- `surface.classification` is now `commons` / `commercial_product` / `external` -- no named company
  special case anywhere in the schema. A `commercial_product` surface carries a required `owner_id`
  (Vertice, invinoveritas, ReceiptOS, or any future owner), symmetric by construction.
- `edge-schema.json` no longer defines `counts_toward_vertice_split` or any derivation rule for it.
  The schema records `edge_type` (dependency / verified_application / enabling_provenance),
  `source_entry`, `target`, `edge_verified_by`, and `evidence` -- full stop. Whether any given edge
  counts toward ANY owner's compensation is that owner's own decision, made outside this format.

### Reading edges for your own compensation policy (guidance, not part of the schema)

An owner (Vertice, invinoveritas, or anyone else building a commercial surface on this commons)
computes their own sizing by reading the shared ledger with their own rule -- something like:

```
an edge counts toward OWNER's split iff:
  edge.edge_type == "verified_application"
  AND edge.edge_verified_by is non-empty
  AND edge.evidence carries all three required refs
  AND resolve(edge.target).surface.classification == "commercial_product"
  AND resolve(edge.target).surface.owner_id == OWNER
```

This is deliberately NOT a field in `edge-schema.json` -- it's each owner's own policy, reading
data that's fully public and symmetric. Vertice can apply exactly this rule with `OWNER = "vertice"`
today; invinoveritas could apply the identical rule with `OWNER = "invinoveritas"` tomorrow. Neither
owner's policy is privileged by the format itself.

## The rules this format enforces, and why

1. **`entry_id` is deterministic and content-addressed**, not assigned. Same claim recorded twice,
   byte-identical, necessarily produces the same `entry_id` -- that's intentional signal (a
   duplicate claim), not a collision bug to guard against.
2. **`verified_by` is required and non-empty.** An entry with nobody independently confirming it
   is a self-assertion, not a ledger row.
3. **An actor cannot be the sole `verified_by` for their own claim.**
4. **`type` is one of five, each first-class, none requiring a commit:** `find` / `prove` / `audit`
   / `verify` / `build`.
5. **`surface` is a structured, closed, owner-neutral classification, never inferred or free
   text.** No named company is special-cased in the schema.
6. **`evidence` must give a stranger something to check, not just a claim** -- and must state
   explicitly whether that evidence is actually resolvable by a stranger (`accessibility`).
7. **Causal edges (`edge-schema.json`) are typed, symmetric, and carry no sizing.** `dependency`,
   `verified_application`, `enabling_provenance` are recorded identically as attribution; whether
   any of them counts toward compensation is out of scope for the commons (see above).

## Real examples (`examples.jsonl`, `edges.jsonl`)

Four ledger entries, drawn from actual events the same day this draft was written, not fabricated
for illustration -- all validate cleanly against `schema.json`, including real `entry_id`s computed
with `services/vantage_resolution.py::encode_jcs`:

- Two `find`/`build` entries from the erc-8309.envelope inventory fix (surface: `commercial_product`
  / `invinoveritas`, since that work touched invinoveritas's own product surface -- not excludable
  under v3 the way it was under v2's `vendor` category).
- One `find` entry on a real, live bug (`encode_json_utf8_lf`'s code-point-vs-UTF-16 sort
  divergence), independently reproduced by Merlini before he agreed rather than taken on faith.
- One `verify` entry from a real cross-project interop exchange with safal207
  (Causal-Memory-Layer) on crewAI#4877 (surface: `external`).

**One real edge now exists, restoring what v2 had to remove.** Under v2's identity model, no real
edge example existed because no two entries were properly connected as source/target. Under v3's
owner-neutral surface model, entry 0 (Merlini's `find` -- locating the exact
`golden_set_inventory([])` gap) and entry 1 (babyblueviper1's `build` -- the fix, applied directly
to invinoveritas's own commercial surface) form a genuine `verified_application` edge: Merlini's
discovery was deliberately applied to a specific commercial surface, and the causal link is
independently checkable (the build entry's own claim states it implements exactly the fix Merlini
located). Recorded in `edges.jsonl`, not fabricated -- this is the actual shape of the week's real
work, expressed correctly for the first time now that the taxonomy isn't asymmetric.

**A fifth ledger case, deliberately left OUT -- the format working as designed, not a gap.**
babyblueviper1 posted a reciprocal verification back to safal207 on 2026-08-25T16:20:39Z, a real
claim with real evidence, but safal207 has not yet replied to confirm it. Per rule 2, that means it
does not get a ledger entry yet.

## Open questions for review (not resolved by this draft)

- **Where does this live?** Still explicitly not decided -- `$id` in both schema files stays a
  placeholder.
- **Multi-surface entries** (work that touches both a commons repo and a company's product surface
  in one PR) aren't modeled -- `surface` is a single object, not an array.
- **`verified_by` fully moving to evidence-bearing refs** -- allowed but not required yet.
- **The ledger-level validator work** (from v2.1's review round) is still open: recomputing
  `entry_id` from its own preimage and rejecting a pattern-valid-but-wrong digest; referential
  integrity with UNRESOLVED as its own state; mechanically rejecting `actor == sole verified_by`
  (confirmed this needs real code, not a schema trick); append-only/supersession semantics for
  `verified_by` since it's in the `entry_id` preimage; committing the synthetic pass/fail cases as
  real conformance vectors. Logged to `data/BUILD_QUEUE.md` (invinoveritas repo) as the next real
  build.
- **What operates the reference instance, and where.** Explicitly out of scope for this draft --
  that's the vendor/build lane, a separate conversation once this format itself is settled.
