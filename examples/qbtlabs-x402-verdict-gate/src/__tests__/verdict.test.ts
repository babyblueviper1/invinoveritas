/**
 * invinoveritas verdict gate tests. Every proof here is a real signed verdict recorded from invinoveritas
 * (pilot exhibit 3, 2026-10-08), and the settlement receipt is the real Base transaction 0x2afb35e2...
 * No network calls: /review is mocked with the recorded responses.
 */

import { readFileSync, mkdtempSync, rmSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';
import { privateKeyToAccount, generatePrivateKey } from 'viem/accounts';
import { verifyTypedData } from 'viem';
import {
  canonicalize, argsHash, verifyVerdictProof, executionNonce, verifyExecutionLocal, createVerdictGate,
  signGatedAuthorization, createVerdictPaymentFetch, INVINOVERITAS_PUBKEY, type GateDecision, type ProofEvent,
} from '../verdict/index.js';
import { jest } from '@jest/globals';
import { Vault } from '../vault/index.js';
import { SignerServer } from '../signer/server.js';
import { SignerClient } from '../signer/client.js';

const FX = join(process.cwd(), 'src/__tests__/fixtures/invinoveritas');
const approve = JSON.parse(readFileSync(join(FX, 'exhibit3_approve_settled.json'), 'utf8'));
const reject = JSON.parse(readFileSync(join(FX, 'exhibit3_reject.json'), 'utf8'));
const approveEvent: ProofEvent = approve.review_response.proof.event;
const rejectEvent: ProofEvent = reject.review_response.proof.event;
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));
const contentOf = (e: ProofEvent) => JSON.parse(e.content);

describe('JCS (RFC 8785)', () => {
  it('sorts keys, drops whitespace, keeps strings exact', () => {
    expect(canonicalize({ b: 1, a: [true, null, 'x'], c: { z: 1.5, y: 'é' } })).toBe('{"a":[true,null,"x"],"b":1,"c":{"y":"é","z":1.5}}');
  });
  it('rejects values JCS cannot represent', () => {
    expect(() => canonicalize({ x: NaN })).toThrow();
    expect(() => canonicalize({ x: 1n })).toThrow();
  });
  it('recomputes the args hash bound in a real verdict', () => {
    expect(argsHash(approve.args)).toBe(contentOf(approveEvent).action_binding_args_hash);
  });
});

describe('verifyVerdictProof (offline)', () => {
  it('passes every check on a real approve_with_concerns proof', () => {
    const r = verifyVerdictProof(approveEvent, { args: approve.args, tool: approve.tool });
    expect(r.checks).toEqual({
      id_integrity: true, signature_valid: true, issued_by_invinoveritas: true, is_proof_event: true,
      decision_ref_recomputes: true, args_bound: true, tool_bound: true,
    });
    expect(r.valid).toBe(true);
    expect(r.verdict).toBe('approve_with_concerns');
    expect(approveEvent.pubkey).toBe(INVINOVERITAS_PUBKEY);
  });
  it('passes on a real reject proof (valid proof, negative verdict)', () => {
    const r = verifyVerdictProof(rejectEvent, { args: reject.args, tool: reject.tool });
    expect(r.valid).toBe(true);
    expect(r.verdict).toBe('reject');
  });
  it('fails id_integrity when the verdict text is edited', () => {
    const ev = clone(approveEvent);
    ev.content = ev.content.replace('"verdict":"approve_with_concerns"', '"verdict":"approve"');
    const r = verifyVerdictProof(ev);
    expect(r.checks.id_integrity).toBe(false);
    expect(r.checks.decision_ref_recomputes).toBe(false);
    expect(r.valid).toBe(false);
  });
  it('fails signature_valid on a flipped signature byte', () => {
    const ev = clone(approveEvent);
    ev.sig = (ev.sig[0] === '0' ? '1' : '0') + ev.sig.slice(1);
    expect(verifyVerdictProof(ev).checks.signature_valid).toBe(false);
  });
  it('fails issuer pin against another key', () => {
    expect(verifyVerdictProof(approveEvent, { pubkey: 'ab'.repeat(32) }).checks.issued_by_invinoveritas).toBe(false);
  });
  it('fails args_bound when any bound field differs (amount, recipient)', () => {
    expect(verifyVerdictProof(approveEvent, { args: { ...approve.args, amount_atomic: '1000001' } }).checks.args_bound).toBe(false);
    expect(verifyVerdictProof(approveEvent, { args: { ...approve.args, to: '0x' + '1'.repeat(40) } }).checks.args_bound).toBe(false);
  });
  it('never throws on garbage', () => {
    expect(verifyVerdictProof({} as ProofEvent).valid).toBe(false);
    expect(verifyVerdictProof({ ...approveEvent, created_at: 1.5 } as ProofEvent).valid).toBe(false);
  });
});

