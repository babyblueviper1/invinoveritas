# invinoveritas verdict gate for `@qbtlabs/x402`

*An independent integration example. It isn't affiliated with or endorsed by QBT Labs. [`@qbtlabs/x402`](https://github.com/QBT-Labs/x402) is MIT-licensed.*

`@qbtlabs/x402` already puts a policy engine in front of the signature (caps, allowlists, an isolated signer) and an
audit log behind it. This example adds one thing an operator can't self-issue: an **independent, signed verdict
bound to the exact EIP-3009 payment fields before the key signs**, plus a check after settlement that the
settled transfer carried that verdict (the EIP-3009 nonce is the verdict's `decision_ref`).

- `src/verdict/`: the module (TypeScript, ESM). It needs no new dependencies, using the `@noble/*` and `viem` already in `@qbtlabs/x402`.
- `src/__tests__/verdict.test.ts`: 33 tests on real recorded verdicts and the real Base settlement
  [0x2afb35e2…c4a7](https://basescan.org/tx/0x2afb35e24a20fdee74c35937feb59b86358d45c8029a91d065d59825c3e7c4a7). No network.
- `patch/0001-*.patch`: the same change as one commit against `QBT-Labs/x402@f736392`. It also adds an optional `preSign`
  hook to the isolated signer, which runs after `PolicyEngine.check()` and before the vault decrypts, and a `./verdict` package export.

```sh
git clone https://github.com/QBT-Labs/x402 && cd x402 && git checkout f736392
git am /path/to/patch/0001-*.patch && npm ci && npm test   # 253 passed, 18 skipped
```

---

Optional module. Nothing in `@qbtlabs/x402` calls it unless you pass a gate in.

Your policy engine answers *is this payment inside my rules?* (caps, allowlists, chains). This module adds a second
question your own process can't answer about itself: *does an independent reviewer, looking at this exact payment,
sign off on it?* It also leaves a record that a third party can check later without trusting you or the reviewer.

## What it does

**Before signing**
1. Fix every EIP-3009 field except the nonce: `from`, `to`, `value`, `validAfter`, `validBefore`, token, chain.
2. Send exactly those fields to invinoveritas `POST /review` (`artifact_type: onchain_action`, `sign: true`, `action_binding.args`).
3. Verify the returned proof **offline**: BIP-340 signature, pinned issuer key, NIP-01 id, `decision_ref` recompute,
   `sha256(JCS(args))` equal to the bound args hash, and the tool hash. It uses `@noble/curves` and `@noble/hashes`, which this package already depends on.
4. Allow only if the verdict is in `proceedOn` and younger than `maxVerdictAgeSeconds`. The nonce to sign with is the
   verdict's `decision_ref`, so the authorization can't predate the verdict.

**After settlement**
5. `gate.verifyExecution(decision, txHash)` checks the chain: USDC's `AuthorizationUsed(authorizer, nonce)` log carries
   the verdict's `decision_ref`, and the `Transfer` matches the bound payer, recipient and amount. This runs offline over an RPC
   receipt (`{ rpcUrl }`), or through the free `POST /verify-execution` endpoint.

**Fail modes**: `failMode: 'closed'` (the default) blocks when the reviewer is unreachable. `'open'` allows and flags
`failOpen: true`. A proof that fails verification **always** blocks: a bad proof is a finding, not an outage.

## Integration (client side)

```ts
import { createVerdictGate, createVerdictPaymentFetch } from '@qbtlabs/x402/verdict';

const gate = createVerdictGate({
  apiKey: process.env.INVINOVERITAS_KEY,          // free: POST https://api.babyblueviper.com/register
  failMode: 'closed',                             // reviewer down => no payment
  proceedOn: ['approve', 'approve_with_concerns'],
  reviewAboveAtomic: 1_000_000n,                  // only review payments >= 1 USDC
  accountableParty: 'treasury-ops@yourco',        // signed into the record with the proceed_on rule
});
const pay = createVerdictPaymentFetch({ privateKey: AGENT_KEY, gate, rpcUrl: 'https://mainnet.base.org',
  onDecision: (url, d) => audit.log({ url, allowed: d.allowed, verdict: d.verdict, proof: d.event?.id }),
  onSettled: (url, tx, r) => audit.log({ url, tx, governed: r instanceof Error ? r.message : r.valid }) });
const res = await pay('https://feed.example.com/analytics/SOL-USDC');
```

## Integration (isolated signer)

The signer gets an optional `preSign` hook. It runs after `PolicyEngine.check()` and before the vault is decrypted, so the key is never touched for a blocked payment:

```ts
const decisions = new Map();
const signer = new SignerServer({ password, preSign: gate.asPreSign({ onDecision: (d) => decisions.set(d.nonce, d) }) });
// later, with the settled tx hash and the nonce from the authorization:
const check = await gate.verifyExecution(decisions.get(nonce), txHash, { rpcUrl: 'https://mainnet.base.org' });
```

## What a valid result does and doesn't establish

It establishes that the verdict was issued by the published invinoveritas key and hasn't been altered, that it
committed to these exact payment fields, that the settled authorization was created after the verdict existed, and
that the settled transfer matches. It does **not** establish that the reviewer saw complete context, that the verdict
was right, or that the payer couldn't have paid another way without a verdict. Enforcement stays with the payer, and that is
what this gate provides.

`decision_ref_recomputes` here is a pure hash recompute. The hosted `/verify-proof` also checks the preimage field
list against the registry for each policy version.

## Cost and latency

An `onchain_action` review takes about 20 to 60 s and costs about $1 (prepaid sats on a Bearer key, or x402 USDC). That suits
treasury-sized, new-recipient or above-threshold payments, not sub-cent API calls. Use `reviewAboveAtomic`, or call
the gate only where your policy would otherwise require manual approval.

## Tests

`src/__tests__/verdict.test.ts` (33 tests). The fixtures are real recorded invinoveritas verdicts from 2026-10-08: an
`approve_with_concerns` verdict followed by a 1.00 USDC transfer on Base,
[0x2afb35e2…c4a7](https://basescan.org/tx/0x2afb35e24a20fdee74c35937feb59b86358d45c8029a91d065d59825c3e7c4a7),
whose nonce is the verdict's `decision_ref`, plus a signed `reject`. No test touches the network.
