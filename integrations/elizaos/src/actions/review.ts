import type {
  Action,
  IAgentRuntime,
  Memory,
  State,
  HandlerCallback,
} from "@elizaos/core";
import { callReview, type ReviewInput } from "../client.js";

function messageText(message: Memory): string {
  const c: any = message?.content;
  if (typeof c === "string") return c;
  return (c?.text as string) ?? "";
}

/**
 * VERIFY_BEFORE_ACTING — get an independent, capital/risk-aware verdict before an irreversible action.
 *
 * Improves on a generic reasoning-verifier: with sign=true the verdict comes with a recomputable
 * signed proof (trust the math, not a pipeline); the verifier keeps a public Bitcoin-anchored track
 * record; and it specializes on trades + on-chain actions. Advisory — it never blocks the agent.
 */
export const reviewAction: Action = {
  name: "VERIFY_BEFORE_ACTING",
  similes: ["REVIEW_ACTION", "INVINOVERITAS_REVIEW", "CHECK_BEFORE_TRADE", "VERIFY_ONCHAIN_ACTION", "SECOND_OPINION"],
  description:
    "Before the agent does something irreversible — a trade, an on-chain transaction, a deploy, a destructive command — get an INDEPENDENT verdict (approve | approve_with_concerns | reject) from invinoveritas. Pass options.artifactType='trade' for a capital-scale-aware risk review or 'onchain_action' for deterministic scam/drainer/approval/poisoning checks. With options.sign=true the verdict carries a recomputable signed proof (trust the math, not a pipeline); the verifier keeps a public Bitcoin-anchored track record. Advisory — it informs the agent's own decision, never blocks it and never waits on a human.",
  validate: async (runtime: IAgentRuntime) => {
    return Boolean(runtime.getSetting?.("INVINO_API_KEY") || process.env.INVINO_API_KEY);
  },
  handler: async (
    runtime: IAgentRuntime,
    message: Memory,
    _state?: State,
    options?: { [key: string]: unknown },
    callback?: HandlerCallback,
  ) => {
    const apiKey = (runtime.getSetting?.("INVINO_API_KEY") as string) || process.env.INVINO_API_KEY;
    const input: ReviewInput = {
      artifact: (options?.artifact as string) || messageText(message) || "No action provided",
      artifactType: options?.artifactType as string | undefined,
      context: options?.context as string | undefined,
      sign: Boolean(options?.sign),
    };
    const r = await callReview(input, apiKey);
    const lines = [
      `Verdict: ${r.verdict}${typeof r.confidence === "number" ? ` (confidence ${r.confidence})` : ""}`,
      r.summary ? `Summary: ${r.summary}` : "",
      Array.isArray(r.issues) && r.issues.length ? `Issues: ${r.issues.map((i: any) => i.title ?? i).join("; ")}` : "",
      r.proof ? `Signed proof attached — anyone can recompute it at ${baseUrlHint()}/verify-proof.` : "",
    ].filter(Boolean);
    await callback?.({ text: lines.join("\n"), content: r });
    return r;
  },
  examples: [
    [
      { name: "{{name1}}", content: { text: "I'm about to swap 5 ETH for this token, check it first." } },
      { name: "{{agent}}", content: { text: "Running an invinoveritas review (onchain_action) before you sign.", action: "VERIFY_BEFORE_ACTING" } },
    ],
  ],
};

function baseUrlHint(): string {
  return (process.env.INVINO_BASE_URL ?? "https://api.babyblueviper.com").replace(/\/$/, "");
}
