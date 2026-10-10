/**
 * invinoveritas verdict gate for @qbtlabs/x402: an independent, signed second opinion before a payment is signed.
 *
 * Flow (pre-sign):
 *   1. Fix every EIP-3009 field except the nonce (from, to, value, validAfter, validBefore, token, chain).
 *   2. POST /review with those exact fields as action_binding.args (sign=true).
 *   3. Verify the returned proof OFFLINE (signature, issuer key, decision_ref recompute, args and tool binding).
 *   4. Allow only if the verdict is in `proceedOn` and fresh; the nonce to sign with is the verdict's decision_ref.
 * Flow (post-settlement): verifyExecution() proves the settled transfer carried that verdict.
 *
 * Optional by construction: nothing in @qbtlabs/x402 calls this unless you pass a gate in.
 * Fail mode: 'closed' (default) blocks when the reviewer is unreachable; 'open' allows and says so.
 * A proof that fails verification ALWAYS blocks, whatever the fail mode: a bad proof is a finding, not an outage.
 */

import { USDC_CONTRACTS } from '../config.js';
import { canonicalize } from './jcs.js';
import { argsHash, executionNonce, verifyVerdictProof, type ProofEvent, type ProofVerification, type Verdict } from './proof.js';
import { fetchReceipt, verifyExecutionLocal, verifyExecutionRemote, type ExecutionVerification } from './execution.js';

export const DEFAULT_BASE_URL = 'https://api.babyblueviper.com';
export const GATE_TOOL = 'usdc_transfer_eip3009';
const NONCE_RULE = "eip3009_nonce = this verdict's decision_ref";

export interface PaymentIntent {
  chainId: number;
  /** Payer address (the vault / signer address). */
  from: string;
  /** Recipient (payTo). */
  to: string;
  /** Amount in atomic USDC units (6 decimals). */
  amountAtomic: string | bigint;
  /** Token contract. Defaults to USDC on chainId. */
  token?: string;
  /** What the payment buys and why now, e.g. the 402 resource URL and the tool call. Goes into the reviewed artifact. */
  purpose?: string;
  validAfter?: number;
  validBefore?: number;
  /** Facts from your own systems that justify this payment (see PaymentEvidence). Overrides cfg.evidence for this call. */
  evidence?: PaymentEvidence;
}

/**
 * What your own systems already know about this payment. The reviewer judges the payment against it; without it,
 * an independent reviewer cannot tie the recipient to anyone and will (correctly) reject. Every field is optional,
 * and anything you add is passed through. It is labelled to the reviewer as asserted by the payer, not verified,
 * and its sha256(JCS) is bound into the signed verdict as `evidence_sha256`, so the record shows what the verdict saw.
 */
export interface PaymentEvidence {
  [extra: string]: unknown;
  /** Your vendor/counterparty record for the recipient: id, legal name, payout address, when and how it was verified. */
  recipient_record?: Record<string, unknown>;
  /** Prior payments to this exact address: count, first/last date, all settled. */
  payment_history?: Record<string, unknown>;
  /** The PolicyEngine result for this payment: result, caps, spent today, allowlist version. */
  policy_decision?: Record<string, unknown>;
  /** What is being paid: invoice/PO id, amount, approvals, status (open/unpaid) and an idempotency key. */
  obligation?: Record<string, unknown>;
}

/** The exact arguments the verdict binds (sha256(JCS(args)) is inside the signed proof). */
export interface BoundArgs {
  [extra: string]: unknown;
  chain: string;
  token: string;
  from: string;
  to: string;
  amount_atomic: string;
  valid_after: string;
  valid_before: string;
  nonce_rule: string;
  /** Which verdicts let the payer execute, declared before the payment and signed into the record. */
  proceed_on: Verdict[];
  /** sha256(JCS(evidence)) of the evidence the reviewer was shown, when any. */
  evidence_sha256?: string;
  accountable_party?: string;
  purpose?: string;
}

