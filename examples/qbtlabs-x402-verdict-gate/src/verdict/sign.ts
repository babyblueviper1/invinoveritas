/**
 * Sign the EIP-3009 authorization a verdict allowed, with nonce = decision_ref, refusing any drift from the bound args.
 */

import { signEIP3009 } from '../chains/evm.js';
import type { SignEIP3009Result } from '../types/evm.types.js';
import type { GateDecision } from './gate.js';

export async function signGatedAuthorization(decision: GateDecision, privateKey: string): Promise<SignEIP3009Result> {
  if (!decision.allowed) throw new Error(`verdict gate blocked this payment: ${decision.reason}`);
  if (decision.failOpen || !decision.nonce || !decision.args) {
    throw new Error('no verdict nonce to bind (fail-open decision); sign through your normal path and record it as ungoverned');
  }
  const a = decision.args;
  const chainId = Number(a.chain.split(':')[1]);
  const result = await signEIP3009({
    privateKey, to: a.to, value: BigInt(a.amount_atomic), validAfter: Number(a.valid_after),
    validBefore: Number(a.valid_before), nonce: BigInt(decision.nonce), chainId,
  });
  const z = result.authorization;
  const drift: string[] = [];
  if (z.from.toLowerCase() !== a.from.toLowerCase()) drift.push('from (the key is not the bound payer)');
  if (z.to.toLowerCase() !== a.to.toLowerCase()) drift.push('to');
  if (z.value !== a.amount_atomic) drift.push('value');
  if (z.validAfter !== a.valid_after || z.validBefore !== a.valid_before) drift.push('validity window');
  if (z.nonce.toLowerCase() !== decision.nonce.toLowerCase()) drift.push('nonce');
  if (drift.length) throw new Error(`signed authorization does not match the verdict's bound args: ${drift.join(', ')}`);
  return result;
}
