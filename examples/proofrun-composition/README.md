# Composing ProofRun with invinoveritas /review

Built in response to [yebiguo/ProofRun#12](https://github.com/yebiguo/ProofRun/issues/12) — a
real question about whether remote/third-party attestation is a gap in ProofRun. yebiguo's
answer was clear and correct: it's a deliberate non-goal, not an oversight. ProofRun proves
*what ran and against what exact code* (re-executable, offline, zero network calls by design).
A judgment call like invinoveritas's `/review` proves *someone/something independent looked and
formed an opinion* — a reputation-based claim, not a re-derivable one. Bolting the second onto
the first would make "ProofRun says PASS" mean something mushier than it does now.

His invitation: "two legs, composing without either side needing to know about the other... if
you build the glue on your end, I'd genuinely like to see it." This is that glue — and it's
built from two REAL calls, not a mocked-up illustration.

## What's here

A tiny fee-cap function (`fixtures/fee_cap.py`), three tests, and two independent artifacts about
the exact same commit:

1. **`fixtures/proofrun_receipt.json`** — a real receipt from running `proofrun run test --
   pytest tests/` (ProofRun v0.3.0, downloaded from its own GitHub release, run locally, zero
   network calls). Binds `status: pass` to git commit `54f9671` via an HMAC signature.

2. **`fixtures/review_proof_signed.json`** — a real, signed `/review` verdict on the same file
   (`POST /review {"sign": true}`), independently verified via `POST /verify-proof`
   (`fixtures/verify_proof_response.json`, `valid: true`, `decision_ref_recomputes: true`) —
   schnorr-signature-checkable offline, no trust in invinoveritas required to confirm the
   platform issued it unaltered.

3. **`fixtures/composed_evidence.json`** — the actual glue: a small file that references both
   by hash/signature, with no coupling between the two tools. ProofRun never calls invinoveritas.
   invinoveritas never calls ProofRun. Composition happens entirely at the evidence layer.

## The interesting part: they disagree

All 3 tests pass. ProofRun correctly says so. But `/review` rejected the code at 0.98 confidence
— `max_fee_pct` is never validated, so a negative value (e.g. from a misconfigured caller)
produces a **negative fee**, which in a real withdrawal backend could mean crediting a user
instead of charging them. None of the three tests exercise that input at all.

This is the concrete case for composing both legs rather than picking one: "tests pass" and "this
is safe" are different claims, and here they point in opposite directions. A single green
checkmark from either tool alone would have hidden that gap.

## Reproducing this yourself

```bash
# Execution-binding leg (ProofRun, offline)
curl -L https://github.com/yebiguo/proofrun/releases/download/v0.3.0/proofrun_linux_amd64.tar.gz | tar xz
./proofrun run test -- python3 -m pytest fixtures/ -q
cat .proofrun/receipt.json

# Judgment leg (invinoveritas /review, signed)
curl -X POST https://api.babyblueviper.com/review \
  -H "Authorization: Bearer <your-key>" -H "Content-Type: application/json" \
  -d '{"artifact": "<contents of fee_cap.py>", "artifact_type": "code_diff", "sign": true}'

# Verify the /review proof independently, no trust required
curl -X POST https://api.babyblueviper.com/verify-proof \
  -H "Content-Type: application/json" -d '{"event": <the "event" object from the proof above>}'
```

Neither call needs the other to exist. That's the whole point.
