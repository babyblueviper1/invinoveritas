/**
 * After settlement: prove a settled payment was governed by a specific prior verdict.
 *
 * Mirrors invinoveritas POST /verify-execution (free, no auth) so you can run it either way:
 *   - verifyExecutionLocal(): offline over a transaction receipt you fetched yourself (any RPC, no trust in us)
 *   - verifyExecutionRemote(): ask invinoveritas to do the same checks (Base mainnet only)
 *
 * Checks: proof_valid, args_bound, nonce_is_verdict (the AuthorizationUsed nonce equals the verdict's decision_ref),
 * authorizer_matches, transfer_matches (Transfer(from, to, value) of args.token), tx_succeeded.
 * It does NOT establish that the reviewer had complete context, that the verdict was correct, or that the payer
 * could not have paid by another route without a verdict. It proves this payment carried this verdict.
 */

import { executionNonce, verifyVerdictProof, type ProofEvent } from './proof.js';

/** The bound args the check needs (a verdict may bind more fields; all of them are hashed, these are also matched on-chain). */
export interface ExecutionArgs { token: string; from: string; to: string; amount_atomic: string; [extra: string]: unknown }

export const TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef';
/** AuthorizationUsed(address indexed authorizer, bytes32 indexed nonce) */
export const AUTH_USED_TOPIC = '0x98de503528ee59b575ef0c0a2576a82497bfc029a5685b209e9ec333479b10a5';

export interface TxLog {
  address: string;
  topics: string[];
  data: string;
}
export interface TxReceipt {
  status: string;
  blockNumber?: string;
  logs: TxLog[];
}

export interface ExecutionVerification {
  valid: boolean;
  checks: {
    proof_valid: boolean;
    args_bound: boolean;
    nonce_is_verdict: boolean;
    authorizer_matches: boolean;
    transfer_matches: boolean;
    tx_succeeded: boolean;
  };
  verdict?: string;
  decision_ref?: string;
  executed_despite_reject: boolean;
  error?: string;
}

const addr = (t: string) => '0x' + t.toLowerCase().slice(-40);

export function verifyExecutionLocal(
  event: ProofEvent,
  args: ExecutionArgs,
  receipt: TxReceipt,
  opts: { pubkey?: string } = {},
): ExecutionVerification {
  const proof = verifyVerdictProof(event, { pubkey: opts.pubkey, args });
  const checks = {
    proof_valid: proof.checks.id_integrity && proof.checks.signature_valid && proof.checks.issued_by_invinoveritas
      && proof.checks.is_proof_event && proof.checks.decision_ref_recomputes,
    args_bound: proof.checks.args_bound === true,
    nonce_is_verdict: false,
    authorizer_matches: false,
    transfer_matches: false,
    tx_succeeded: false,
  };
  const out: ExecutionVerification = {
    valid: false, checks, verdict: proof.verdict, decision_ref: proof.decisionRef, executed_despite_reject: false,
  };
  let want: string;
  try {
    want = executionNonce(proof.decisionRef ?? '');
  } catch (e) {
    return { ...out, error: `proof has no usable decision_ref: ${(e as Error).message}` };
  }
  const token = args.token.toLowerCase();
  const from = args.from.toLowerCase();
  const logs = (receipt.logs ?? []).filter((l) => l.address?.toLowerCase() === token);
  const auth = logs.filter((l) => l.topics?.[0]?.toLowerCase() === AUTH_USED_TOPIC && l.topics.length > 2);
  const xfer = logs.filter((l) => l.topics?.[0]?.toLowerCase() === TRANSFER_TOPIC && l.topics.length > 2);
  checks.tx_succeeded = BigInt(receipt.status ?? '0x0') === 1n;
  checks.nonce_is_verdict = auth.some((l) => l.topics[2].toLowerCase() === want);
  checks.authorizer_matches = auth.some((l) => addr(l.topics[1]) === from);
  checks.transfer_matches = xfer.some(
    (l) => addr(l.topics[1]) === from && addr(l.topics[2]) === args.to.toLowerCase()
      && BigInt(l.data || '0x0') === BigInt(args.amount_atomic),
  );
  out.valid = Object.values(checks).every(Boolean);
  out.executed_despite_reject = out.valid && out.verdict === 'reject';
  return out;
}

/** Fetch a receipt with plain JSON-RPC (no client library). */
export async function fetchReceipt(rpcUrl: string, txHash: string, fetchImpl: typeof fetch = fetch): Promise<TxReceipt | null> {
  const res = await fetchImpl(rpcUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_getTransactionReceipt', params: [txHash] }),
  });
  const body = (await res.json()) as { result?: TxReceipt; error?: unknown };
  if (body.error) throw new Error(`RPC error: ${JSON.stringify(body.error)}`);
  return body.result ?? null;
}

/** Ask invinoveritas to run the same checks (free, no auth). Supported chain: eip155:8453. */
export async function verifyExecutionRemote(
  event: ProofEvent,
  args: ExecutionArgs,
  txHash: string,
  opts: { baseUrl?: string; fetch?: typeof fetch } = {},
): Promise<ExecutionVerification & Record<string, unknown>> {
  const f = opts.fetch ?? fetch;
  const res = await f(`${opts.baseUrl ?? 'https://api.babyblueviper.com'}/verify-execution`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ event, args, tx_hash: txHash }),
  });
  if (!res.ok) throw new Error(`/verify-execution returned ${res.status}: ${(await res.text()).slice(0, 300)}`);
  return (await res.json()) as ExecutionVerification & Record<string, unknown>;
}
