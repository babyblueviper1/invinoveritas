# Article 12 worked example — NOMOS authority-gate + invinoveritas /review

A joint, half-finished pair with Allan Sendagi (SafeHaven/NOMOS).

Article 12 of the EU AI Act requires human oversight to be **real and
specific to this action**, not a standing org-level sign-off somewhere in
the handbook. Two independently recomputable attestations can sit on the
same underlying transfer and answer **different questions**:

| Layer | Who | Question | Status |
|---|---|---|---|
| Authority-gate | NOMOS / `.nomos` | Did a named human review and authorize **this** transfer (amount, counterparty, timestamp) under the cited policy? | Waiting on Allan's fixture |
| Judgment | invinoveritas `/review` | Given the stated facts, is the transfer itself a reasonable action? | This folder — signed, independently verified |

Those are not the same claim. A fully-authorized-but-bad transfer is in
scope for `/review` and structurally out of scope for the authority-gate.
A reasonable transfer that nobody authorized is the reverse. Article 12
needs both.

Allan confirmed (2026-08-15) the technical property that makes this
composable: a `.nomos` fingerprint is computed **before** later
attestations and is independent of them. A second party's signed judgment
can attach to the same artifact without changing the original fingerprint.
Canonical serialization is locked down (one standard representation;
field order / spacing / formatting cannot change the digest). A standalone
NOMOS verifier exists independent of their server.

He has not sent a `.nomos` fixture yet. Our side does not wait on that.

## The case

`treasury-agent-7` (synthetic) proposes an irreversible **USD 87,450**
transfer — above a **USD 50,000** human-authorization threshold — to a
**first-seen** counterparty, citing a weekend cutoff and a 2% late fee,
on an on-chain USDC rail, with **no invoice bytes attached**. Identifiers
are obviously fictional. No real money, no real legal entity, no real
account.

The odd amount, the urgency framing, the new counterparty, the SOP cited
for a first payment, and the ACH-ref vs on-chain-address split are
intentional. A rubber-stamp-obvious case would not exercise either layer.

`underlying_transfer_id` is `synth-art12-transfer-2026-08-15-87450`.
Allan's `.nomos` fixture for this case should name that same id (or bind
to `artifact_fingerprint.txt`) so both attestations compose on one
transfer.

## How the fingerprint works

```
synthetic_fund_transfer_artifact.json
        │
        ▼
canonicalize.py     sorted keys, separators=(',',':'), no floats
        │
        ▼
sha256(canonical UTF-8 bytes)     = OUR artifact_fingerprint
        │
        ├── our /review proof attaches to a text rendering of THE SAME fixture
        └── a future .nomos authority-gate seal attaches to the SAME transfer
            without entering this hash
```

`canonicalize.py --self-test` checks two things: reordering keys does not
change the digest, and pretty-printed JSON is a *different* digest (so the
lock is real, not a no-op).

This fingerprint is **ours** over the synthetic transfer record. It is not
a `.nomos` fingerprint. When Allan's fixture arrives, his digest is
computed by NOMOS's own canonicalizer over his artifact; composition is
"two seals, one underlying transfer," not "we computed his hash for him."

## Reproduce

From this directory, repo venv, local API on `127.0.0.1:8000`,
`HL_REVIEW_BEARER` in `../../.env.hl` (same key
`scripts/discretionary_log.py` uses):

```bash
python3 canonicalize.py --self-test
python3 run_review.py
python3 verify_review.py
```

`run_review.py` POSTs `/review` with `artifact_type=onchain_action`,
`sign=true`, `seed=true`, `severity_threshold=all`. `seed=true` is
required: this is fleet dogfood / a published demo, not external paid
demand (`proofs_seeded` vs `proofs_issued`).

`verify_review.py` POSTs the returned `proof.event` to `/verify-proof`
(free, no auth) so the schnorr check runs against the published key
instead of trusting `/review`'s self-report.

## Live result (this run)

Ran 2026-08-15 against `http://127.0.0.1:8000` (not mocked).

| | |
|---|---|
| `artifact_fingerprint` | `sha256:88794f5586b8fe3855c0a8f53fe1c6bfc0c78d6a629acd331fc4a7eb1be0265e` |
| `/review` verdict | **reject** (confidence 0.99) |
| `decision_ref` | `sha256:2f94acc012cda07f7e0e378932eb26547a33ab89a049ed7d046326c91ddd66ce` |
| proof event id | `c1770ea52ff7b90bb6ac0f8b8d4d60d8c7c81e607ef09c1b9279fb60d873856a` |
| signer | published key `6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7` |
| `/verify-proof` | `valid: true` (id_integrity, signature_valid, issued_by_invinoveritas, decision_ref_recomputes) |

Summary from `/review`: do not authorize — the transfer is above the Article 12 threshold with no named action-specific human authorization, and the on-chain destination is not shown to be the same party as the listed ACH ref.

Auth note: `HL_REVIEW_BEARER` (`h1_review`) returned **402** (55 sats on the account, 273 required). The live call was retried once with `OPERATOR_FULL_API_KEY` (also `is_internal`). That fallback is recorded as `auth_used` in `review_response.json`. `seed=true` on localhost still counts this as `proofs_seeded`.

Committed outputs:

| file | what |
|---|---|
| `synthetic_fund_transfer_artifact.json` | the transfer |
| `artifact_fingerprint.txt` | `sha256:…` of the canonical bytes |
| `review_response.json` | full `/review` body plus the request we sent |
| `verify_proof_response.json` | independent `/verify-proof` result |

## Waiting on

Allan Sendagi / SafeHaven / NOMOS: a `.nomos` fixture for **this same**
synthetic transfer (`underlying_transfer_id` above, or an explicit bind
to `artifact_fingerprint.txt`) recording whether a named human authorized
it under `AI-ACT-ART12-v1`. Once that file is here, a third script can
verify his seal with the standalone NOMOS verifier and sit both
attestations next to each other without either party trusting the other.

Until then this folder is half of the pair, published as such.