describe('executionNonce', () => {
  it('equals the nonce of the real signed authorization', () => {
    expect(executionNonce(contentOf(approveEvent).decision_ref)).toBe(approve.authorization.nonce);
  });
  it('rejects a malformed decision_ref', () => {
    expect(() => executionNonce('sha256:xyz')).toThrow();
  });
});

describe('verifyExecutionLocal (after settlement)', () => {
  it('matches the recorded /verify-execution result on the real Base tx', () => {
    const r = verifyExecutionLocal(approveEvent, approve.args, approve.receipt);
    expect(r.checks).toEqual(approve.verify_execution_response_recorded.checks);
    expect(r.valid).toBe(true);
    expect(r.executed_despite_reject).toBe(false);
  });
  it('fails nonce_is_verdict for a payment that carried a different verdict', () => {
    const r = verifyExecutionLocal(rejectEvent, reject.args, approve.receipt);
    expect(r.checks.nonce_is_verdict).toBe(false);
    expect(r.valid).toBe(false);
  });
  it('fails transfer_matches when the settled amount differs from the bound amount', () => {
    const rc = clone(approve.receipt);
    rc.logs[1].data = '0x' + (2_000_000).toString(16).padStart(64, '0');
    expect(verifyExecutionLocal(approveEvent, approve.args, rc).checks.transfer_matches).toBe(false);
  });
  it('fails tx_succeeded on a reverted receipt', () => {
    expect(verifyExecutionLocal(approveEvent, approve.args, { ...approve.receipt, status: '0x0' }).valid).toBe(false);
  });
});

