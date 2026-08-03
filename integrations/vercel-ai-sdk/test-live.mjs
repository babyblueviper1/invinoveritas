// Live verification for invinoveritasToolApproval -- NOT mocked, calls the real production
// /review API. Requires IVV_API_KEY in the environment (see
// data/secrets_local/llamaindex_review_gate_test_key.txt for a shared low-balance test key,
// or use your own -- POST /register for a free one).
//
// Run: IVV_API_KEY=ivv_... npx tsx test-live.mjs
import { invinoveritasToolApproval } from "./toolApproval.ts";

const apiKey = process.env.IVV_API_KEY;
if (!apiKey) {
  throw new Error("Set IVV_API_KEY to run this live test.");
}

async function run(label, toolName, input, artifactType) {
  const approval = invinoveritasToolApproval({ apiKey, artifactType, timeoutMs: 20000 });
  const status = await approval({
    toolCall: { toolName, toolCallId: `${label}-1`, input },
  });
  console.log(`--- ${label} ---`);
  console.log(JSON.stringify(status, null, 2));
  return status;
}

const benign = await run("benign_ls", "runCommand", { command: "ls -la /tmp" }, "shell_command");
const destructive = await run(
  "destructive_rm",
  "runCommand",
  { command: "rm -rf / --no-preserve-root" },
  "shell_command",
);

if (typeof benign !== "object" || benign.type !== "approved") {
  throw new Error(`Expected benign case to be approved, got: ${JSON.stringify(benign)}`);
}
if (typeof destructive !== "object" || destructive.type !== "denied") {
  throw new Error(`Expected destructive case to be denied, got: ${JSON.stringify(destructive)}`);
}
console.log("\nBoth branches verified against the real API.");
