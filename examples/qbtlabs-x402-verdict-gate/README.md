# invinoveritas verdict gate for `@qbtlabs/x402`

*An independent integration example. It isn't affiliated with or endorsed by QBT Labs. [`@qbtlabs/x402`](https://github.com/QBT-Labs/x402) is MIT-licensed.*

`@qbtlabs/x402` already puts a policy engine in front of the signature (caps, allowlists, an isolated signer) and an
audit log behind it. This example adds one thing an operator can't self-issue: an **independent, signed verdict
bound to the exact EIP-3009 payment fields before the key signs**, plus a check after settlement that the
settled transfer carried that verdict (the EIP-3009 nonce is the verdict's `decision_ref`).

- `src/verdict/`: the module (TypeScript, ESM). It needs no new dependencies, using the `@noble/*` and `viem` already in `@qbtlabs/x402`.
- `src/__tests__/verdict.test.ts`: 42 tests on real recorded verdicts and the real Base settlement
  [0x2afb35e2…c4a7](https://basescan.org/tx/0x2afb35e24a20fdee74c35937feb59b86358d45c8029a91d065d59825c3e7c4a7). No network.
- `patch/0001-*.patch`: the same change as one commit against `QBT-Labs/x402@f736392`. It also adds an optional `preSign`
  hook to the isolated signer, which runs after `PolicyEngine.check()` and before the vault decrypts, and a `./verdict` package export.
  It includes the two client fixes the gate's payment fetch builds on (exact USD to atomic amounts; paying x402 v2 servers),
  which are also open as QBT-Labs/x402 #14 and #15.

```sh
git clone https://github.com/QBT-Labs/x402 && cd x402 && git checkout f736392
git am /path/to/patch/0001-*.patch && npm ci && npm test   # 273 passed, 18 skipped
```

**Live on Base mainnet (2026-10-10).** `createVerdictPaymentFetch` paid a live x402 v2 server
(`GET https://api.babyblueviper.com/regime`, 0.024897 USDC). The first review rejected it: the only evidence for the
payout address was the 402 of the server being paid, which the reviewer named as possible address poisoning, so nothing
was signed. With the recipient record checked against an independent source (Coinbase's x402 Bazaar catalog lists the
same `payTo`), the verdict was `approve` (verified offline, 6 s), the payment settled
([0xa186db4b…f84a](https://basescan.org/tx/0xa186db4ba79d6b9581cdb7a3134593038bc5ae186ab526eefaa6b349a274f84a)), and
`verifyExecution` passed 6/6 offline against the chain: the on-chain nonce is the verdict's `decision_ref` and the
transfer matches the approved one.


**Run it yourself: `live_demo.mjs`.** In a checkout of QBT-Labs/x402 with the patch applied and built:

```sh
export INVINOVERITAS_KEY=...                                   # free: POST https://api.babyblueviper.com/register
node live_demo.mjs reject                                      # no vendor record -> reject, nothing signed
node live_demo.mjs pay                                         # vendor record from Coinbase's x402 directory -> approve,
                                                               # pay 2.5 cents (PAYER_KEY: a Base wallet with a little USDC)
node live_demo.mjs verdict --vendor 0x1111...1111 "Acme Ltd"   # a vendor record that doesn't match the invoice -> reject
```

The vendor is our own paid `/regime` endpoint, so a paid run pays us about 2.5 cents (set `DEMO_URL` for another
x402 v2 server). The vendor record is what the agent checks the invoice's payout address against: a source the vendor
doesn't control. By default it's Coinbase's public x402 directory; in production it's your own vendor database.

**Independent payee data: Lumière PayCheck.** By default the demo cross-checks the directory's vendor record with
PayCheck, so the reviewer sees two independent sources (`--no-paycheck` turns it off; `--vendor-source paycheck` uses it
alone). It takes data from [Lumière PayCheck](https://lumierepaycheck.org) ([API](https://github.com/Book0fEli/lumiere-paycheck/blob/main/docs/api.md)),
which monitors x402 endpoints continuously: payout-wallet history, paid delivery tests and OFAC screening. Its
`check-payment` answer goes into the evidence (`recipient_record.independent_monitor`, hashed into the verdict), so the
reviewer weighs third-party data about the payee instead of the payer's word. First run (2026-10-10, against our own
`/regime`): PayCheck reported the payout wallet stable and matching and OFAC-clear, and denied on its own price rule (the
quote was 0.000003 USDC above the price it last saw); the reviewer weighed that and returned `approve_with_concerns`,
citing the monitor's grade and the unverified delivery.

**Tuning what blocks** (operator settings, details in `src/verdict/README.md`): `proceedOn` (stricter with
`['approve']`; adding `'reject'` gives an advisory shadow mode that blocks nothing and keeps every verdict), `blockOn`
(block an allowed verdict when the review lists a concern you name, e.g. `address_poisoning`; only ever stricter),
`concerns` (your own checklist for the reviewer) and `severityThreshold`.

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

## Evidence: give the reviewer what your systems already know

An independent reviewer that sees only an address and an amount cannot tie the recipient to anyone, so it rejects. That
is the right answer for an unknown payee, but your systems usually know more. Pass it per payment (`intent.evidence`) or
through a resolver (`evidence: async (intent) => ...`) that reads your vendor master, the PolicyEngine result and your
invoice ledger:

```ts
const gate = createVerdictGate({
  apiKey, evidence: async (i) => ({
    recipient_record: await vendors.byAddress(i.to),          // id, legal name, payout address, how and when verified
    payment_history: await ledger.historyTo(i.to),            // prior settled payments to this exact address
    policy_decision: lastPolicyResult,                        // ALLOW, caps, spent today, allowlist version
    obligation: await invoices.forPayment(i),                 // invoice/PO, amount, approvals, status: open, idempotency key
  }),
});
```

The reviewer is told the evidence is asserted by the payer, not verified by the reviewer, and its `sha256(JCS(evidence))`
is bound into the signed verdict as `evidence_sha256`, so the record shows what the verdict was based on. If the
resolver throws, the payment is blocked and no review is requested, whatever the fail mode.

Measured on 2026-10-10 against the live reviewer, three runs per case, using this module's exact request text:

| Case | Without evidence | With evidence |
|---|---|---|
| 2,500 USDC supplier invoice, known vendor | reject 3/3 | approve_with_concerns 3/3 |
| 120 USDC monthly subscription, known vendor | reject 3/3 | approve 1, approve_with_concerns 2 |
| 48,000 USDC to an address "changed by email", no callback | reject 3/3 | reject 3/3, citing the mismatch with the vendor record |

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

An `onchain_action` review takes about 20 to 60 s and costs about $1 at list price (prepaid sats on a Bearer key, or x402 USDC; volume pricing on request). That suits
treasury-sized, new-recipient or above-threshold payments, not sub-cent API calls. Use `reviewAboveAtomic`, or call
the gate only where your policy would otherwise require manual approval.

## Tests

`src/__tests__/verdict.test.ts` (42 tests). The fixtures are real recorded invinoveritas verdicts from 2026-10-08: an
`approve_with_concerns` verdict followed by a 1.00 USDC transfer on Base,
[0x2afb35e2…c4a7](https://basescan.org/tx/0x2afb35e24a20fdee74c35937feb59b86358d45c8029a91d065d59825c3e7c4a7),
whose nonce is the verdict's `decision_ref`, plus a signed `reject`. No test touches the network.
