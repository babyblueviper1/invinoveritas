// Live demo: @qbtlabs/x402 (with the verdict gate) pays a real x402 v2 server on Base mainnet, after a vendor-record
// check and an independent signed verdict. Run it from a checkout of QBT-Labs/x402 with patch/0001-*.patch applied
// and built (`npm run build`), so `@qbtlabs/x402` and `@qbtlabs/x402/verdict` resolve.
//
//   node live_demo.mjs reject                      no vendor record: the only evidence for the payout address is the
//                                                  invoice itself. Asks for a verdict, never signs or pays.
//   node live_demo.mjs verdict [vendor options]    with a vendor record: verdict only, never signs or pays.
//   node live_demo.mjs pay     [vendor options]    with a vendor record: verdict -> sign (nonce = decision_ref) -> pay
//                                                  -> check on-chain that what settled is what was approved.
// Vendor options (default: look the vendor up in Coinbase's public x402 directory, which the vendor doesn't control):
//   --vendor 0xADDRESS "Label"     use this payout address as the vendor record, as if from your vendor database
//   --vendor-record record.json    a saved record: {"payTo", "label", "source", "checked_at"}
// Env: INVINOVERITAS_KEY (free: POST https://api.babyblueviper.com/register, then fund it), PAYER_KEY (pay only:
// a Base wallet holding a little USDC; no ETH needed, the facilitator pays gas), DEMO_URL (default /regime, 2.5 cents).
import { readFileSync } from 'node:fs';
import { parsePaymentRequired } from '@qbtlabs/x402';
import { createVerdictGate, createVerdictPaymentFetch } from '@qbtlabs/x402/verdict';
import { privateKeyToAccount } from 'viem/accounts';

const [mode, ...rest] = process.argv.slice(2);
if (!['reject', 'verdict', 'pay'].includes(mode)) { console.error('usage: node live_demo.mjs reject|verdict|pay [--vendor 0x.. "Label" | --vendor-record file.json]'); process.exit(2); }
const URL_ = process.env.DEMO_URL ?? 'https://api.babyblueviper.com/regime';
const DIRECTORY = 'https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources';
const t0 = Date.now();
const secs = () => ((Date.now() - t0) / 1000).toFixed(1) + ' s';
const say = (s) => console.log(s);
const checks = (c) => Object.entries(c).map(([k, v]) => `${k} ${v ? 'OK' : 'FAIL'}`).join(', ');

async function lookUpInDirectory(resource) {
  for (let off = 0, total = Infinity; off < total; off += 1000) {
    const d = await (await fetch(`${DIRECTORY}?limit=1000&offset=${off}`)).json();
    total = d.pagination?.total ?? 0;
    for (const it of d.items ?? []) {
      const acc = (it.accepts ?? []).find((a) => a.network === 'eip155:8453');
      if (it.resource === resource && acc) {
        return { payTo: acc.payTo, label: new URL(resource).host, checked_at: new Date().toISOString(),
          source: `Coinbase CDP x402 Bazaar discovery catalog (${DIRECTORY}), hosted by Coinbase and independent of the server being paid: its entry for ${resource} lists this payTo (entry lastUpdated ${it.lastUpdated})` };
      }
    }
    if (!d.items?.length) break;
    await new Promise((r) => setTimeout(r, 600));
  }
  return null;
}

async function vendorRecord() {
  if (mode === 'reject') return null;
  const i = rest.indexOf('--vendor'), j = rest.indexOf('--vendor-record');
  if (j >= 0) return JSON.parse(readFileSync(rest[j + 1], 'utf8'));
  if (i >= 0) return { payTo: rest[i + 1], label: rest[i + 2] ?? 'vendor', checked_at: new Date().toISOString(), from_vendor_db: true,
    source: `the payer's own vendor database entry for ${rest[i + 2] ?? 'this vendor'}` };
  say(`   Looking the vendor up in Coinbase's public x402 directory ...`);
  const r = await lookUpInDirectory(URL_);
  if (!r) throw new Error('vendor not found in the directory');
  return r;
}

say(`1. GET ${URL_}`);
const first = await fetch(URL_);
let body = await first.json().catch(() => null);
if (!Array.isArray(body?.accepts) && first.headers.get('PAYMENT-REQUIRED')) body = JSON.parse(Buffer.from(first.headers.get('PAYMENT-REQUIRED'), 'base64').toString());
const req = parsePaymentRequired(body);
if (!req) throw new Error('no payable USDC-on-Base requirement in the 402');
say(`   The vendor's invoice (HTTP 402): pay ${Number(req.amountAtomic) / 1e6} USDC to ${req.payTo} on Base`);

