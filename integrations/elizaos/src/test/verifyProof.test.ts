import { test } from "node:test";
import assert from "node:assert/strict";
import { schnorr } from "@noble/curves/secp256k1.js";
import { sha256 } from "@noble/hashes/sha2.js";
import { callVerifyProof, callReview } from "../client.js";

/**
 * Real tests requested by lalalune's review of elizaOS/eliza#9090 (2026-08-13): forged proofs,
 * endpoint substitution, malformed responses, timeouts, unavailable-review behavior, and the
 * actual cryptographic trust boundary. Each test exercises real math (real schnorr signatures),
 * not mocked crypto -- the whole point is proving the trust boundary is genuine.
 */

function buildSignedEvent(privKeyHex: string, overrides: Partial<Record<string, unknown>> = {}) {
  const privKey = Uint8Array.from(Buffer.from(privKeyHex, "hex"));
  const pubkey = Buffer.from(schnorr.getPublicKey(privKey)).toString("hex");
  const created_at = Math.floor(Date.now() / 1000);
  const kind = 30078;
  const tags = [["schema", "invinoveritas.verdict_proof.v1"]];
  const content = JSON.stringify({ schema: "invinoveritas.verdict_proof.v1", verdict: "approve" });
  const base = { pubkey, created_at, kind, tags, content, ...overrides };
  const serial = JSON.stringify([0, String(base.pubkey).toLowerCase(), Number(base.created_at),
    Number(base.kind), base.tags, String(base.content)]);
  const idBytes = sha256(new TextEncoder().encode(serial));
  const id = Buffer.from(idBytes).toString("hex");
  const sig = Buffer.from(schnorr.sign(idBytes, privKey)).toString("hex");
  return { id, ...base, sig };
}

test("cryptographic trust boundary: a genuine signature under a FRESH (non-published) key is REJECTED", async () => {
  // This is the exact forgery class this fix exists to close: real, mathematically valid
  // signature, wrong key. A verifier that only checks "does the signature verify" (the bug
  // lalalune found) would wrongly accept this.
  const attackerKey = "ab".repeat(32);
  const forged = buildSignedEvent(attackerKey);
  const r = await callVerifyProof(forged);
  assert.equal(r.method, "local");
  assert.equal((r as any).checks.signature_valid, true, "the signature itself IS genuinely valid");
  assert.equal((r as any).checks.issued_by_invinoveritas, false, "but the key is not ours");
  assert.equal(r.valid, false, "so the overall verdict must be false");
});

test("malformed proof (missing required fields) fails closed with an error, not a crash", async () => {
  const r = await callVerifyProof({ pubkey: "abc", sig: "def" } as any);
  assert.equal(r.valid, false);
  assert.ok(r.error, "must report why, not just false");
});

test("tampered content after signing invalidates id_integrity (content swapped post-signature)", async () => {
  const attackerKey = "cd".repeat(32);
  const signed = buildSignedEvent(attackerKey);
  const tampered = { ...signed, content: JSON.stringify({ schema: "invinoveritas.verdict_proof.v1", verdict: "reject" }) };
  const r = await callVerifyProof(tampered);
  assert.equal((r as any).checks.id_integrity, false, "recomputed id no longer matches the claimed id");
  assert.equal(r.valid, false);
});

test("positive case: a genuine event under the real published key verifies fully local, zero network calls", async () => {
  // Real sample proof shipped with invinoveritas-verify (sdk/ts/sample_proof.json) -- genuinely
  // signed under the actual published verifier_pubkey, not a synthetic fixture. Added per
  // lalalune's round-3 review of PR #9090: prior tests only proved rejection paths (forged key,
  // tampered content), never a positive "this really works" case.
  const SAMPLE = {
    id: "68378998c57cc5b12b0e82cd1def49cc0a1d0130e6db5b85837419b048f3e422",
    pubkey: "6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7",
    created_at: 1781569676,
    kind: 30078,
    tags: [["d", "invinoveritas-proof-proof-1781569676-ddd67438"], ["t", "invinoveritas"],
      ["t", "proof"], ["schema", "invinoveritas.content_attestation.v1"]],
    content: "{\"attests\":\"Sample proof \\u2014 verify it to confirm invinoveritas's signing key, trust nothing.\",\"content_type\":\"handshake_sample\",\"issued_at\":1781569676,\"platform\":\"invinoveritas\",\"schema\":\"invinoveritas.content_attestation.v1\",\"verifier_pubkey\":\"6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7\",\"verify_how\":\"POST this proof's signed `event` to verify_url, OR run NIP-01 yourself: recompute the Nostr event id = sha256([0,pubkey,created_at,kind,tags,content]), verify the schnorr signature against verifier_pubkey. valid \\u21d2 invinoveritas issued this verdict. No trust required.\",\"verify_url\":\"https://api.babyblueviper.com/verify-proof\"}",
    sig: "ac802c627f37303483c512d60293b9f7af090c343067312e34493a05c692e8832b0c1294fc96e115216d02a144e5e05ab2db89c0d408d490bf458b4f829146aa",
  };
  const realFetch = global.fetch;
  global.fetch = (async () => {
    throw new Error("verifyProofLocal must never call fetch -- a network call here means the local path is broken");
  }) as typeof fetch;
  try {
    const r = await callVerifyProof(SAMPLE);
    assert.equal(r.method, "local");
    assert.equal(r.valid, true);
    assert.equal((r as any).checks.id_integrity, true);
    assert.equal((r as any).checks.signature_valid, true);
    assert.equal((r as any).checks.issued_by_invinoveritas, true);
  } finally {
    global.fetch = realFetch;
  }
});