export interface VerdictGateConfig {
  /** API base. Default https://api.babyblueviper.com */
  baseUrl?: string;
  /** Bearer key for /review. Omit if `fetch` pays per call over x402 (e.g. createPaymentFetch). */
  apiKey?: string;
  /** fetch used for /review (e.g. one that adds your own auth or pays per call). Default: global fetch. */
  fetch?: typeof fetch;
  /**
   * Only review payments at or above this many atomic USDC units (6 decimals). Smaller payments pass ungoverned
   * (decision.skipped = true, no verdict nonce). Default 0: review everything. A /review costs about $1, so for
   * sub-cent API calls set this, or gate only new recipients upstream.
   */
  reviewAboveAtomic?: string | bigint;
  /** Verdicts that allow the payment. Default ['approve', 'approve_with_concerns']. */
  proceedOn?: Verdict[];
  /** 'closed' (default): block when the reviewer is unreachable. 'open': allow, flagged failOpen. */
  failMode?: 'closed' | 'open';
  /** Max seconds between the verdict and signing. Default 120. */
  maxVerdictAgeSeconds?: number;
  /** /review timeout. Default 120000 ms (an onchain_action review typically takes 20 to 60 s). */
  timeoutMs?: number;
  /** Authorization validity window when the intent sets none. Default 600 s. */
  authTtlSeconds?: number;
  /** Pin a verifier key. Default: the published invinoveritas key. */
  pubkey?: string;
  /** Agent id bound into the verdict. */
  agentId?: string;
  /** Who is accountable for the proceed_on rule (bound into the record). */
  accountableParty?: string;
  /** Only issues at or above this severity count. Default 'medium'. */
  severityThreshold?: 'low' | 'medium' | 'high' | 'critical';
  /** Extra context for the reviewer (your policy, the agent's task). */
  context?: string;
  /**
   * Evidence resolver, called per payment before the review (look up your vendor master, PolicyEngine result and
   * invoice ledger). Strongly recommended: without evidence most payments to an unknown address come back 'reject'.
   */
  evidence?: (intent: PaymentIntent) => PaymentEvidence | undefined | Promise<PaymentEvidence | undefined>;
  /** Clock, for tests. Unix seconds. */
  now?: () => number;
}

export interface GateDecision {
  allowed: boolean;
  reason: string;
  verdict?: Verdict;
  confidence?: number;
  summary?: string;
  /** True when allowed only because the reviewer was unreachable and failMode is 'open'. */
  failOpen?: boolean;
  /** True when the amount is below reviewAboveAtomic, so no review was asked for. */
  skipped?: boolean;
  /** Sign the EIP-3009 authorization with exactly these. */
  nonce?: `0x${string}`;
  args?: BoundArgs;
  event?: ProofEvent;
  proof?: ProofVerification;
  /** Raw /review response, for your audit log. */
  review?: unknown;
}

function buildArtifact(args: BoundArgs, chainId: number, evidence?: PaymentEvidence): string {
  const typed = {
    domain: { name: chainId === 84532 ? 'USDC' : 'USD Coin', version: '2', chainId, verifyingContract: args.token },
    primaryType: 'TransferWithAuthorization',
    message: {
      from: args.from, to: args.to, value: args.amount_atomic, validAfter: args.valid_after,
      validBefore: args.valid_before, nonce: "<this verdict's decision_ref>",
    },
  };
  return [
    `x402 payment about to be signed by an agent: ${Number(args.amount_atomic) / 1e6} USDC from ${args.from} to ${args.to} on ${args.chain}.`,
    args.purpose ? `Purpose: ${args.purpose}` : 'Purpose: not stated by the caller.',
    `Exact EIP-712 typed data to be signed (only the nonce is open, and it is fixed by rule to this verdict's decision_ref): ${JSON.stringify(typed)}`,
    `Review stage: PRE-SIGN. The wallet signs only if this review approves, so the missing signature is expected. Signer assertions before signing: every field above equals the bound args; nonce == decision_ref; the verdict is one of ${JSON.stringify(args.proceed_on)} and younger than the configured maximum age.`,
    evidence
      ? `Evidence supplied by the payer's own systems (asserted, not independently verified by the reviewer; its sha256(JCS) is bound into this verdict as evidence_sha256=${args.evidence_sha256}): ${canonicalize(evidence)}`
      : 'No evidence was supplied: nothing here ties the recipient to a known counterparty, an obligation or a policy decision.',
  ].join('\n\n');
}

