# Article 12 worked example — NOMOS authority-gate + invinoveritas /review

A joint pair with Allan Sendagi (SafeHaven/NOMOS) — **both halves shipped**
as of 2026-08-15.

Article 12 of the EU AI Act requires human oversight to be **real and
specific to this action**, not a standing org-level sign-off somewhere in
the handbook. Two independently recomputable attestations can sit on the
same underlying transfer and answer **different questions**:

| Layer | Who | Question | Status |
|---|---|---|---|
| Authority-gate | NOMOS / `.nomos` | Did a named human review and authorize **this** transfer (amount, counterparty, timestamp) under the cited policy? | Shipped — [nomos-spec/interoperability-examples](https://github.com/nomos-spec/interoperability-examples/tree/main/examples/article12-fund-transfer), independently verified below |
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
a `.nomos` fingerprint. Allan's digest is computed by NOMOS's own
canonicalizer over his artifact; composition is "two seals, one underlying
transfer," not "we computed his hash for him."

**Two valid binding points, not one — worth naming precisely (found
2026-08-15, checking Allan's shipped fixture).** This folder actually
publishes TWO different hashes over the same underlying case, and this
README originally only headlined one of them as "the" fingerprint, which
briefly read like a mismatch when cross-checking Allan's artifact:

| Hash | What it's over | Where it lives |
|---|---|---|
| `artifact_fingerprint` = `sha256:8879...0265e` | The raw `synthetic_fund_transfer_artifact.json`, canonicalized (`canonicalize.py`: sorted keys, `separators=(',',':')`, no floats) | `artifact_fingerprint.txt` |
| `artifact_hash` = `sha256:4ea0...bede36` | The SAME fixture, rendered as the `/review` call's input text and embedded inside the signed verdict proof event | `review_response.json`'s `proof.event.content.artifact_hash` |

Both are real, both independently recomputable, both trace to the same
`underlying_transfer_id`. Allan's `.nomos` fixture binds to `artifact_hash`
(the one embedded in our *signed* proof event) rather than
`artifact_fingerprint.txt` (a static local file) — arguably the stronger
anchor of the two, since it's inside a schnorr-signed, independently
verifiable event rather than something either party could quietly edit on
disk. Naming this explicitly so a future verifier checking either binding
knows both are legitimate and point at the same case, rather than treating
a mismatch against just one of them as an error.

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

## Both halves, verified independently (2026-08-15)

Allan's NOMOS authority-gate fixture shipped:
[`nomos-spec/interoperability-examples/examples/article12-fund-transfer`](https://github.com/nomos-spec/interoperability-examples/tree/main/examples/article12-fund-transfer).
Verdict: **ESCALATE** (no named human authorized this specific amount/
counterparty/timestamp) — the mirror-image result to our `/review`
**REJECT**, exactly as the two-question framing above predicts: neither
system answers the other's question, both fire on the same underlying
case.

Independently re-verified myself, not just trusted the description:

```bash
git clone https://github.com/nomos-spec/interoperability-examples.git
cd interoperability-examples/examples/article12-fund-transfer
node ../../scripts/verify-nomos.mjs article12-fixture.nomos \
  --pubkey article12-fixture.pubkey.pem
```

```
[OK] Payload hash matches: c3850804ffbc3dee…
[OK] Ed25519 signature verified against published key (no secret, no server call)
Result: VALID
```

Both attestations are now sitting side by side on one underlying
transfer, sealed by two independent parties, neither derived from the
other, both offline-verifiable by anyone. That's the pair.

**Real next milestone (Allan's own framing, and it lines up with our own
`vantage_limitation` field):** the NOMOS-SPEC-002 agent runtime guard is
*declared* in his artifact as the pre-action mediation layer our
`vantage_limitation` field says a proof needs before it's more than
advisory input for an irreversible action — but that guard's current
default is advisory and this exercise didn't run it. Turning that from a
declared capability into a demonstrated block (a live, still-synthetic
agent action actually intercepted and escalated) is the natural next
build, not a new idea — open on our side.
