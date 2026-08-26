# Trusty (TAWG) → attribution-ledger adapter — draft mapping

Drafted 2026-08-26 following the damon:general thread (msgs 3376-3382): Pavlo checked Trusty's
actual data model and confirmed it lacks a mechanical `verified_by` equivalent; this maps every
field precisely, grounded in the real source (`trustless-ai/tawg-daily-contribution`, read
directly — `knowledge/meta/claim-ledger.json`, `knowledge/meta/source-ledger.json`,
`src/tawg_bot/ledger.py`, `src/tawg_bot/github_source.py`), not inferred from the thread alone.

**Status: draft for the group to react to, not a commitment on Trusty's side.** Same posture as
the ledger itself — a proposal, reviewed not dictated.

## 1. What Trusty actually tracks today (real field names)

Two separate ledgers, `tawg.claim-ledger.v2` and `tawg.source-ledger.v2`
(`src/tawg_bot/ledger.py::ClaimAssessmentV2` / `SourceEvidenceV2`):

```
ClaimAssessmentV2:  claim_id, claim_kind, state, risk, source_keys[], assessed_at
SourceEvidenceV2:   source_key, source_kind, authority, canonical_url,
                    observed_version, observed_sha256, observed_at,
                    independence_key, active
```

`claim_kind` ∈ {ordinary, normative, implementation, status, discussion}.
`state` ∈ {accepted, provisional, contested, unsupported, deprecated}.
`EvidenceLedger.validate_claim()` requires an ACCEPTED claim to have >=1 (ordinary risk) or >=2
(high risk) sources with **distinct `independence_key` values**, each `source_kind` matching the
claim's kind (normative claims need a normative-spec source, implementation claims need an
implementation/test/example source, etc). This is real, working logic -- it answers "is this
claim backed by enough independent DOCUMENTS," which is a genuinely different question from "did
another PARTICIPANT confirm this specific claim is true."

Separately, real per-event actor attribution DOES exist in Trusty's system, one layer up
(`src/tawg_bot/github_source.py` pulls real GitHub `author.login` off every commit/PR/review/
comment it ingests). It just never reaches the two ledgers above -- those track evidence and
claims, not who authored the underlying GitHub activity. So the "actor" gap isn't that Trusty has
no attribution data at all; it's that the claim/source ledgers and the raw event stream are two
separate parts of Trusty that haven't been joined yet.

## 2. The real gap, restated precisely (Pavlo's point, with field names)

`independence_key` measures **source diversity** (2+ different origins back this claim). It does
not measure **claim verification** (a specific other person/agent checked THIS claim and confirms
it). Nothing in `ClaimAssessmentV2` records "who reviewed this and agreed" -- `source_keys`
already existing and being independent is not the same as someone looking at the claim and saying
yes. This is exactly the ledger's own `actor != sole verified_by` discipline, applied to Trusty's
shape: today, Trusty could mark a claim ACCEPTED entirely on its own source-matching logic, with
zero human/agent participant ever having reviewed the specific claim text.

## 3. Field mapping

