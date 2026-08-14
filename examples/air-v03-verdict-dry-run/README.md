# AIR v0.3-draft-2 — verdict-side `/ledger` dry-run

A runnable dry-run of [crisnovillo1991/agent-receipt-spec](https://github.com/crisnovillo1991/agent-receipt-spec)
**SPEC v0.3 DRAFT 2** (§2.7 verification procedure + §2.8 worked example (1))
against a **real** invinoveritas `/ledger` proof.

This is an example in *this* repo, not a PR against `agent-receipt-spec`.
Draft-2 §6 names the remaining freeze gate in so many words:

> Freeze gate: snapshot side CLOSED (live `/quality` bytes, 17/17,
> post-deploy). Verdict side OPEN: `/ledger` dry-run lands against this
> draft.

That dry-run is this directory.

`spec_version` on anything produced here is `"0.3-draft-2"`. The value
`"0.3"` is reserved for the frozen release.

## What this demonstrates

1. A live `/review`-signed kind-30078 event, fetched from a public relay,
   encoded as an `issuer_signed` binding whose field set matches draft-2
   §2.2 exactly (common core + the artifact-byte conditional set).
2. The six §2.7 steps run mechanically against those real bytes — not
   narrated. Step 3 is a real call to
   `services.proof_signing.verify_proof_event`.
3. The §2.6 three-state authority fixture-flip (`structurally_invalid` /
   `structurally_valid_zero_authority` / `valid_and_authorized`) on the
   `issuer_signed` surface — the named §6 gap ("only `issuer_signed` has
   one today").

It does **not** mint a full AIR receipt, and it does not close the freeze
gate on its own. It lands the verdict-side procedure against the draft
so the gate has a real result to freeze against.

## Artifact

| | |
|---|---|
| Ledger entry | [#62](https://api.babyblueviper.com/ledger/62) |
| Event id | `926831de4d62bdd5facf5aa01e8fceb17dc489f73addee8c695c2c28b7a1c54f` |
| Schema | `invinoveritas.verdict_proof.v1` |
| Verdict | `approve_with_concerns` (conf 0.85) on a proposed AAVE long |
| `decision_ref` | `sha256:b2bbbf7989ec1b673e7a3918e2d60bcfbe514e4ab6ab3c99bcfe2404262fdb3b` |
| Fetched from | `wss://nos.lol` first (REQ-by-id; same pattern as `scripts/ledger_relay_audit.py`) |
| Relays this session | First fetch: nos.lol held, damus.io HTTP 503. Refetch minutes later: nos.lol **and** damus.io both held. primal/wine EOSE-without-event; nostr.band timed out both times. |
| OTS / Bitcoin | confirmed, block **956932**, hash `00000000000000000001262e595dd5f6832d158ffb3c5d342174f55fc99acdb3`, stamped pre-outcome |
| Outcome | cited **proven_right** by [entry #242](https://api.babyblueviper.com/ledger/242) (`source_class=recomputable`, Hyperliquid public fills) |

#62 is the point-in-time verdict. #242 is the later outcome citation —
a different artifact, not mixed into this binding. The OTS stamp is a
`chain_anchored` precedent on the *same* `event_id`; it is referenced
here and deliberately **absent** from the `issuer_signed` object
(draft-2: `anchor` / `locator` on an artifact-byte binding is
non-conforming).

`GET /verdict-proofs/926831de…` 404s — this proof predates the durable
store. Retrieval paths that actually work: the relay, the cached
`fixtures/artifact.json`, and `proof_event` on `GET /ledger/62`.

## Binding (as constructed)

```json
{
  "scheme": "invinoveritas.verdict_proof.v1",
  "decision_ref": "sha256:b2bbbf7989ec1b673e7a3918e2d60bcfbe514e4ab6ab3c99bcfe2404262fdb3b",
  "trust_model": "issuer_signed",
  "authority_ref": "nostr:6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7",
  "authorization_uri": "nostr:926831de4d62bdd5facf5aa01e8fceb17dc489f73addee8c695c2c28b7a1c54f",
  "authorization_sha256": "b1be650f8dfaf50c5f5db7c1127c17022f77855773425707bbcbc1e00eb7ce3c",
  "transport_hint": "relay_event",
  "axes": {
    "precedence": {"field": "created_at"},
    "freshness": null,
    "correctness": null
  }
}
```

Axes match worked example (1): precedence declared, freshness and
correctness present-and-null. The two nulls are load-bearing — a
verdict that cannot say "still holds" or "turned out right" says so
visibly. (The later proven_right citation is a *different* artifact.)

`authorization_sha256` is SHA-256 of RFC 8785 JCS over the seven NIP-01
fields. See "Honest findings" for why that is a choice, not a silent
default.

## §2.7 result (real run, 2026-08-14)

Out-of-band obtain (not a numbered step): 2363 bytes from `wss://nos.lol`,
cached at `fixtures/artifact.json`. Subsequent runs are cache hits.
`--refetch` hits the relay again.

| Step | Name | Result | Real value |
|---|---|---|---|
| 1 | obtain artifact | **PASS** | 2363 bytes already held; `transport_hint=relay_event`; `uri=nostr:926831de…` |
| 2 | `SHA-256(bytes) == authorization_sha256` | **PASS** | declared = recomputed = `b1be650f8dfaf50c5f5db7c1127c17022f77855773425707bbcbc1e00eb7ce3c` |
| 3 | verify per `scheme` | **PASS** | `verify_proof_event()` `valid=True`. checks: `id_integrity`, `signature_valid`, `issued_by_invinoveritas`, `is_proof_event`, `decision_ref_recomputes` all true |
| 4 | axes declaration | **PASS** | `created_at=1783347506` present on the event envelope. `freshness` / `correctness` present-and-null (no field to look up) |
| 5 | coherence table | **N/A** | no `state` field; `axes.freshness` is null. The fresh/stale/unavailable table is a rolling-snapshot rule (§2.5), not a point-in-time one |
| 6 | consumer-judgment | **PASS** (not format-validity) | freshness not declared; anchoring existence N/A (`issuer_signed`). Authority classified against two real policies — see below |

`structural_ok` (steps 1–5): **True**.

Step 5 N/A is a reading of the draft text, not an assumption: §2.7 step 5
is keyed on `state: "fresh" | "stale" | "unavailable"`, and §2.5 requires
that closed vocabulary of **rolling-snapshot** artifacts. A point-in-time
verdict with freshness=null has nothing for the table to apply to.

## issuer_signed three-state fixture (§2.6 / §6)

Identical valid bundle; classification flips solely with the consumer's
trust-policy list. Each result carries the `trust_policy_id` it was
computed against (recomputability rule).

| Bundle | Policy | Classification |
|---|---|---|
| real event, real hash | `air.issuer_signed.v0:accepts-invinoveritas-published-key` (lists `nostr:6786e18a…`) | `valid_and_authorized` |
| same bytes | `air.issuer_signed.v0:excludes-invinoveritas-key` (lists a different key) | `structurally_valid_zero_authority` |
| one hex digit flipped; accepting policy still lists us | same accepting policy | `structurally_invalid` (step 2 digest `44ecad250d96286a6b6f235e343c3108a3ee86ba0bd12d2e20e42e3d1548525f`) |

All three states demonstrated. A listed key cannot rescue a bad hash —
authority is downstream of structure.

## Honest findings

These are real, not padding. An honest partial is worth more here than a
forced 6/6.

1. **`relay_event` has no pinned byte profile in draft-2.**
   `authorization_sha256` attests "the exact bytes I verified." Relay
   JSON is not byte-stable. Against this same event:
   - JCS (what we bound): `b1be650f8dfaf50c5f5db7c1127c17022f77855773425707bbcbc1e00eb7ce3c`
   - `json.dumps(event)` as parsed: `5a89ee6541317cf7723829d443f29fe5d0f7385c3f287685c892b2c9641d3bb0`
   Two honest verifiers fetching the same id from two relays can fail
   step 2 without anyone tampering. Worked example (1) avoids this by
   using `transport_hint: raw_url` against a committed file. We used
   `relay_event` because that is how these bytes actually moved.
   **Resolution path:** pin a canonicalization for `relay_event` (we
   used the same RFC 8785 JCS subset `proof_signing.py` already uses
   for `decision_ref` / `content_sha256`) — or say explicitly that
   `relay_event` bindings SHOULD also publish a `raw_url` copy of the
   hashed bytes. Question for the draft, not an assertion that it is
   already wrong.

2. **`created_at` is producer-held.** Worked example (1) names it as
   the precedence field, so this binding does too. Independent
   precedence for this event is the OTS Bitcoin stamp (block 956932),
   which is a different trust model and was not stuffed into this
   object. The two-null axes declaration is doing its job: this
   binding does not claim the OTS.

3. **Relay availability flickered inside one session.** First fetch:
   nos.lol held, damus.io (listed as holding it on the last ledger
   audit) returned 503. Refetch minutes later: both held. That is a
   transport observation, not a binding failure — and is exactly why
   `authorization_sha256` exists separately from "the issuer published
   this."

4. **`GET /verdict-proofs/{id}` 404s for #62.** Predates the durable
   store. Not a spec problem; named so nobody treats that URL as the
   retrieval pointer.

## Run

From the repo root:

```bash
venv/bin/python -m py_compile \
  examples/air-v03-verdict-dry-run/verdict_binding.py \
  examples/air-v03-verdict-dry-run/verify_dryrun.py \
  examples/air-v03-verdict-dry-run/test_verdict_dryrun.py

# fetch (or reuse cache) + print the binding
venv/bin/python examples/air-v03-verdict-dry-run/verdict_binding.py

# §2.7 steps 1–6 + the three-state fixture, real verify_proof_event()
venv/bin/python examples/air-v03-verdict-dry-run/verify_dryrun.py

# passing path + tamper + zero-authority + fixture-flip
venv/bin/python examples/air-v03-verdict-dry-run/test_verdict_dryrun.py -v
```

`--refetch` on either script hits `wss://nos.lol` again instead of the
cache. Step 1 of the procedure itself never opens a socket: retrieval
is out-of-band, matching §2.7 ("No network access in either case").

## Files

| file | what |
|---|---|
| `verdict_binding.py` | relay fetch, JCS artifact bytes, draft-2 binding builder, shape checker |
| `verify_dryrun.py` | §2.7 steps 1–6, `verify_proof_event()`, three-state fixture-flip |
| `test_verdict_dryrun.py` | real passing path + tampered step 2 + excluding policy + all-three-states |
| `fixtures/artifact.json` | exact hashed bytes (2363-byte JCS of the NIP-01 event) |
| `fixtures/binding.json` | `spec_version: "0.3-draft-2"` envelope + the binding |
| `fixtures/fetch_meta.json` | which relay, when, which others failed |
| `fixtures/trust_policy_*.json` | the two consumer lists the fixture flips across |
| `fixtures/last_dryrun.json` | last `verify_dryrun.py` report |

## Draft reply — crisnovillo1991/agent-receipt-spec#14

*Draft only. Not posted. Independent review before anything goes out.*

---

Draft-2 asked for the verdict-side dry-run against `/ledger`. It ran
against this text, not against a summary of it.

Artifact is ledger [#62](https://api.babyblueviper.com/ledger/62), event
`926831de4d62bdd5facf5aa01e8fceb17dc489f73addee8c695c2c28b7a1c54f`
(`invinoveritas.verdict_proof.v1`, `approve_with_concerns` on a proposed
AAVE long). Fetched live from `wss://nos.lol` by id. Later cited
`proven_right` by [#242](https://api.babyblueviper.com/ledger/242). OTS
confirmed at bitcoin block 956932 on the same `event_id` (referenced,
not folded into the binding — `anchor` on an `issuer_signed` object is
non-conforming under §2.2).

Binding (one `authorizations` element, `spec_version: "0.3-draft-2"`):

```json
{
  "scheme": "invinoveritas.verdict_proof.v1",
  "decision_ref": "sha256:b2bbbf7989ec1b673e7a3918e2d60bcfbe514e4ab6ab3c99bcfe2404262fdb3b",
  "trust_model": "issuer_signed",
  "authority_ref": "nostr:6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7",
  "authorization_uri": "nostr:926831de4d62bdd5facf5aa01e8fceb17dc489f73addee8c695c2c28b7a1c54f",
  "authorization_sha256": "b1be650f8dfaf50c5f5db7c1127c17022f77855773425707bbcbc1e00eb7ce3c",
  "transport_hint": "relay_event",
  "axes": {
    "precedence": {"field": "created_at"},
    "freshness": null,
    "correctness": null
  }
}
```

§2.7 against those bytes:

1. obtain — PASS (2363 bytes held; out-of-band relay fetch, then offline)
2. SHA-256 — PASS (`b1be650f8dfaf50c5f5db7c1127c17022f77855773425707bbcbc1e00eb7ce3c`)
3. scheme — PASS (`verify_proof_event`: id_integrity, signature_valid,
   issued_by_invinoveritas, is_proof_event, decision_ref_recomputes)
4. axes — PASS (`created_at=1783347506` on the envelope; the two nulls
   name no field)
5. coherence table — N/A. Reading of §2.5/§2.7: the table is keyed on
   `state: fresh|stale|unavailable`, which rolling snapshots must carry
   and point-in-time verdicts with `freshness: null` do not. Confirm or
   correct this reading if the table was meant to fire on the absence
   of `state` as well.
6. consumer-judgment — authority only (freshness null; not
   `chain_anchored`). Same bundle, two policies:
   - lists our published key → `valid_and_authorized`
   - lists a different key → `structurally_valid_zero_authority`
   One hex digit flipped, accepting policy still lists us →
   `structurally_invalid` (recomputed digest
   `44ecad250d96286a6b6f235e343c3108a3ee86ba0bd12d2e20e42e3d1548525f`).
   That is the issuer_signed fixture §6 said was the only one on the
   board; it now has a live `/ledger` bundle underneath it, not just
   the earlier constructed one.

One finding that is not a clean pass, and is more useful than one.

`authorization_sha256` is "the exact bytes I verified." For
`transport_hint: relay_event` draft-2 does not pin a serialization.
Against this event, JCS of the seven NIP-01 fields hashes to
`b1be650f…`; `json.dumps` of the parsed object hashes to `5a89ee65…`.
A second verifier who fetched the same id and hashed the relay's JSON
as received would fail step 2 with no tamper and no signing failure —
the failure mode §2.3 exists to isolate, manufactured by transport
serialization. Worked example (1) sidesteps it via `raw_url` against a
committed file. Does draft-2 want a canonicalization for `relay_event`
(we used the RFC 8785 JCS subset already in `content_sha256` /
`decision_ref`), or a rule that a `relay_event` binding also publish a
`raw_url` of the hashed bytes? Either closes it; leaving it unstated
leaves step 2 relay-implementation-defined.

Runnable copy is in our tree at
`examples/air-v03-verdict-dry-run/` (binding builder, §2.7 runner,
tamper + zero-authority tests). Happy to land a vector against the
spec repo in whatever shape you want it, including a negative for
"two serializations of the same event, one hash."

---

*End of draft reply.*
