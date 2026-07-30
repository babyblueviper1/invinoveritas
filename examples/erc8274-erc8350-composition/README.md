# ERC-8274 x ERC-8350 composition — worked example

A verifier switch (an ERC-8274 `AgentVerifiable` deployment rotating its verification
backend — TEE to zkML, key rotation, model version bump) is itself a decision that
needs a checkable "why", not just a bare `(old, new)` address pair.

Converges two independently-arrived-at ideas:
- JimmyShi22 (ERC-8274 author), [ethereum-magicians.org/t/29098/7](https://ethereum-magicians.org/t/29098/7):
  proposed `AgentVerifierUpdated(bytes32 transitionId)` as an alternative event, wired
  to ERC-8350's `transitionId` so a consumer who sees the `bytes32` variant "knows
  where to find the full story."
- everest-an (ERC-8350 author), [ethereum-magicians.org/t/25098/342](https://ethereum-magicians.org/t/25098/342):
  `provenanceCommitment` carrying "a recomputable reference to the why... a stronger
  claim than a free-text reason precisely because the reader does not have to trust
  the switcher's own account of it."

## What this actually builds

1. A real, live, signed invinoveritas `/review(sign=true)` verdict — a genuine
   judgment call about whether a specific verifier switch is sound — as the "why."
2. `provenanceBytes` = that verdict's proof, canonicalized (JCS).
3. `provenanceCommitment`, computed exactly per ERC-8350's own commitment-domain
   formula.
4. A full `ExperienceDelta` struct, and `transitionId` computed exactly per
   ERC-8350's own Transition ID formula — independently verified against
   ERC-8350's own `test-vectors-v1.json` (typehash, transitionId, nextStateRoot all
   matched byte-for-byte) *before* this script was written on top of it.
5. The ERC-8274 side's `AgentVerifierUpdated(transitionId)` event data — no contract
   deployed; this computes the exact bytes a real deployment would emit, from the two
   ERCs' own published formulas, so anyone can reproduce it cold.

## Independently verifiable on both sides

- **Our half** (the verdict): a real NIP-01 event, BIP-340 Schnorr signed. POST
  `output.json`'s `_verdict_proof_full.event` to
  `https://api.babyblueviper.com/verify-proof` (free, no auth), or recompute the NIP-01
  event id + signature yourself.
- **Their half** (the ERC-8350 math): pure functions of public bytes. Run
  `compose_and_verify.py --verify` — it recomputes `transitionId`,
  `provenanceCommitment`, and `nextStateRoot` from scratch using ONLY
  `output.json`'s own fields, no trust in the script's prior run required.

## Run it

```bash
# Build fresh (needs an invinoveritas API key with balance — real /review call, ~270 sats)
venv/bin/python3 compose_and_verify.py --api-key ivv_...

# Verify a saved output.json only (no new API call, no trust in the prior run)
venv/bin/python3 compose_and_verify.py --verify
```

`output.json` in this directory is a real, live artifact from an actual run — not a
mock. Re-run `--verify` on it any time; the numbers should always reproduce.

## The registry field (added 2026-07-30, everest-an, t/29098/15)

`spaceId` is deliberately chain-free (t/29098/14): one identity across chains, so the
same `spaceId` can carry genuinely different histories on different chains. That makes
`(spaceId, transitionId)` insufficient to locate a specific history — a verifier switch
is exactly the case where the reference needs to resolve unambiguously. `registry` is
carried alongside both sides' output for this reason: `(registry, spaceId, transitionId)`
is the actual locating tuple. It's a pure annotation, not a hash input — dropping or
changing it does not affect `transitionId`/`provenanceCommitment` at all, which is why
`verify_erc8350_math()` checks it separately (`registry_present_and_agrees`) rather than
folding it into the cryptographic checks. Reuses everest-an's own real, live Sepolia
ERC-8350 registry deployment (`0xDdf21937ba80b5fF973610877A0955b320C91241`, the same one
in `examples/erc-8337-attestation-refs/sepolia-fixture-v1.json`) rather than a synthetic
placeholder.