describe('createVerdictGate.decide (policy over a verified verdict)', () => {
  const verifiedAt = contentOf(approveEvent).verified_at as number;
  it('allows a fresh approve_with_concerns and returns the decision_ref nonce', () => {
    const gate = createVerdictGate({ now: () => verifiedAt + 2 });
    const d = gate.decide(approve.review_response, approve.args);
    expect(d.allowed).toBe(true);
    expect(d.nonce).toBe(approve.authorization.nonce);
  });
  it('blockOn blocks an allowed verdict when the review lists a matching concern, and only then', () => {
    const withIssue = { ...clone(approve.review_response), issues: [
      { severity: 'high', category: 'address_poisoning', description: 'payee not in the vendor record' },
      { severity: 'info', category: 'missing_check', description: 'token reputation not checked' }] };
    const byCategory = createVerdictGate({ now: () => verifiedAt + 2, blockOn: { categories: ['address_poisoning'] } }).decide(withIssue, approve.args);
    expect(byCategory.allowed).toBe(false);
    expect(byCategory.blockedBy?.category).toBe('address_poisoning');
    expect(byCategory.nonce).toBeUndefined();
    expect(createVerdictGate({ now: () => verifiedAt + 2, blockOn: { severities: ['high'] } }).decide(withIssue, approve.args).allowed).toBe(false);
    expect(createVerdictGate({ now: () => verifiedAt + 2, blockOn: { categories: ['scam_token'], severities: ['blocker'] } }).decide(withIssue, approve.args).allowed).toBe(true);
    expect(createVerdictGate({ now: () => verifiedAt + 2 }).decide(withIssue, approve.args).allowed).toBe(true);
  });
  it('blockOn never allows: a reject with no matching concern stays blocked', () => {
    const gate = createVerdictGate({ now: () => contentOf(rejectEvent).verified_at + 2, blockOn: { categories: ['nothing'] } });
    expect(gate.decide(reject.review_response, reject.args).allowed).toBe(false);
  });
  it('blocks a real reject verdict', () => {
    const gate = createVerdictGate({ now: () => contentOf(rejectEvent).verified_at + 2 });
    const d = gate.decide(reject.review_response, reject.args);
    expect(d.allowed).toBe(false);
    expect(d.reason).toMatch(/reject/);
  });
  it('blocks approve_with_concerns when proceedOn is approve only', () => {
    const gate = createVerdictGate({ now: () => verifiedAt + 2, proceedOn: ['approve'] });
    expect(gate.decide(approve.review_response, approve.args).allowed).toBe(false);
  });
  it('blocks a stale verdict', () => {
    const gate = createVerdictGate({ now: () => verifiedAt + 3600 });
    expect(gate.decide(approve.review_response, approve.args).reason).toMatch(/old/);
  });
  it('blocks a real verdict replayed for a different payment, even with failMode open', () => {
    const gate = createVerdictGate({ now: () => verifiedAt + 2, failMode: 'open' });
    const d = gate.decide(approve.review_response, { ...approve.args, to: '0x' + '2'.repeat(40) });
    expect(d.allowed).toBe(false);
    expect(d.reason).toMatch(/args_bound/);
  });
});

