/**
 * A drop-in variant of createPaymentFetch that runs the verdict gate before signing each x402 payment.
 */

import { privateKeyToAccount } from 'viem/accounts';
import { buildPaymentPayloadWithAuthorization, parsePaymentRequired } from '../client.js';
import type { GateDecision, VerdictGate } from './gate.js';
import type { ExecutionVerification } from './execution.js';
import { signGatedAuthorization } from './sign.js';
import { signEIP3009 } from '../chains/evm.js';

export interface VerdictPaymentFetchOptions {
  privateKey: `0x${string}`;
  gate: VerdictGate;
  /** Called with every gate decision (allowed or not). Put it in your audit log. */
  onDecision?: (url: string, decision: GateDecision) => void;
  /** Called once settlement is visible and checked against the verdict. Never blocks the response. */
  onSettled?: (url: string, txHash: string, result: ExecutionVerification | Error) => void;
  /** Passed to gate.verifyExecution: check offline against this RPC instead of calling /verify-execution. */
  rpcUrl?: string;
}

function settlementTx(res: Response): string | undefined {
  const h = res.headers.get('PAYMENT-RESPONSE') ?? res.headers.get('X-PAYMENT-RESPONSE');
  if (!h) return undefined;
  try {
    const j = JSON.parse(Buffer.from(h, 'base64').toString('utf8'));
    return j.transaction ?? j.txHash ?? undefined;
  } catch {
    return undefined;
  }
}

export function createVerdictPaymentFetch(options: VerdictPaymentFetchOptions): typeof fetch {
  const { privateKey, gate, onDecision, onSettled, rpcUrl } = options;
  const from = privateKeyToAccount(privateKey).address;

  return async function verdictPaymentFetch(input: string | URL | Request, init?: RequestInit): Promise<Response> {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : (input as Request).url;
    const first = await fetch(input, init);
    if (first.status !== 402) return first;

    const body = (await first.json().catch(() => null)) as any;
    const req = body ? parsePaymentRequired(body) : null;
    if (!req) throw new Error('Failed to parse payment requirements from 402 response');
    const atomic = body.accepts?.[0]?.maxAmountRequired ?? String(Math.ceil(req.price * 1_000_000));

    const decision = await gate.check({
      chainId: req.chainId, from, to: req.payTo, amountAtomic: atomic,
      purpose: `${init?.method ?? 'GET'} ${url}`,
    });
    onDecision?.(url, decision);
    if (!decision.allowed) throw new Error(`Payment blocked by verdict gate: ${decision.reason}`);

    // Governed: nonce = the verdict's decision_ref. Ungoverned (below threshold, or fail-open): a random nonce, and
    // onDecision has already told the caller that no verdict covers this payment.
    const a = decision.args!;
    const signed = decision.nonce
      ? await signGatedAuthorization(decision, privateKey)
      : await signEIP3009({ privateKey, to: a.to, value: BigInt(a.amount_atomic), validAfter: Number(a.valid_after),
          validBefore: Number(a.valid_before), chainId: req.chainId });
    const headers = new Headers(init?.headers);
    headers.set('X-PAYMENT', buildPaymentPayloadWithAuthorization({ ...signed, chainId: req.chainId }));
    const paid = await fetch(input, { ...init, headers });

    const tx = settlementTx(paid);
    if (tx && onSettled) {
      gate.verifyExecution(decision, tx, { rpcUrl }).then(
        (r) => onSettled(url, tx, r),
        (e) => onSettled(url, tx, e as Error),
      );
    }
    return paid;
  };
}
