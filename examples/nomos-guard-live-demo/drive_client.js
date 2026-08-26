const { Client } = require("@modelcontextprotocol/sdk/client/index.js");
const { StdioClientTransport } = require("@modelcontextprotocol/sdk/client/stdio.js");
const path = require("path");

async function callThroughGuard(artifact, args) {
  const transport = new StdioClientTransport({
    command: "node",
    args: [
      path.join(__dirname, "node_modules", "nomos-guard", "dist", "index.js"),
      "--artifact", artifact,
      "--",
      "node", path.join(__dirname, "payments_server.js"),
    ],
  });
  const client = new Client({ name: "demo-client", version: "1.0.0" });
  await client.connect(transport);
  try {
    const result = await client.callTool({ name: "issue_refund", arguments: args });
    console.log(JSON.stringify(result, null, 2));
  } catch (e) {
    console.log("ERROR:", e.message);
  } finally {
    await client.close();
  }
}

(async () => {
  const testCase = process.argv[2];
  const base = {
    days_since_purchase: 7,
    is_defective: false,
    proof_of_purchase: true,
    product_type: "physical",
    item_condition: "opened_undamaged",
    returns_this_quarter: 0,
  };
  if (testCase === "small") {
    console.log("=== small refund, $89, under every threshold, expect ALLOW (forwarded, executed) ===");
    await callThroughGuard("pub_refund_v1", { ...base, order_id: "ORD-1001", refund_amount: 89, reason: "damaged item" });
  } else if (testCase === "big") {
    console.log("=== large refund, $1500, over the $1000 dual-approval line (R6), expect ESCALATE (blocked, held for approval) ===");
    await callThroughGuard("pub_refund_v1", { ...base, order_id: "ORD-1002", refund_amount: 1500, reason: "not as described" });
  } else if (testCase === "mid") {
    console.log("=== mid refund, $700, over the $500 supervisor line (R7) but under R6, expect ESCALATE ===");
    await callThroughGuard("pub_refund_v1", { ...base, order_id: "ORD-1003", refund_amount: 700, reason: "wrong size" });
  }
})();
