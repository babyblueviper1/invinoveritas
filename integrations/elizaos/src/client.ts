const DEFAULT_BASE_URL = "https://api.babyblueviper.com";
const DEFAULT_TIMEOUT_MS = 20000;

export function baseUrl(): string {
  return (process.env.INVINO_BASE_URL ?? DEFAULT_BASE_URL).replace(/\/$/, "");
}

async function postJson(
  url: string,
  body: unknown,
  opts: { apiKey?: string; timeoutMs?: number },
): Promise<{ ok: boolean; status: number; data: any }> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  try {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (opts.apiKey) headers["Authorization"] = `Bearer ${opts.apiKey}`;
    const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body), signal: ctrl.signal });
    let data: any = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    return { ok: res.ok, status: res.status, data };
  } finally {
    clearTimeout(t);
  }
}

export interface ReviewInput {
  artifact: string;
  artifactType?: string;
  context?: string;
  sign?: boolean;
}

/** Advisory: always resolves; never throws into the agent's main flow. */
export async function callReview(input: ReviewInput, apiKey?: string): Promise<any> {
  if (!apiKey) {
    return {
      verdict: "review_unavailable",
      reason: 'No INVINO_API_KEY. Get one free: POST https://api.babyblueviper.com/register {"label":"your-app"}.',
    };
  }
  try {
    const { ok, status, data } = await postJson(
      `${baseUrl()}/review`,
      { artifact: input.artifact, artifact_type: input.artifactType ?? "general", context: input.context, sign: input.sign ?? false },
      { apiKey },
    );
    if (!ok || !data || typeof data.verdict !== "string") {
      return { verdict: "review_unavailable", reason: `Review unavailable (HTTP ${status}). Advisory; proceed on your own judgment.` };
    }
    return data;
  } catch {
    return { verdict: "review_unavailable", reason: "Review timed out or errored; advisory, never blocks." };
  }
}

export interface VerifyProofResult {
  valid: boolean;
  method: "local" | "remote" | "fetched_then_local";
  error?: string;
  [key: string]: unknown;
}

/**
 * Verify a signed invinoveritas proof. Two real, distinct paths — the returned `method` field
 * always tells the truth about which one ran (real fix for the trust-boundary misrepresentation
 * lalalune found in review of PR elizaOS/eliza#9090, 2026-08-13: the prior version always POSTed
 * to our own remote /verify-proof and trusted the response, while the user-facing text falsely
 * claimed "verified locally").
 *
 * - `event` supplied (the common real case — one agent hands another the actual proof object):
 *   genuinely LOCAL verification via `invinoveritas-verify`'s `verifyProofLocal` — recomputes the
 *   NIP-01 event id and checks the BIP-340 schnorr signature against the hardcoded published
 *   pubkey, entirely offline. Zero network calls. You are not trusting us, or the presenter —
 *   only the math, for real this time.
 * - `proofId` only (no event bytes in hand): there is no way to verify bytes you don't have —
 *   this path fetches the actual signed event from our `/verify-proof` endpoint (or, if
 *   INVINO_INDEPENDENT_NODE is set, from an independently-run verifier instance instead of us),
 *   THEN verifies it locally the same way. Labeled `fetched_then_local`, never called "local"
 *   outright, since the fetch step still has to be trusted for WHICH bytes it hands back — the
 *   verification math itself still runs locally either way.
 */
export async function callVerifyProof(event?: Record<string, unknown>, proofId?: string): Promise<VerifyProofResult> {
  if (!event && !proofId) {
    return { valid: false, method: "local", error: "Provide `event` (the signed proof object) or `proofId`." };
  }
  const { verifyProofLocal } = await import("invinoveritas-verify");

  if (event) {
    const r = verifyProofLocal(event);
    return { ...r, method: "local" };
  }

  // proofId-only: must fetch the raw bytes from somewhere before any verification is possible.
  // GET /verdict-proofs/{event_id} is the endpoint built specifically to hand over the exact
  // {id,pubkey,created_at,kind,tags,content,sig} for independent third-party recompute -- unlike
  // POST /verify-proof, which returns OUR OWN verdict on the event, not the event itself.
  if (!proofId) return { valid: false, method: "local", error: "Provide `event` or `proofId`." };
  const fetchBase = process.env.INVINO_INDEPENDENT_NODE?.replace(/\/$/, "") || baseUrl();
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), DEFAULT_TIMEOUT_MS);
    let res: Response;
    try {
      res = await fetch(`${fetchBase}/verdict-proofs/${encodeURIComponent(proofId)}`, { signal: ctrl.signal });
    } finally {
      clearTimeout(t);
    }
    if (!res.ok) {
      return { valid: false, method: "fetched_then_local", error: `could not fetch proof bytes for proofId (HTTP ${res.status})` };
    }
    const data = await res.json();
    if (!data?.event) {
      return { valid: false, method: "fetched_then_local", error: "fetch response had no `event` field." };
    }
    const r = verifyProofLocal(data.event);
    return { ...r, method: "fetched_then_local", fetched_from: fetchBase };
  } catch {
    return { valid: false, method: "fetched_then_local", error: "fetching proof bytes timed out or errored." };
  }
}
