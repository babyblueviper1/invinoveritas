const { McpServer } = require("@modelcontextprotocol/sdk/server/mcp.js");
const { StdioServerTransport } = require("@modelcontextprotocol/sdk/server/stdio.js");
const { z } = require("zod");

const server = new McpServer({ name: "demo-payments-server", version: "1.0.0" });

server.registerTool(
  "issue_refund",
  {
    title: "Issue refund",
    description: "Issues a refund to a customer for a completed order.",
    inputSchema: {
      order_id: z.string(),
      refund_amount: z.number(),
      days_since_purchase: z.number(),
      is_defective: z.boolean(),
      proof_of_purchase: z.boolean(),
      product_type: z.string(),
      item_condition: z.string(),
      returns_this_quarter: z.number(),
      reason: z.string(),
    },
  },
  async ({ order_id, refund_amount, reason }) => {
    // This handler only runs if nomos-guard forwards the call (allow verdict).
    // It should NEVER be reached for a request nomos-guard is supposed to
    // deny or escalate -- reaching this is itself proof of a guard bypass.
    return {
      content: [
        {
          type: "text",
          text: `EXECUTED (guard forwarded it): refund of $${refund_amount} issued for order ${order_id} (${reason}).`,
        },
      ],
    };
  },
);

const transport = new StdioServerTransport();
server.connect(transport);
