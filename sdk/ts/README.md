# invinoveritas-verify

**Verify before you pay.** Primitives that make peer verification a *default* in x402 / agent-to-agent commerce — the way browsers made "Not Secure" a warning until HTTPS was table-stakes. Verify a proof **online** (one call to the verifier) or **fully offline** (recompute it yourself, trusting no one — not even us).

```bash
npm install invinoveritas-verify
```

```js
import { preflightVerify, verifyAttachedProof } from "invinoveritas-verify";

// Before paying an x402 provider, check it carries a VERIFIABLE track record:
const rep = await preflightVerify("https://some-agent-service.example");
if (rep.recommend === "caution") {
  console.warn(rep.trustFlag);        // "⚠ no verifiable track record" — trusting on assertion alone
} else {
  console.log(rep.trustFlag, rep.trackRecord);  // "✓ verifiable track record" {entries, wins, losses, ...}
}
// preflightVerify(url, { require: true }) hard-gates a pay flow: throws on an unverifiable provider.

// When an agent attaches a signed verdict proof to its output, confirm it's authentic
// WITHOUT trusting the presenter (free, no-auth schnorr check against the published key):
const res = await verifyAttachedProof(proofEvent, { expectedPubkey: "<their published key>" });
if (!res.valid) throw new Error("unverifiable output");   // valid-but-wrong-signer is caught too

// Or verify the SAME proof OFFLINE — no network, no API, no trust in us. Recomputes the NIP-01 event
// id + BIP-340 schnorr signature against the published key on your machine. Byte-identical verdict.
import { verifyProofLocal } from "invinoveritas-verify";
const local = verifyProofLocal(proofEvent);   // { valid, checks: { id_integrity, signature_valid, issued_by_invinoveritas, is_proof_event } }
if (!local.valid) throw new Error("proof did not verify locally");
```

> **Online vs offline.** `verifyAttachedProof` is the convenient path (one call to the verifier).
> `verifyProofLocal` is the *trustless* path — it computes the same four checks yourself, so you depend
> on neither our uptime nor our honesty. That's "recomputable, not a score" in your hands.

## What it reads

A provider advertises a verifiable track record via the [x402-signals](https://github.com/sF1nX/x402-signals) `verification` block on its `/.well-known/x402` (or the `X-Verification-Handshake` response header):

```json
"verification": {
  "scheme": "verdict-proof.v1",
  "verify_endpoint": "https://provider/verify-proof",
  "track_record": "https://provider/ledger",
  "pubkey": "<key every entry/proof verifies against>",
  "recompute": "verify each entry's signature against pubkey; outcomes settle where the issuer can't edit them; wins AND losses both published."
}
```

`preflightVerify` reads it and summarizes the record; `verifyAttachedProof` checks a proof against the verifier's `/verify-proof` (free, no-auth) and rejects a valid signature from the wrong signer. The norm both ways: **demand a proof on what you receive, attach one to what you ship.**

Live reference provider (serves the block + header + `/verify-proof` + a public `/ledger`): `https://api.babyblueviper.com`.

## API

- `preflightVerify(url, { require?, timeout? })` → `VerificationReport` (`{ hasSignal, trustFlag, recommend, pubkey, trackRecord, ok, ... }`)
- `verifyAttachedProof(proof, { verifyEndpoint?, expectedPubkey?, timeout? })` → `{ valid, ... }` (online)
- `verifyProofLocal(proof, { expectedPubkey? })` → `{ valid, checks{...}, issued_by_invinoveritas, ... }` (offline, no network)
- `discoverVerification(url, timeout?)` → the raw verification block or `null`
- `nostrEventId(event)` → recompute a signed event's canonical NIP-01 id
- `PUBLISHED_PUBKEY` → the reference verifier's key (re-derive: `GET /.well-known/agent-handshake`)

Node 18+ / browsers / workers. The online primitives use global `fetch`; `verifyProofLocal` uses [`@noble/curves`](https://github.com/paulmillr/noble-curves) (audited) for the schnorr check. Ships typed (`index.d.ts`). MIT.
