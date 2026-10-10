/**
 * Offline verification of an invinoveritas verdict proof.
 *
 * A verdict proof is a BIP-340 (schnorr) signed Nostr event (NIP-01). Verifying it needs no call to
 * invinoveritas and no trust in whoever handed it to you:
 *   1. id_integrity            sha256([0, pubkey, created_at, kind, tags, content]) equals event.id
 *   2. signature_valid         the schnorr signature over event.id verifies against event.pubkey
 *   3. issued_by_invinoveritas event.pubkey equals the pinned published key
 *   4. is_proof_event          kind 30078 and an `invinoveritas.*` schema
 *   5. decision_ref_recomputes sha256(JCS(preimage)) equals content.decision_ref, where preimage holds every
 *                              field named in content.decision_ref_preimage_fields (absent ones as null)
 *   6. args_bound              (when args are given) sha256(JCS(args)) equals content.action_binding_args_hash
 *   7. tool_bound              (when a tool is given) sha256(tool) equals content.action_binding_tool_hash
 *
 * Uses @noble/curves and @noble/hashes, which @qbtlabs/x402 already depends on.
 */

import { schnorr } from '@noble/curves/secp256k1.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex, hexToBytes } from '@noble/hashes/utils.js';
import { canonicalize } from './jcs.js';

/** invinoveritas's published verifier key (x-only hex). Re-derive: GET https://api.babyblueviper.com/.well-known/agent-handshake */
export const INVINOVERITAS_PUBKEY = '6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7';
export const PROOF_KIND = 30078;

export type Verdict = 'approve' | 'approve_with_concerns' | 'reject';

export interface ProofEvent {
  id: string;
  pubkey: string;
  created_at: number;
  kind: number;
  tags: string[][];
  content: string;
  sig: string;
}

export interface ProofChecks {
  id_integrity: boolean;
  signature_valid: boolean;
  issued_by_invinoveritas: boolean;
  is_proof_event: boolean;
  decision_ref_recomputes: boolean;
  args_bound?: boolean;
  tool_bound?: boolean;
}

export interface ProofVerification {
  valid: boolean;
  checks: ProofChecks;
  verdict?: Verdict;
  decisionRef?: string;
  verifiedAt?: number;
  content?: Record<string, unknown>;
  error?: string;
}

const utf8 = (s: string) => new TextEncoder().encode(s);
export const sha256Hex = (s: string) => bytesToHex(sha256(utf8(s)));

/** sha256(JCS(args)) in the `sha256:<hex>` form invinoveritas binds into a verdict. */
export function argsHash(args: unknown): string {
  return 'sha256:' + sha256Hex(canonicalize(args));
}

export function nostrEventId(ev: ProofEvent): string {
  if (typeof ev.pubkey !== 'string' || !/^[0-9a-f]{64}$/.test(ev.pubkey)) throw new Error('pubkey must be 64 lowercase hex');
  if (!Number.isSafeInteger(ev.created_at) || !Number.isSafeInteger(ev.kind)) throw new Error('created_at and kind must be integers');
  if (!Array.isArray(ev.tags) || typeof ev.content !== 'string') throw new Error('tags must be an array and content a string');
  return sha256Hex(JSON.stringify([0, ev.pubkey, ev.created_at, ev.kind, ev.tags, ev.content]));
}

/**
 * The EIP-3009 nonce that binds a payment authorization to a verdict: the decision_ref digest as bytes32.
 * Because it is a hash over the verdict, an authorization carrying it cannot have been signed before the verdict existed,
 * and the USDC contract's AuthorizationUsed(authorizer, nonce) log records on-chain which verdict the payment carried.
 */
export function executionNonce(decisionRef: string): `0x${string}` {
  const h = (decisionRef.includes(':') ? decisionRef.split(':', 2)[1] : decisionRef).toLowerCase().replace(/^0x/, '');
  if (!/^[0-9a-f]{64}$/.test(h)) throw new Error('decision_ref is not a 32-byte hex digest');
  return `0x${h}`;
}

export function verifyVerdictProof(
  event: ProofEvent,
  opts: { pubkey?: string; args?: unknown; tool?: string } = {},
): ProofVerification {
  const pin = (opts.pubkey ?? INVINOVERITAS_PUBKEY).toLowerCase();
  const checks: ProofChecks = {
    id_integrity: false,
    signature_valid: false,
    issued_by_invinoveritas: false,
    is_proof_event: false,
    decision_ref_recomputes: false,
  };
  const out: ProofVerification = { valid: false, checks };
  if (!event || typeof event !== 'object') return { ...out, error: 'event must be an object' };
  for (const k of ['id', 'pubkey', 'created_at', 'kind', 'content', 'sig'] as const) {
    if (event[k] === undefined || event[k] === null || event[k] === '') return { ...out, error: `missing ${k}` };
  }
  let content: Record<string, unknown> = {};
  try {
    checks.id_integrity = nostrEventId(event) === String(event.id).toLowerCase();
    try {
      checks.signature_valid = schnorr.verify(hexToBytes(event.sig), hexToBytes(event.id), hexToBytes(event.pubkey));
    } catch {
      checks.signature_valid = false;
    }
    checks.issued_by_invinoveritas = event.pubkey.toLowerCase() === pin;
    content = JSON.parse(event.content);
    checks.is_proof_event =
      event.kind === PROOF_KIND && typeof content.schema === 'string' && content.schema.startsWith('invinoveritas.');
    const fields = content.decision_ref_preimage_fields;
    if (Array.isArray(fields) && typeof content.decision_ref === 'string') {
      const preimage: Record<string, unknown> = {};
      for (const f of fields as string[]) preimage[f] = content[f] ?? null;
      checks.decision_ref_recomputes = 'sha256:' + sha256Hex(canonicalize(preimage)) === content.decision_ref;
    }
    if (opts.args !== undefined) checks.args_bound = argsHash(opts.args) === content.action_binding_args_hash;
    if (opts.tool !== undefined) checks.tool_bound = 'sha256:' + sha256Hex(opts.tool) === content.action_binding_tool_hash;
  } catch (e) {
    return { ...out, error: `malformed event: ${(e as Error).message}` };
  }
  out.content = content;
  out.verdict = content.verdict as Verdict;
  out.decisionRef = content.decision_ref as string;
  out.verifiedAt = content.verified_at as number;
  out.valid = Object.values(checks).every(Boolean);
  return out;
}