test("positive case: proofId-only path fetches then verifies the same genuine event, method=fetched_then_local", async () => {
  const SAMPLE = {
    id: "68378998c57cc5b12b0e82cd1def49cc0a1d0130e6db5b85837419b048f3e422",
    pubkey: "6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7",
    created_at: 1781569676,
    kind: 30078,
    tags: [["d", "invinoveritas-proof-proof-1781569676-ddd67438"], ["t", "invinoveritas"],
      ["t", "proof"], ["schema", "invinoveritas.content_attestation.v1"]],
    content: "{\"attests\":\"Sample proof \\u2014 verify it to confirm invinoveritas's signing key, trust nothing.\",\"content_type\":\"handshake_sample\",\"issued_at\":1781569676,\"platform\":\"invinoveritas\",\"schema\":\"invinoveritas.content_attestation.v1\",\"verifier_pubkey\":\"6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7\",\"verify_how\":\"POST this proof's signed `event` to verify_url, OR run NIP-01 yourself: recompute the Nostr event id = sha256([0,pubkey,created_at,kind,tags,content]), verify the schnorr signature against verifier_pubkey. valid \\u21d2 invinoveritas issued this verdict. No trust required.\",\"verify_url\":\"https://api.babyblueviper.com/verify-proof\"}",
    sig: "ac802c627f37303483c512d60293b9f7af090c343067312e34493a05c692e8832b0c1294fc96e115216d02a144e5e05ab2db89c0d408d490bf458b4f829146aa",
  };
  const realFetch = global.fetch;
  global.fetch = (async () => {
    return { ok: true, json: async () => ({ event: SAMPLE }) } as Response;
  }) as typeof fetch;
  try {
    const r = await callVerifyProof(undefined, "some-proof-id");
    assert.equal(r.method, "fetched_then_local");
    assert.equal(r.valid, true);
    assert.equal((r as any).checks.issued_by_invinoveritas, true);
  } finally {
    global.fetch = realFetch;
  }
});

test("proofId-only path: endpoint substitution via INVINO_INDEPENDENT_NODE is honored, not silently ignored", async () => {
  const calls: string[] = [];
  const realFetch = global.fetch;
  global.fetch = (async (url: string) => {
    calls.push(String(url));
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  }) as typeof fetch;
  try {
    process.env.INVINO_INDEPENDENT_NODE = "https://independent-node.example.com";
    const r = await callVerifyProof(undefined, "some-proof-id");
    assert.equal(r.method, "fetched_then_local");
    assert.ok(calls[0]?.startsWith("https://independent-node.example.com/"),
      `expected the independent node to be called, got: ${calls[0]}`);
    assert.equal(r.valid, false, "a 404 fetch must fail closed");
  } finally {
    global.fetch = realFetch;
    delete process.env.INVINO_INDEPENDENT_NODE;
  }
});

test("malformed fetch response (no `event` field) fails closed with a clear error", async () => {
  const realFetch = global.fetch;
  global.fetch = (async () => ({ ok: true, status: 200, json: async () => ({ unrelated: true }) } as Response)) as typeof fetch;
  try {
    const r = await callVerifyProof(undefined, "some-proof-id");
    assert.equal(r.valid, false);
    assert.match(r.error || "", /no `event` field/);
  } finally {
    global.fetch = realFetch;
  }
});

test("fetch failure/timeout is caught and reported, never thrown into the agent's main flow", async () => {
  const realFetch = global.fetch;
  global.fetch = (async () => { throw new Error("network unreachable"); }) as typeof fetch;
  try {
    const r = await callVerifyProof(undefined, "some-proof-id");
    assert.equal(r.valid, false);
    assert.equal(r.method, "fetched_then_local");
    assert.ok(r.error);
  } finally {
    global.fetch = realFetch;
  }
});

test("neither event nor proofId supplied: clear error, no network call attempted", async () => {
  const realFetch = global.fetch;
  let called = false;
  global.fetch = (async () => { called = true; return { ok: false, status: 400, json: async () => ({}) } as Response; }) as typeof fetch;
  try {
    const r = await callVerifyProof();
    assert.equal(r.valid, false);
    assert.equal(called, false, "must not make any network call with nothing to verify");
  } finally {
    global.fetch = realFetch;
  }
});

test("review action degrades to review_unavailable when no API key is configured (advisory, never throws)", async () => {
  const r = await callReview({ artifact: "test", artifactType: "general" }, undefined);
  assert.equal(r.verdict, "review_unavailable");
  assert.ok(r.reason);
});

test("review action returns review_unavailable (not a throw) when the endpoint is unreachable", async () => {
  const realFetch = global.fetch;
  global.fetch = (async () => { throw new Error("timeout"); }) as typeof fetch;
  try {
    const r = await callReview({ artifact: "test", artifactType: "general" }, "fake-api-key");
    assert.equal(r.verdict, "review_unavailable");
  } finally {
    global.fetch = realFetch;
  }
});