describe('createVerdictGate.check (/review call, mocked)', () => {
  const intent = { chainId: 8453, from: '0x' + 'a'.repeat(40), to: '0x' + 'b'.repeat(40), amountAtomic: 10_000n, purpose: 'GET https://feed.example.com/price/SOL-USDC' };
  const respond = (status: number, body: unknown) =>
    (async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;

  it('sends a signed, action-bound onchain_action review', async () => {
    let sent: any; let auth: string | null = null;
    const f = (async (_u: string, init: RequestInit) => {
      sent = JSON.parse(String(init.body)); auth = new Headers(init.headers).get('Authorization');
      return new Response('{}', { status: 200 });
    }) as unknown as typeof fetch;
    const gate = createVerdictGate({ fetch: f, apiKey: 'test-key', now: () => 1_800_000_000 });
    await gate.check(intent);
    expect(auth).toBe('Bearer test-key');
    expect(sent.sign).toBe(true);
    expect(sent.artifact_type).toBe('onchain_action');
    expect(sent.action_binding.tool).toBe('usdc_transfer_eip3009');
    expect(sent.action_binding.args).toMatchObject({
      chain: 'eip155:8453', token: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', amount_atomic: '10000',
      valid_after: '1799999940', valid_before: '1800000600', proceed_on: ['approve', 'approve_with_concerns'],
    });
    expect(sent.artifact).toContain('TransferWithAuthorization');
  });
  it('fail-closed (default) blocks when the reviewer errors', async () => {
    const d = await createVerdictGate({ fetch: respond(503, {}) }).check(intent);
    expect(d.allowed).toBe(false);
    expect(d.reason).toMatch(/503/);
  });
  it('fail-open allows, flagged, when the reviewer errors', async () => {
    const d = await createVerdictGate({ fetch: respond(503, {}), failMode: 'open' }).check(intent);
    expect(d).toMatchObject({ allowed: true, failOpen: true });
    expect(d.nonce).toBeUndefined();
  });
  it('times out to the fail mode', async () => {
    const hang = ((_u: string, init: RequestInit) => new Promise((_, rej) => {
      init.signal?.addEventListener('abort', () => rej(Object.assign(new Error('aborted'), { name: 'AbortError' })));
    })) as unknown as typeof fetch;
    const d = await createVerdictGate({ fetch: hang, timeoutMs: 20 }).check(intent);
    expect(d.allowed).toBe(false);
    expect(d.reason).toMatch(/timeout/);
  });
  describe('evidence', () => {
    const ev = {
      recipient_record: { vendor_id: 'V-0193', payout_address: '0x' + 'b'.repeat(40), verified_via: 'callback + 2-person approval' },
      policy_decision: { result: 'ALLOW', per_tx_cap_usdc: 5000 },
      obligation: { invoice: 'INV-1043', amount_usdc: '0.01', status: 'open', idempotency_key: 'INV-1043#1' },
    };
    const capture = () => {
      const box: { sent?: any } = {};
      const f = (async (_u: string, init: RequestInit) => { box.sent = JSON.parse(String(init.body)); return new Response('{}', { status: 200 }); }) as unknown as typeof fetch;
      return { box, f };
    };
    it('resolves evidence per payment, shows it to the reviewer labelled as asserted, and binds its hash into the args', async () => {
      const { box, f } = capture(); let seen: any;
      await createVerdictGate({ fetch: f, now: () => 1_800_000_000, evidence: (i) => { seen = i; return ev; } }).check(intent);
      expect(seen.to).toBe(intent.to);
      expect(box.sent.action_binding.args.evidence_sha256).toBe(argsHash(ev));
      expect(box.sent.artifact).toContain('asserted, not independently verified');
      expect(box.sent.artifact).toContain(canonicalize(ev));
      expect(box.sent.artifact).toContain('PRE-SIGN');
    });
    it('per-call evidence overrides the resolver', async () => {
      const { box, f } = capture();
      const own = { obligation: { invoice: 'X' } };
      await createVerdictGate({ fetch: f, evidence: () => ev }).check({ ...intent, evidence: own });
      expect(box.sent.action_binding.args.evidence_sha256).toBe(argsHash(own));
    });
    it('without evidence, binds no evidence hash and tells the reviewer none was supplied', async () => {
      const { box, f } = capture();
      await createVerdictGate({ fetch: f }).check(intent);
      expect(box.sent.action_binding.args.evidence_sha256).toBeUndefined();
      expect(box.sent.artifact).toContain('No evidence was supplied');
    });
    it('blocks (whatever the fail mode) when the evidence resolver throws, and never calls the reviewer', async () => {
      let called = false;
      const f = (async () => { called = true; return new Response('{}'); }) as unknown as typeof fetch;
      const d = await createVerdictGate({ fetch: f, failMode: 'open', evidence: () => { throw new Error('vendor db down'); } }).check(intent);
      expect(d.allowed).toBe(false);
      expect(d.reason).toMatch(/vendor db down/);
      expect(called).toBe(false);
    });
    it('a verdict bound to other evidence fails args_bound', async () => {
      const gate = createVerdictGate({ now: () => 1_800_000_000 });
      const args = { ...gate.bindArgs(intent), evidence_sha256: argsHash(ev) };
      const d = gate.decide(approve.review_response, args);
      expect(d.allowed).toBe(false);
      expect(d.reason).toMatch(/args_bound/);
    });
  });
  it('sends concerns and the severity threshold to /review', async () => {
    let sent: any;
    const f = (async (_u: any, init?: RequestInit) => { sent = JSON.parse(String(init?.body)); return new Response('{}', { status: 500 }); }) as unknown as typeof fetch;
    await createVerdictGate({ fetch: f, concerns: 'payee must be in the vendor master', severityThreshold: 'high' }).check(intent);
    expect(sent.concerns).toBe('payee must be in the vendor master');
    expect(sent.severity_threshold).toBe('high');
  });
  it('blocks when the reviewer returns a real proof for some other payment', async () => {
    const d = await createVerdictGate({ fetch: respond(200, approve.review_response), failMode: 'open' }).check(intent);
    expect(d.allowed).toBe(false);
    expect(d.reason).toMatch(/args_bound/);
  });
});

describe('signGatedAuthorization', () => {
  const pk = generatePrivateKey();
  const me = privateKeyToAccount(pk).address;
  const nonce = approve.authorization.nonce as `0x${string}`;
  const decision = (from: string): GateDecision => ({
    allowed: true, reason: 'test', nonce,
    args: { chain: 'eip155:8453', token: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', from, to: '0x' + 'b'.repeat(40),
      amount_atomic: '10000', valid_after: '100', valid_before: '2000000000', nonce_rule: 'x', proceed_on: ['approve'] },
  });
  it('signs with nonce = decision_ref and exactly the bound fields', async () => {
    const r = await signGatedAuthorization(decision(me), pk);
    expect(r.authorization.nonce).toBe(nonce);
    const ok = await verifyTypedData({
      address: me,
      domain: { name: 'USD Coin', version: '2', chainId: 8453, verifyingContract: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913' },
      types: { TransferWithAuthorization: [
        { name: 'from', type: 'address' }, { name: 'to', type: 'address' }, { name: 'value', type: 'uint256' },
        { name: 'validAfter', type: 'uint256' }, { name: 'validBefore', type: 'uint256' }, { name: 'nonce', type: 'bytes32' }] },
      primaryType: 'TransferWithAuthorization',
      message: { from: me, to: ('0x' + 'b'.repeat(40)) as `0x${string}`, value: 10000n, validAfter: 100n, validBefore: 2000000000n, nonce },
      signature: r.signature as `0x${string}`,
    });
    expect(ok).toBe(true);
  });
  it('refuses when the key is not the bound payer', async () => {
    await expect(signGatedAuthorization(decision('0x' + 'c'.repeat(40)), pk)).rejects.toThrow(/from/);
  });
  it('refuses a blocked or fail-open decision', async () => {
    await expect(signGatedAuthorization({ allowed: false, reason: 'reject' }, pk)).rejects.toThrow(/blocked/);
    await expect(signGatedAuthorization({ allowed: true, failOpen: true, reason: 'x' }, pk)).rejects.toThrow(/fail-open/);
  });
});

describe('SignerServer preSign hook', () => {
  let dir: string;
  const password = 'test-password-123';
  beforeAll(() => {
    dir = mkdtempSync(join(tmpdir(), 'x402-verdict-signer-'));
    new Vault({ vaultPath: join(dir, 'vault.enc') }).init({ password });
  });
  afterAll(() => rmSync(dir, { recursive: true, force: true }));

  async function withServer(preSign: any, fn: (c: SignerClient) => Promise<void>) {
    const socketPath = join(dir, `s${Math.random().toString(36).slice(2)}.sock`);
    const server = new SignerServer({ socketPath, vaultPath: join(dir, 'vault.enc'), policyPath: join(dir, 'policy.json'), password, preSign } as any);
    await server.start();
    try { await fn(new SignerClient({ socketPath })); } finally { await server.stop(); }
  }
  const payload = { to: '0x' + 'b'.repeat(40), amount: '10000', chainId: 8453 };

  it('refuses to sign when the hook refuses', async () => {
    await withServer(async () => ({ allowed: false, reason: "verdict 'reject'" }), async (c) => {
      await expect(c.sign(payload)).rejects.toThrow(/reject/);
    });
  });
  it('signs with the nonce and window the hook returns', async () => {
    let seenFrom = '';
    const nonce = approve.authorization.nonce;
    await withServer(async (p: any) => { seenFrom = p.from; return { allowed: true, nonce, validAfter: 100, validBefore: 2000000000 }; }, async (c) => {
      const r = await c.sign(payload);
      expect(r.authorization?.nonce).toBe(nonce);
      expect(r.authorization?.validAfter).toBe('100');
      expect(seenFrom).toMatch(/^0x[0-9a-fA-F]{40}$/);
    });
  });
});

describe('createVerdictPaymentFetch', () => {
  const pk = generatePrivateKey();
  const payTo = '0x' + 'b'.repeat(40);
  const challenge = { error: 'Payment Required', accepts: [{ network: 'eip155:8453', asset: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', payTo, maxAmountRequired: '5000000' }] };
  afterEach(() => jest.restoreAllMocks());

  function mockApi(onPaid: (h: Headers) => void) {
    return jest.spyOn(globalThis, 'fetch').mockImplementation((async (_i: any, init?: RequestInit) => {
      const h = new Headers(init?.headers);
      if (h.get('X-PAYMENT')) { onPaid(h); return new Response('{"ok":true}', { status: 200 }); }
      return new Response(JSON.stringify(challenge), { status: 402 });
    }) as any);
  }

  it('never signs or sends a payment the gate blocks', async () => {
    let paid = false;
    mockApi(() => { paid = true; });
    const reviewFetch = (async () => new Response(JSON.stringify(reject.review_response), { status: 200 })) as unknown as typeof fetch;
    const decisions: GateDecision[] = [];
    const pay = createVerdictPaymentFetch({ privateKey: pk, gate: createVerdictGate({ fetch: reviewFetch }), onDecision: (_u, d) => decisions.push(d) });
    await expect(pay('https://api.example.com/analytics/SOL')).rejects.toThrow(/blocked/);
    expect(paid).toBe(false);
    expect(decisions[0].allowed).toBe(false);
  });

  it('pays below the review threshold without asking for a verdict, and says so', async () => {
    let header = '';
    mockApi((h) => { header = h.get('X-PAYMENT')!; });
    let reviewed = false;
    const reviewFetch = (async () => { reviewed = true; return new Response('{}'); }) as unknown as typeof fetch;
    const decisions: GateDecision[] = [];
    const gate = createVerdictGate({ fetch: reviewFetch, reviewAboveAtomic: 10_000_000n });
    const res = await createVerdictPaymentFetch({ privateKey: pk, gate, onDecision: (_u, d) => decisions.push(d) })('https://api.example.com/price/SOL');
    expect(res.status).toBe(200);
    expect(reviewed).toBe(false);
    expect(decisions[0]).toMatchObject({ allowed: true, skipped: true });
    const sent = JSON.parse(Buffer.from(header, 'base64').toString('utf8'));
    expect(sent.payload.authorization).toMatchObject({ to: payTo, value: '5000000' });
  });

  it('pays an x402 v2 server: requirements from the PAYMENT-REQUIRED header, exact amount, offered entry echoed', async () => {
    const offered = { scheme: 'exact', network: 'eip155:8453', asset: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913', payTo,
      amount: '24897', maxTimeoutSeconds: 60, extra: { name: 'USD Coin', version: '2' } };
    const pr = Buffer.from(JSON.stringify({ x402Version: 2, error: 'X-PAYMENT header required', accepts: [offered] })).toString('base64');
    let sig = '';
    jest.spyOn(globalThis, 'fetch').mockImplementation((async (_i: any, init?: RequestInit) => {
      const h = new Headers(init?.headers);
      if (h.get('PAYMENT-SIGNATURE')) { sig = h.get('PAYMENT-SIGNATURE')!; return new Response('{"ok":true}', { status: 200 }); }
      return new Response('{}', { status: 402, headers: { 'PAYMENT-REQUIRED': pr } });
    }) as any);
    const gate = createVerdictGate({ fetch: (async () => new Response('{}')) as unknown as typeof fetch, reviewAboveAtomic: 10_000_000n });
    const res = await createVerdictPaymentFetch({ privateKey: pk, gate })('https://api.example.com/regime');
    expect(res.status).toBe(200);
    const sent = JSON.parse(Buffer.from(sig, 'base64').toString('utf8'));
    expect(sent.payload.authorization).toMatchObject({ to: payTo, value: '24897' });
    expect(sent.accepted).toEqual(offered);
  });
});