| ledger field | source | notes |
|---|---|---|
| `claim` | **not currently in either ledger** -- lives as prose in Trusty's daily catch-up synthesis (`src/tawg_bot/daily.py`), not attached to a `claim_id`. Adapter needs the specific claim sentence Trusty already generates, keyed to the `claim_id` it's about. | Real gap #1 -- Trusty's ledgers store claim METADATA (kind/state/sources), not the claim's own text. |
| `actor` | `github_source.py`'s per-event `author` (GitHub login), joined by whichever `source_key`/commit underlies the claim. | Real gap #2 -- exists in Trusty already, just not joined to `ClaimAssessmentV2`. Needs `source_keys` -> underlying GitHub event -> `author` lookup. |
| `verified_by` | **does not exist yet.** Needs a new field on `ClaimAssessmentV2` (or a sibling structure) recording which participant(s) reviewed and confirmed this SPECIFIC claim -- distinct from `source_keys`/`independence_key`. | Real gap #3, the one Pavlo named directly. This is the actual new mechanism to build, not a mapping. |
| `timestamp` | `assessed_at` (claim) or `observed_at` (source), whichever the entry is really about. | Clean, direct. |
| `surface` | Not in either ledger -- inferable from `source_key`/`canonical_url` (e.g. `github.com/trustless-ai/*` → `classification: "commons"`, `identifier` = repo name). External repos would map to `external`. No `commercial_product` case seen yet in this data (all sampled entries are trustless-ai's own repos or canonical ERC specs). | Derivable, needs a real per-repo mapping table, not guesswork per entry. |
| `type` | **different axis from `claim_kind`, not a 1:1 map.** `claim_kind` answers "what kind of claim is this" (normative/implementation/status/discussion); the ledger's `type` answers "what kind of contribution act produced it" (find/prove/audit/verify/build). A `claim_kind=implementation` claim could be the result of a `build` (someone wrote the code) or a `verify` (someone confirmed existing code matches spec) -- `claim_kind` alone can't tell you which. Needs deriving from the underlying GitHub event type (a new commit → `build`; a review comment catching an issue → `find` or `audit`; a re-run confirming someone else's claim → `verify`), same join as `actor`. | Real gap #4 -- needs the event-type join, not a lookup table on `claim_kind` alone. |
| `evidence.url` | `canonical_url` | Clean, direct. |
| `evidence.hash` | `observed_sha256` | Clean, direct -- already a real sha256, already pinned to a specific observed version. |
| `evidence.commit` | Not always populable -- `canonical_url` sometimes points at a file path (blob URL), not a commit. Populate when the underlying GitHub event carries a real commit SHA; leave absent otherwise (the schema already allows `url` alone to satisfy the `anyOf`). | Direct when available. |
| `entry_id` | Computed fresh by the adapter once the above are populated -- `sha256("sha256:" + hex(sha256(JCS(entry minus entry_id))))`, same construction as the rest of the ledger, reusing `services/vantage_resolution.py::encode_jcs`. | Not read from Trusty at all -- this is the ledger's own content-addressing, computed on the ledger side. |

## 4. What this means concretely, in order

1. **Cheap, no new Trusty mechanism needed:** `evidence.url`/`evidence.hash`/`timestamp` map
   directly today. A read-only adapter script could emit partial ledger entries (missing `actor`,
   `verified_by`, `type`) from the existing two ledgers alone, right now.
2. **Needs a join, not a new field:** `actor` and `type` need the adapter to cross-reference
   `source_keys`/`claim_id` back to the raw GitHub event Trusty already ingested
   (`github_source.py`'s output) to recover the real author and event shape. This is real work
   but doesn't require changing Trusty's own data model.
3. **Needs a real new mechanism on Trusty's side:** `verified_by` and `claim` (the sentence, not
   just the id) don't exist as structured data anywhere in Trusty today. This is the actual design
   decision the group needs to make -- not "how do we map field X to field Y" but "how does Trusty
   record that a specific claim was reviewed by a specific other participant, distinct from its own
   source-independence check."

## 5. Open question for the group

Should `verified_by` on Trusty's side be: (a) a new field on `ClaimAssessmentV2` populated when a
group member replies confirming a specific claim (parsed from Telegram/GitHub the same way
`github_source.py` already parses events), or (b) kept entirely out of Trusty and handled as a
separate, later manual/adapter-side annotation step when a candidate entry gets promoted to a real
ledger entry? Leaning toward (a) since Trusty already ingests the exact reply text this would come
from -- but that's the group's design call, not this doc's.

Not proposing this get built yet -- posting it as the concrete "here's exactly what maps and what
doesn't" artifact requested in the thread, so the vocabulary/evidence/validation discussion has
real field names to react to instead of a hypothetical shape.
