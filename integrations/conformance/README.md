# Pre-action governance — conformance fixtures

A portable, implementation-independent conformance suite for the pre-action governance receipt model
discussed in [vercel/ai#13215](https://github.com/vercel/ai/issues/13215): a verifier should be able to
confirm, from the **bytes and declared trust inputs alone**, that a consequential agent action was
judged by an independent party and committed before it executed — without calling back to whatever
runtime produced the records.

The suite is **offline and zero-dependency**. The BIP-340 / NIP-01 core is vendored
(`_bip340_nostr.py`, pure stdlib); a second verifier using any correct BIP-340 implementation reaches
the same result.

```bash
python3 run_conformance.py        # asserts every fixture meets the bar (exit 0)
python3 verifier.py fixtures/positive.json fixtures/negative_*.json   # per-fixture detail
```

## The three joined invariants

Recompute the canonical envelope hash **once**, then test three joins against that single byte commitment:

| Suite | What it proves |
|---|---|
| `chain_invariant` | the pre-action and terminal records join on the same envelope hash |
| `admission_invariant` | an **independent identity** signed that same envelope hash before execution |
| `anchoring_invariant` | the commitment was **externally anchored before** the terminal outcome |

The receipt chain proves *what ran*. The admission record proves *a party that isn't the actor*
approved it. The anchor proves *the approval came first*. The three are separable and each fails for
its own reason.

## Fixture layers (what each carries)

- **canonical_envelope**: `raw_input`, `canonicalization` version, `canonical_bytes_utf8`, and the
  `expected_envelope_hash`. The verifier recomputes `sha256(canonical_bytes)` and ignores the declared
  hash except to confirm it.
- **chain**: `pre_action` (action_ref, actor_pubkey, envelope_hash) and `terminal`
  (action_ref, executed_envelope_hash, terminal_outcome_time).
- **admission**: the signed `verdict_event` (a NIP-01 schnorr event), whose content binds
  `artifact_hash == envelope_hash`. Identity is resolved from the event's **own** pubkey, not from any
  self-claim in the content.
- **anchor**: `commitment_digest` (must equal the admission event id), `accepted_anchor_point`
  (a declared trust input — see below), `terminal_outcome_time`, and the OTS `anchor_proof`.
- **trust_policy**: `independent_verifier_pubkeys` — the identities the policy treats as independent.

## Positive + five one-broken-join negatives

The positive fixture passes all three suites end to end. Each negative breaks **exactly one** join and
passes the rest:

| Fixture | Fails | Why |
|---|---|---|
| `positive` | — | chain joins, an independent published key signed the hash, anchored before the outcome |
| `verdict_binding_failed` | admission | valid signature, but over a *different* canonical hash |
| `admission_not_independent` | admission | signer resolves to the actor/executor (self-attested) |
| `key_different_but_identity_unproven` | admission | signer ≠ actor, but not a declared-independent identity (a second self-issued key passes the signature check yet proves no independence) |
| `late_commitment` | anchoring | valid anchor, but accepted *after* the terminal outcome |
| `ordering_unanchored` | anchoring | valid internal chain, no external existence proof at all |

## Provenance (these are real signatures, not mocks)

- The **positive** admission is signed by the live verifier's published secp256k1 key
  (`6786e18a…`); you can confirm it independently by POSTing the event to
  `https://api.babyblueviper.com/verify-proof` (or recomputing NIP-01 + BIP-340 locally with the
  zero-dep `invinoveritas-verify` package). It returns `valid: true`.
- The **identity negatives** carry real, valid schnorr signatures from throwaway keys — the signature
  verifies, the *identity* does not. That is the whole point of `admission_invariant`.

## The anchoring trust root

`accepted_anchor_point` is a **declared trust input** — the deterministic suite tests the *ordering*
relation (anchor point precedes the terminal outcome). Confirming that the anchor point is real (a
Bitcoin block, not a declaration) is the out-of-band step a deployment verifier runs:
`ots verify <commitment>.ots` resolves the block, and the block time is the accepted anchor point.

`fixtures/live_confirmed_anchor.json` is a **real, fully Bitcoin-confirmed** anchored verdict from the
live `/ledger` — real signed event, real `.ots`, real block — so the trust root isn't hypothetical.
The mechanism runs end to end in production; the synthetic fixtures isolate the verifier *logic*.

## Regenerating

`generate_fixtures.py` produces the fixtures (it needs the live signer for the positive fixture's real
signature). The committed fixtures under `fixtures/` are the contract; the verifier and `run_conformance.py`
depend on nothing in this repo beyond the vendored stdlib core.

## License

MIT