export function createVerdictGate(cfg: VerdictGateConfig = {}) {
  const baseUrl = cfg.baseUrl ?? DEFAULT_BASE_URL;
  const proceedOn = cfg.proceedOn ?? ['approve', 'approve_with_concerns'];
  const failMode = cfg.failMode ?? 'closed';
  const maxAge = cfg.maxVerdictAgeSeconds ?? 120;
  const now = cfg.now ?? (() => Math.floor(Date.now() / 1000));
  const f = cfg.fetch ?? fetch;

  function bindArgs(intent: PaymentIntent): BoundArgs {
    const chain = `eip155:${intent.chainId}`;
    const token = intent.token ?? USDC_CONTRACTS[chain];
    if (!token) throw new Error(`no USDC contract known for ${chain}; pass intent.token`);
    const t = now();
    return {
      chain, token, from: intent.from, to: intent.to, amount_atomic: BigInt(intent.amountAtomic).toString(),
      valid_after: String(intent.validAfter ?? t - 60),
      valid_before: String(intent.validBefore ?? t + (cfg.authTtlSeconds ?? 600)),
      nonce_rule: NONCE_RULE, proceed_on: proceedOn,
      ...(cfg.accountableParty ? { accountable_party: cfg.accountableParty } : {}),
      ...(intent.purpose ? { purpose: intent.purpose } : {}),
    };
  }

  const unavailable = (reason: string, args: BoundArgs): GateDecision =>
    failMode === 'open'
      ? { allowed: true, failOpen: true, reason: `reviewer unavailable (${reason}); allowed because failMode is 'open'`, args }
      : { allowed: false, reason: `reviewer unavailable (${reason}); blocked because failMode is 'closed'`, args };

  /** Decide on a payment from an already-obtained /review response (no network). Exposed for tests and replays. */
  function decide(review: any, args: BoundArgs): GateDecision {
    const res = review?.result ?? review;
    const proofBlock = res?.proof ?? review?.proof;
    const event: ProofEvent | undefined = proofBlock?.event ?? proofBlock;
    if (!event || typeof event !== 'object' || !('sig' in event)) {
      return { ...unavailable('response carried no signed proof', args), review };
    }
    const proof = verifyVerdictProof(event, { pubkey: cfg.pubkey, args, tool: GATE_TOOL });
    const base = { verdict: proof.verdict, confidence: res?.confidence, summary: res?.summary, event, proof, args, review };
    if (!proof.valid) {
      const failed = Object.entries(proof.checks).filter(([, v]) => !v).map(([k]) => k);
      return { ...base, allowed: false, reason: `proof failed local verification: ${failed.join(', ') || proof.error}` };
    }
    if (!proof.verdict || !proceedOn.includes(proof.verdict)) {
      return { ...base, allowed: false, reason: `verdict '${proof.verdict}' is not in proceedOn ${JSON.stringify(proceedOn)}` };
    }
    const age = now() - Number(proof.verifiedAt);
    if (!(age <= maxAge)) {
      return { ...base, allowed: false, reason: `verdict is ${age}s old (max ${maxAge}s)` };
    }
    return { ...base, allowed: true, reason: `verdict '${proof.verdict}' verified offline`, nonce: executionNonce(proof.decisionRef!) };
  }

  /** Pre-sign check. Call after the PolicyEngine allows the payment and before the key signs. */
  async function check(intent: PaymentIntent): Promise<GateDecision> {
    let args = bindArgs(intent);
    if (cfg.reviewAboveAtomic !== undefined && BigInt(args.amount_atomic) < BigInt(cfg.reviewAboveAtomic)) {
      return { allowed: true, skipped: true, reason: `below the review threshold of ${cfg.reviewAboveAtomic} atomic units`, args };
    }
    let evidence: PaymentEvidence | undefined;
    try {
      evidence = intent.evidence ?? (await cfg.evidence?.(intent));
    } catch (e) {
      return { allowed: false, reason: `evidence resolver failed: ${(e as Error).message}`, args };
    }
    if (evidence) args = { ...args, evidence_sha256: argsHash(evidence) };
    const body = {
      artifact: buildArtifact(args, intent.chainId, evidence),
      artifact_type: 'onchain_action',
      sign: true,
      action_binding: { tool: GATE_TOOL, agent_id: cfg.agentId ?? 'qbtlabs-x402-agent', args },
      severity_threshold: cfg.severityThreshold ?? 'medium',
      confidentiality_tier: 'partial_disclosure',
      disclosed_summary: `x402 payment ${Number(args.amount_atomic) / 1e6} USDC to ${args.to} on ${args.chain}`,
      ...(cfg.context ? { context: cfg.context } : {}),
    };
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), cfg.timeoutMs ?? 120_000);
    let review: unknown;
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (cfg.apiKey) headers.Authorization = `Bearer ${cfg.apiKey}`;
      const res = await f(`${baseUrl}/review`, { method: 'POST', headers, body: JSON.stringify(body), signal: ctrl.signal });
      if (!res.ok) return unavailable(`/review returned HTTP ${res.status}`, args);
      review = await res.json();
    } catch (e) {
      return unavailable((e as Error).name === 'AbortError' ? 'timeout' : (e as Error).message, args);
    } finally {
      clearTimeout(timer);
    }
    return decide(review, args);
  }

  /**
   * Post-settlement: prove the settled transfer carried this verdict.
   * With `rpcUrl` (or `receipt`) it runs fully offline against the chain; otherwise it calls /verify-execution.
   */
  async function verifyExecution(
    decision: GateDecision,
    txHash: string,
    opts: { rpcUrl?: string; receipt?: Parameters<typeof verifyExecutionLocal>[2] } = {},
  ): Promise<ExecutionVerification> {
    if (!decision.event || !decision.args) throw new Error('decision has no verdict to check against');
    if (opts.receipt || opts.rpcUrl) {
      const receipt = opts.receipt ?? (await fetchReceipt(opts.rpcUrl!, txHash, f));
      if (!receipt) throw new Error('transaction not found (not mined yet, or wrong chain)');
      return verifyExecutionLocal(decision.event, decision.args, receipt, { pubkey: cfg.pubkey });
    }
    return verifyExecutionRemote(decision.event, decision.args, txHash, { baseUrl, fetch });
  }

  /**
   * Adapter for the isolated signer: `new SignerServer({ ..., preSign: gate.asPreSign() })`.
   * `onDecision` receives every decision (keep it: verifyExecution needs it after settlement).
   */
  function asPreSign(opts: { purpose?: string; evidence?: PaymentIntent['evidence']; onDecision?: (d: GateDecision) => void } = {}) {
    return async (p: { to: string; amount: string; chainId: number; from: string; validAfter?: number; validBefore?: number }) => {
      const d = await check({
        chainId: p.chainId, from: p.from, to: p.to, amountAtomic: p.amount,
        validAfter: p.validAfter || undefined, validBefore: p.validBefore || undefined, purpose: opts.purpose, evidence: opts.evidence,
      });
      opts.onDecision?.(d);
      if (!d.allowed) return { allowed: false, reason: d.reason };
      if (d.failOpen || d.skipped || !d.nonce || !d.args) return { allowed: true, reason: d.reason };
      return { allowed: true, reason: d.reason, nonce: d.nonce, validAfter: Number(d.args.valid_after), validBefore: Number(d.args.valid_before) };
    };
  }

  return { check, decide, bindArgs, verifyExecution, asPreSign, config: { baseUrl, proceedOn, failMode, maxAge } };
}

export type VerdictGate = ReturnType<typeof createVerdictGate>;
