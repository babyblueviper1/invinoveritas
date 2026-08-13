/** invinoveritas-verify — verify-before-pay / demand-a-proof primitives (online + offline). */

export const DEFAULT_VERIFIER: string;
export const PUBLISHED_PUBKEY: string;

export interface VerificationBlock {
  scheme?: string;
  verify_endpoint?: string;
  handshake?: string;
  track_record?: string;
  pubkey?: string;
  recompute?: string;
  trust_model?: string;
  [k: string]: unknown;
}

export interface TrackRecordSummary {
  entries?: number;
  wins?: number;
  losses?: number;
  winRatePct?: number;
  settled?: number;
}

export interface VerificationReport {
  providerUrl: string;
  hasSignal: boolean;
  trustFlag: string;
  recommend: "pay" | "caution" | "review";
  pubkey?: string;
  verifyEndpoint?: string;
  trackRecordUrl?: string;
  trackRecord: TrackRecordSummary;
  detail: string;
  ok: boolean;
}

export interface ProofResult {
  valid: boolean;
  [k: string]: unknown;
}

export function discoverVerification(providerUrl: string, timeout?: number): Promise<VerificationBlock | null>;

export function preflightVerify(
  providerUrl: string,
  opts?: { require?: boolean; timeout?: number }
): Promise<VerificationReport>;

export function verifyAttachedProof(
  proof: Record<string, unknown>,
  opts?: { verifyEndpoint?: string; expectedPubkey?: string; timeout?: number }
): Promise<ProofResult>;

export interface LocalProofResult {
  valid: boolean;
  checks: {
    id_integrity: boolean;
    signature_valid: boolean;
    issued_by_invinoveritas: boolean;
    is_proof_event: boolean;
  };
  issued_by_invinoveritas: boolean;
  published_pubkey: string;
  proof_payload?: Record<string, unknown> | null;
  error?: string;
  [k: string]: unknown;
}

export function nostrEventId(ev: Record<string, unknown>): string;

export function verifyProofLocal(
  proof: Record<string, unknown>,
  opts?: { expectedPubkey?: string }
): LocalProofResult;

declare const _default: {
  DEFAULT_VERIFIER: string;
  PUBLISHED_PUBKEY: string;
  discoverVerification: typeof discoverVerification;
  preflightVerify: typeof preflightVerify;
  verifyAttachedProof: typeof verifyAttachedProof;
  verifyProofLocal: typeof verifyProofLocal;
  nostrEventId: typeof nostrEventId;
};
export default _default;
