/**
 * invinoveritas x Crossmint — a real, working wrapper around Crossmint's agent-wallet
 * send() call that gets an independent judgment BEFORE the money moves.
 *
 * Why this exists: Crossmint's own agent-wallet controls (checked verbatim against their
 * docs, 2026-08-29) are entirely STATIC -- a spend cap + reset interval, a recipient
 * whitelist, an expiry timestamp, all validated once at signing time
 * (docs.crossmint.com/wallets/guides/signers/scopes.md: "Scopes are checked before the
 * transaction is broadcast onchain"). Their webhooks are documented as post-hoc
 * notifications only ("fire when these operations complete"). There is no point in their
 * stack where a SPECIFIC transaction gets a real-time judgment call -- an agent with a
 * $10,000/day cap and an approved recipient can send that $10,000 to a manipulated
 * invoice, and nothing in Crossmint's system asks "does this specific payment make sense"
 * before it fires irreversibly.
 *
 * This wrapper adds exactly that: one call to invinoveritas /review before Crossmint's
 * own wallet.send() -- the single call in their entire documented agent-wallet flow that
 * actually moves money (see docs.crossmint.com/agents/payment-methods/stablecoin-wallets/
 * on-chain-actions.md; there is no separate prepare/broadcast split in their current API,
 * so this is the one real integration seam).
 *
 * Independent integration recipe. Not affiliated with or endorsed by Crossmint.
 */
"use server";

import { createCrossmint, CrossmintWallets } from "@crossmint/wallets-sdk";

const INVINO_API = process.env.INVINO_API_BASE ?? "https://api.babyblueviper.com";

type ReviewVerdict = "approve" | "approve_with_concerns" | "reject";

interface ReviewIssue {
  severity: string;
  title?: string;
  description?: string;
}

interface ReviewResult {
  verdict: ReviewVerdict;
  confidence: number;
  summary: string;
  issues: ReviewIssue[];
  proof?: unknown; // present when sign:true -- a portable, independently-verifiable proof;
                    // confirm it via POST /verify-proof (free, no auth) before trusting a
                    // cached copy of this result
}

async function reviewBeforeSend(params: {
  recipient: string;
  token: string;
  amount: string;
  memo: string;
  context: string;
}): Promise<ReviewResult> {
  const res = await fetch(`${INVINO_API}/review`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${process.env.INVINO_API_KEY}`,
    },
    body: JSON.stringify({
      artifact:
        `Crossmint agent wallet send: transfer ${params.amount} ${params.token} ` +
        `to ${params.recipient}, memo: ${params.memo}`,
      artifact_type: "onchain_action",
      context: params.context,
      concerns:
        "Does this recipient/amount/memo look coherent, or does it show signs of a " +
        "manipulated invoice, address substitution, or an amount anomaly?",
      sign: true,
    }),
  });
  if (!res.ok) {
    throw new Error(`invinoveritas /review failed: HTTP ${res.status}`);
  }
  return res.json();
}

/**
 * Drop-in replacement for a bare Crossmint wallet.send() call. Same signature shape as
 * Crossmint's own documented sendUsdxmFromServer() example, plus the two fields /review
 * needs (memo + context) so the judgment call has something real to reason about.
 */
export async function reviewedSend({
  walletAddress,
  recipient,
  token,
  amount,
  memo,
  context,
  onConcern,
}: {
  walletAddress: string;
  recipient: string;
  token: string;
  amount: string;
  memo: string;
  /** What this payment is for, why now, what the agent's authorized scope looks like --
   *  the more real detail here, the more useful the judgment call. */
  context: string;
  /** Optional hook for routing approve_with_concerns to a human/queue instead of
   *  auto-proceeding. Defaults to logging and proceeding. */
  onConcern?: (review: ReviewResult) => void | Promise<void>;
}) {
  // 1) Independent judgment BEFORE the irreversible action.
  const review = await reviewBeforeSend({ recipient, token, amount, memo, context });

  if (review.verdict === "reject") {
    throw new Error(
      `invinoveritas REJECTED this transfer (confidence ${review.confidence}): ${review.summary}\n` +
        review.issues
          .map((i) => `  - [${i.severity}] ${i.title ?? i.description}`)
          .join("\n")
    );
  }

  if (review.verdict === "approve_with_concerns") {
    if (onConcern) {
      await onConcern(review);
    } else {
      console.warn(
        `invinoveritas: approve_with_concerns (confidence ${review.confidence}) -- ${review.summary}`
      );
      for (const issue of review.issues) {
        console.warn(`  - [${issue.severity}] ${issue.title ?? issue.description}`);
      }
    }
  }

  // 2) Only now touch Crossmint's own send. Real, verbatim call shape from their docs
  //    (docs.crossmint.com/agents/payment-methods/stablecoin-wallets/on-chain-actions.md).
  const crossmint = createCrossmint({ apiKey: process.env.CROSSMINT_SERVER_SIDE_API_KEY });
  const wallets = CrossmintWallets.from(crossmint);
  const wallet = await wallets.getWallet(walletAddress, { chain: "base-sepolia" });
  await wallet.useSigner({ type: "server", secret: process.env.CROSSMINT_SIGNER_SECRET });
  const tx = await wallet.send(recipient, token, amount);

  return { hash: tx.hash, explorerLink: tx.explorerLink, review };
}
