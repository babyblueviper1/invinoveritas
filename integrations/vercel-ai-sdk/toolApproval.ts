/**
 * invinoveritasToolApproval -- a `toolApproval` function for the Vercel AI SDK's
 * ToolLoopAgent / generateText / streamText, wired to an independent /review judgment
 * call instead of a deterministic policy engine.
 *
 * WHY THIS EXISTS (verified against the SDK's own current docs + source, not assumed):
 *
 * The AI SDK's `toolApproval` callback already supports four outcomes --
 * 'not-applicable' | 'approved' | 'denied' | 'user-approval' -- and the docs
 * (content/docs/03-agents/06-tool-approvals.mdx) explicitly show it as an async function of
 * (input, { runtimeContext }) that can return 'approved'/'denied' automatically. The SDK
 * team's own reference composition for automatic decisions is `@ai-sdk/policy-opa`
 * (packages/policy-opa) -- an OPA/Rego adapter: "Write your 'what can this agent do?' rules
 * in a .rego file... evaluated by OPA." That is a DETERMINISTIC rule engine -- boolean
 * expressions over known fields, structurally incapable of a judgment call ("is this
 * specific, novel, multi-step action actually sound, given context an author never
 * anticipated"). The exact same deterministic/judgment split we found in
 * perplexityai/numbat's CEL rule engine (see BIG_SYSTEMS_TARGET_LIST.md target #8).
 *
 * A real user (see vercel/ai#15842) hit this distinction directly -- they wanted
 * "programmatic, server-side policy enforcement based on runtime state" and were pointed at
 * `toolApproval` + `policy-opa`; nothing in that thread, or in the tool-approvals docs, shows
 * an example composing `toolApproval` with an LLM-based / judgment-based verifier as a
 * COMPLEMENT to (not a replacement for) deterministic OPA policy. This module is that
 * reference implementation: it is 100% built on the SDK's existing PUBLIC toolApproval
 * contract -- no SDK changes needed, nothing experimental, nothing that conflicts with
 * `@ai-sdk/policy-opa` (the two compose: run OPA first for hard deterministic rules, fall
 * through to this for the "OPA says maybe, get a real second opinion" case).
 *
 * Pattern (same "escalate only when uncertain" composition already shipped for
 * AgentScope's on_check_permission middleware, Qwen-Agent's PythonExecutor confirm_callback,
 * and LlamaIndex's InputRequiredEvent/HumanResponseEvent gate -- see targets #10, #11, #18):
 *   - clean, high-confidence `approve`        -> 'approved' (reason carries the verdict summary)
 *   - `reject`                                 -> { type: 'denied', reason: summary }
 *   - `approve_with_concerns`, low confidence, -> 'user-approval' (falls through to the SDK's
 *     or the gate itself unavailable (fail-closed)  own human-in-the-loop UI, unchanged)
 *
 * Fail-open discipline matches every other invinoveritas integration: a network error,
 * timeout, or unfunded key resolves to 'not-applicable' (tool runs normally) by default --
 * this is a second opinion, not a single point of failure. Pass failClosed: true for
 * genuinely irreversible tools where "gate unavailable" should escalate to a human instead.
 *
 * npm i invinoveritas-governance-gate-core   (published, MIT, framework-agnostic /review client)
 */
import { reviewAction, type GovernanceGateConfig } from "invinoveritas-governance-gate-core";

export type ToolApprovalStatus =
  | "not-applicable"
  | "approved"
  | { type: "approved"; reason?: string }
  | { type: "denied"; reason?: string }
  | "user-approval";

export interface InvinoveritasToolApprovalOptions extends GovernanceGateConfig {
  /** Confidence threshold for auto-approving a clean 'approve' verdict without a human. Default 0.9. */
  approveConfidence?: number;
  /** Escalate to 'user-approval' (instead of silently allowing) when the gate itself is unavailable. Default false. */
  failClosed?: boolean;
  /** Static artifact_type sent to /review. Default "general" -- pass "shell_command" / "onchain_action" etc. per tool for a sharper verdict. */
  artifactType?: string;
}

/**
 * Build a generic `toolApproval` function (the `GenericToolApprovalFunction` shape the SDK
 * docs describe) that calls /review for every tool call and maps the verdict onto the SDK's
 * own ToolApprovalStatus contract.
 */
export function invinoveritasToolApproval(opts: InvinoveritasToolApprovalOptions) {
  return async ({
    toolCall,
  }: {
    toolCall: { toolName: string; toolCallId: string; input: unknown; dynamic?: boolean };
  }): Promise<ToolApprovalStatus> => {
    const result = await reviewAction(
      {
        artifact: JSON.stringify({ tool: toolCall.toolName, input: toolCall.input }),
        artifactType: opts.artifactType ?? "general",
        context: `Vercel AI SDK toolApproval gate for tool "${toolCall.toolName}" (call ${toolCall.toolCallId}).`,
      },
      { ...opts, failMode: opts.failClosed ? "escalate" : "open" },
    );

    switch (result.decision) {
      case "ALLOW":
        if (result.verdict === "review_unavailable") {
          // failMode="open" resolved unavailability to ALLOW -- don't claim a verdict we don't have.
          return "not-applicable";
        }
        return {
          type: "approved",
          reason: `invinoveritas /review: ${result.verdict} (confidence ${result.confidence ?? "n/a"}) -- ${result.summary ?? ""}`,
        };
      case "BLOCK":
        return { type: "denied", reason: result.summary ?? result.reason ?? "Rejected by invinoveritas /review." };
      case "ESCALATE":
      default:
        return "user-approval";
    }
  };
}
