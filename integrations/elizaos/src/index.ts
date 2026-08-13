import type { Plugin } from "@elizaos/core";
import { reviewAction } from "./actions/review.js";
import { verifyProofAction } from "./actions/verifyProof.js";

/**
 * invinoveritas — the verification layer for AI agents, as an elizaOS plugin.
 *
 * Two actions:
 *  - VERIFY_BEFORE_ACTING — an independent, capital/risk-aware verdict before an irreversible action,
 *    with an optional recomputable signed proof. Advisory; never blocks.
 *  - VERIFY_PROOF — free verification of a proof another agent handed you.
 *
 * Set INVINO_API_KEY (free: POST https://api.babyblueviper.com/register) in the character's secrets.
 */
export const invinoveritasPlugin: Plugin = {
  name: "invinoveritas",
  description:
    "Independent, automated second opinion: a capital/risk-aware verdict the agent requests before an irreversible action (the agent decides — no human in the loop) (with a recomputable signed proof and a public Bitcoin-anchored track record), plus free verification of proofs other agents hand you. Trust the math, not a pipeline.",
  actions: [reviewAction, verifyProofAction],
};

export default invinoveritasPlugin;
export { reviewAction, verifyProofAction };
