# elizaos-plugin-invinoveritas

An [elizaOS](https://elizaos.ai) plugin that gives your agent **an automated, independent second
opinion on a high-stakes action** — and free, recomputable proof verification. Fully autonomous: the
**agent** calls it, weighs the verdict, and decides — **no human in the loop**, it never blocks and
never waits on approval. The independent check on another agent's output that an agent **can't
self-issue** (you can't issue a trustworthy verdict on your own work).

```bash
npm install elizaos-plugin-invinoveritas
```

```ts
import { invinoveritasPlugin } from "elizaos-plugin-invinoveritas";

const character = {
  name: "MyAgent",
  plugins: [invinoveritasPlugin],
  settings: {
    secrets: { INVINO_API_KEY: "ivv_..." }, // free: POST https://api.babyblueviper.com/register
  },
};
```

## Actions
- **`VERIFY_BEFORE_ACTING`** — an independent verdict before any irreversible step. `options.artifactType: "trade"` → capital-scale-aware risk review; `"onchain_action"` → deterministic scam/drainer/approval/poisoning checks. Returns `approve | approve_with_concerns | reject` + summary + issues; `options.sign: true` attaches a recomputable signed proof. Advisory — degrades to `review_unavailable`, never blocks.
- **`VERIFY_PROOF`** — verification of a signed proof another agent handed you (the receiving half of the trust handshake). Pass the full `event` object and it's verified **100% locally** (BIP-340 schnorr recompute via `invinoveritas-verify`, zero network calls — genuinely trustless, not just described that way). Pass only a `proofId` and it fetches the exact bytes first, then verifies them the same way locally; the response's `method` field (`local` vs `fetched_then_local`) always tells you honestly which path ran.

## Why this, not a generic reasoning-verifier
- **Recomputable proof, not a trust-us score** — `sign: true` returns a verdict anyone re-derives from public data (NIP-01 + BIP-340 vs a published key).
- **A public, Bitcoin-anchored track record** (`/ledger`) of being right — wins *and* losses.
- **Committed before the outcome** it's graded against (anti-back-dating).
- **Specialized** for trades + on-chain actions, not generic claim-checking.
- **Free** verification of proofs you receive — one action a single-verdict plugin doesn't give you.

The principle, both ways: **demand a proof on what you receive; attach one to what you ship.**

Setup for every client: https://api.babyblueviper.com/install · Track record: https://api.babyblueviper.com/ledger · MIT licensed.