const record = await vendorRecord();
const match = record ? record.payTo.toLowerCase() === req.payTo.toLowerCase() : false;
say(!record ? '2. Vendor record: NOT CHECKED. The only evidence for the payout address is the invoice itself.'
  : `2. Vendor record (${record.label}): ${record.payTo}, from ${record.from_vendor_db ? 'the vendor database' : "Coinbase's x402 directory"} (${record.checked_at})\n   `
    + (match ? 'MATCHES the address the server asks for' : `DOES NOT MATCH the address the server asks for (${req.payTo})`));

const evidence = {
  policy_decision: { result: 'allow', payment_terms: 'x402 exact scheme is an unconditional prepaid payment; accepted under the per-call cap, non-delivery risk capped at that amount', per_call_cap_usdc: '0.05', daily_cap_usdc: '0.50', allowlisted_host: new URL(URL_).host },
  obligation: { what: `one paid call to ${URL_}, priced by the server in its 402`, idempotency_key: `demo-${new Date().toISOString().slice(0, 16)}`, status: 'unpaid' },
  recipient_record: record
    ? { vendor: record.label, payout_address: record.payTo, network: 'eip155:8453', source: record.source, verified_at: record.checked_at, matches_402_payTo: match,
        ...(match ? {} : { note: `the server's 402 asks for payment to ${req.payTo}, which is NOT the payout address in this vendor record` }), relationship: 'data vendor, pay-per-call' }
    : { vendor: new URL(URL_).host, payout_address_source: "the payTo in this server's own 402 response for this exact URL", relationship: 'data vendor, pay-per-call' },
};
const gate = createVerdictGate({
  apiKey: process.env.INVINOVERITAS_KEY, failMode: 'closed', proceedOn: ['approve', 'approve_with_concerns'],
  accountableParty: 'operator of the demo agent', agentId: 'qbtlabs-x402-live-demo', evidence: () => evidence,
});

function show(d) {
  say(`3. Verdict: ${String(d.verdict).toUpperCase()} in ${secs()}  ->  ${d.allowed ? 'ALLOWED to sign' : 'BLOCKED, nothing signed, nothing paid'}`);
  if (d.proof) say(`   Proof checked offline: ${checks(d.proof.checks)}`);
  if (d.summary) say(`   Reviewer: ${d.summary}`);
  for (const i of ((d.review && d.review.issues) || []).filter((x) => x.severity === 'blocker')) say(`   Blocker (${i.category}): ${String(i.description).slice(0, 260)}`);
  if (!d.allowed && !d.summary) say(`   Reason: ${d.reason}`);
}
say('   Asking invinoveritas for a signed verdict on the exact EIP-3009 fields...');

if (mode !== 'pay') {
  const from = process.env.PAYER_KEY ? privateKeyToAccount(process.env.PAYER_KEY).address : '0x0000000000000000000000000000000000000001';
  const d = await gate.check({ chainId: req.chainId, from, to: req.payTo, amountAtomic: req.amountAtomic, purpose: `GET ${URL_}` });
  show(d);
  if (d.allowed) say(`4. (verdict only: stopping before signing; the EIP-3009 nonce would be ${d.nonce})`);
  process.exit(0);
}

let settled; const done = new Promise((r) => (settled = r)); let result = {};
const pay = createVerdictPaymentFetch({
  privateKey: process.env.PAYER_KEY, gate, rpcUrl: 'https://mainnet.base.org',
  onDecision: (_u, d) => { show(d); if (d.allowed) say(`4. Signing EIP-3009 transferWithAuthorization, nonce = verdict decision_ref ${d.nonce.slice(0, 18)}...`); },
  onSettled: (_u, tx, r) => { result = { tx, r }; settled(); },
});
try {
  const res = await pay(URL_);
  say(`5. Paid. HTTP ${res.status}. Response: ${(await res.text()).slice(0, 160)}...`);
  await Promise.race([done, new Promise((r) => setTimeout(r, 90000))]);
  if (!result.tx) say('6. No settlement tx reported by the server.');
  else {
    say(`   Settlement: https://basescan.org/tx/${result.tx}`);
    say(result.r instanceof Error ? `6. Post-settlement check: ${result.r.message}`
      : `6. Post-settlement check, offline against Base: ${result.r.valid ? 'VALID' : 'INVALID'}\n   ${checks(result.r.checks)}`);
  }
} catch (e) {
  say(`STOPPED: ${e.message}`);
}
say(`Done in ${secs()}.`);
