import type {
  Action,
  ActionResult,
  IAgentRuntime,
  Memory,
  State,
  HandlerCallback,
} from "@elizaos/core";
import { callVerifyProof } from "../client.js";

/**
 * VERIFY_PROOF — the receiving half of the agent-to-agent trust handshake. FREE, no auth.
 * Recomputes a signed invinoveritas proof another agent handed you against the published key,
 * so you trust neither the presenter nor us — only the math.
 */
export const verifyProofAction: Action = {
  name: "VERIFY_PROOF",
  similes: ["CHECK_PROOF", "INVINOVERITAS_VERIFY_PROOF", "VERIFY_COUNTERPARTY_PROOF"],
  description:
    "Verify a signed invinoveritas proof another agent handed you, before you act on their claim. FREE, no auth, no API key. Pass options.event (the signed proof object — the common case, verified 100% LOCALLY, zero network calls) or options.proofId (fetches the exact proof bytes first, then verifies them the same way locally — the fetch step is honestly reported, never called 'local' on its own). Returns { valid, method: 'local'|'fetched_then_local', checks, ... }.",
  validate: async () => true,
  handler: async (
    _runtime: IAgentRuntime,
    _message: Memory,
    _state?: State,
    options?: { [key: string]: unknown },
    callback?: HandlerCallback,
  ): Promise<ActionResult> => {
    const event = options?.event as Record<string, unknown> | undefined;
    const proofId = options?.proofId as string | undefined;
    const r = await callVerifyProof(event, proofId);
    const methodText = r.method === "local"
      ? "verified 100% locally (BIP-340 schnorr recompute, zero network calls — trust the math, not us)"
      : "bytes fetched, then verified locally (BIP-340 schnorr recompute against the fetched event — the fetch step is not itself a trust guarantee, the signature check is)";
    const text = r.valid
      ? `Proof is VALID — issued by invinoveritas, ${methodText}.`
      : `Proof did NOT verify${r.error ? `: ${r.error}` : "."} (method: ${r.method})`;
    await callback?.({ text, content: r });
    return { text, success: r.valid, data: r, error: r.valid ? undefined : r.error };
  },
  examples: [
    [
      { name: "{{name1}}", content: { text: "Another agent gave me a verdict proof — is it real?" } },
      { name: "{{agent}}", content: { text: "Verifying it against invinoveritas's published key (free, no trust needed).", action: "VERIFY_PROOF" } },
    ],
  ],
};
