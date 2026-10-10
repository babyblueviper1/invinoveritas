/**
 * @qbtlabs/x402/verdict: optional invinoveritas verdict gate.
 * An independent, signed verdict bound to the exact EIP-3009 fields before signing, and a check after settlement
 * that the settled transfer carried that verdict.
 */

export { createVerdictGate, DEFAULT_BASE_URL, GATE_TOOL } from './gate.js';
export type { VerdictGate, VerdictGateConfig, PaymentIntent, PaymentEvidence, BoundArgs, GateDecision } from './gate.js';
export { verifyVerdictProof, executionNonce, argsHash, nostrEventId, INVINOVERITAS_PUBKEY } from './proof.js';
export type { ProofEvent, ProofVerification, ProofChecks, Verdict } from './proof.js';
export { verifyExecutionLocal, verifyExecutionRemote, fetchReceipt } from './execution.js';
export type { ExecutionVerification, ExecutionArgs, TxReceipt, TxLog } from './execution.js';
export { signGatedAuthorization } from './sign.js';
export { createVerdictPaymentFetch } from './fetch.js';
export type { VerdictPaymentFetchOptions } from './fetch.js';
export { canonicalize } from './jcs.js';
