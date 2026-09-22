/** Hermetic tests for invinoveritas-verify (mocked fetch) + an optional live smoke.
 *  Run:  node test.mjs           (hermetic)
 *        node test.mjs --live     (also hits the live reference provider)
 */
import assert from "node:assert";
import { readFileSync } from "node:fs";
import {
  preflightVerify, discoverVerification, verifyAttachedProof,
  verifyProofLocal, nostrEventId,
} from "./index.js";

const SAMPLE = JSON.parse(readFileSync(new URL("./sample_proof.json", import.meta.url)));
const clone = (o) => JSON.parse(JSON.stringify(o));

const realFetch = globalThis.fetch;
function mockFetch(routes) {
  globalThis.fetch = async (url, opts) => {
    for (const [match, resp] of routes) {
      if (url.includes(match)) {
        return {
          ok: resp.ok !== false,
          status: resp.status || 200,
          headers: { get: (k) => (resp.headers || {})[k.toLowerCase()] || null },
          json: async () => resp.json || {},
        };
      }
    }
    return { ok: false, status: 404, headers: { get: () => null }, json: async () => ({}) };
  };
}
function restore() { globalThis.fetch = realFetch; }

let passed = 0;
async function test(name, fn) {
  try { await fn(); passed++; console.log("  ✓", name); }
  catch (e) { console.error("  ✗", name, "\n   ", e.message); process.exitCode = 1; }
  finally { restore(); }
}

const BLOCK = {
  scheme: "verdict-proof.v1",
  verify_endpoint: "https://p.example/verify-proof",
  track_record: "https://p.example/ledger",
  pubkey: "abc123",
  recompute: "check each entry's sig against pubkey",
};
const LEDGER = { count: 26, track_record: { wins: 10, losses: 9, win_rate_pct: 52.6, live_trades_closed: 19 } };

await test("verified provider → recommend pay, losses present", async () => {
  mockFetch([["/.well-known/x402", { json: { verification: BLOCK } }], ["/ledger", { json: LEDGER }]]);
  const rep = await preflightVerify("https://p.example");
  assert.equal(rep.hasSignal, true);
  assert.equal(rep.pubkey, "abc123");
  assert.equal(rep.trackRecord.losses, 9);
  assert.equal(rep.recommend, "pay");
  assert.equal(rep.ok, true);
});

await test("no signal → caution + require throws", async () => {
  mockFetch([["/.well-known/x402", { json: {} }], ["/", { json: {} }]]);
  const rep = await preflightVerify("https://nope.example");
  assert.equal(rep.hasSignal, false);
  assert.equal(rep.recommend, "caution");
  await assert.rejects(() => preflightVerify("https://nope.example", { require: true }));
});

await test("discover falls back to handshake header", async () => {
  const hdr = "invinoveritas.verification.v1; verify=https://p.example/verify-proof; ledger=https://p.example/ledger";
  mockFetch([["/.well-known/x402", { json: {} }], ["/", { headers: { "x-verification-handshake": hdr } }]]);
  const block = await discoverVerification("https://p.example");
  assert.ok(block);
  assert.equal(block.verify_endpoint, "https://p.example/verify-proof");
});

await test("verifyAttachedProof catches wrong signer", async () => {
  mockFetch([["/verify-proof", { json: { valid: true } }]]);
  const res = await verifyAttachedProof({ pubkey: "WRONG" }, { expectedPubkey: "EXPECTED" });
  assert.equal(res.valid, false);
  assert.equal(res.expected, "EXPECTED");
});

await test("verifyAttachedProof passes authentic", async () => {
  mockFetch([["/verify-proof", { json: { valid: true } }]]);
  const res = await verifyAttachedProof({ pubkey: "EXPECTED" }, { expectedPubkey: "EXPECTED" });
  assert.equal(res.valid, true);
});

// ── OFFLINE verifier (verifyProofLocal) — no network, real proof fixture ──────────────────────────
await test("offline: real proof verifies (all four checks)", async () => {
  const r = verifyProofLocal(SAMPLE);
  assert.equal(r.valid, true);
  assert.ok(Object.values(r.checks).every(Boolean));
  assert.equal(r.issued_by_invinoveritas, true);
});

await test("offline: content tamper fails id_integrity", async () => {
  const ev = clone(SAMPLE); ev.content = ev.content.slice(0, -2) + "XY";
  const r = verifyProofLocal(ev);
  assert.equal(r.valid, false);
  assert.equal(r.checks.id_integrity, false);
});

await test("offline: sig tamper fails signature_valid", async () => {
  const ev = clone(SAMPLE); ev.sig = ev.sig.slice(0, -2) + (ev.sig.slice(-2) !== "00" ? "00" : "11");
  const r = verifyProofLocal(ev);
  assert.equal(r.valid, false);
  assert.equal(r.checks.signature_valid, false);
});

await test("offline: foreign key not ours", async () => {
  const ev = clone(SAMPLE); ev.pubkey = ev.pubkey.slice(0, -2) + (ev.pubkey.slice(-2) !== "00" ? "00" : "11");
  const r = verifyProofLocal(ev);
  assert.equal(r.valid, false);
  assert.equal(r.checks.issued_by_invinoveritas, false);
});

await test("offline: malformed never throws", async () => {
  for (const bad of [null, {}, { id: "x" }, 42, "s"]) assert.equal(verifyProofLocal(bad).valid, false);
});

await test("offline: event id recompute matches", async () => {
  assert.equal(nostrEventId(SAMPLE).toLowerCase(), String(SAMPLE.id).toLowerCase());
});

await test("offline: strict NIP-01 -- coerced-type fields must not verify", async () => {
  for (const [f, v] of [
    ["created_at", String(SAMPLE.created_at)], ["kind", String(SAMPLE.kind)],
    ["pubkey", SAMPLE.pubkey.toUpperCase()], ["created_at", SAMPLE.created_at + 0.5],
    ["kind", true], ["created_at", null],
  ]) {
    const ev = clone(SAMPLE); ev[f] = v;
    const r = verifyProofLocal(ev);
    assert.equal(r.valid, false, `${f}=${String(v)} verified`);
    assert.equal(r.checks.id_integrity, false);
  }
  assert.equal(verifyProofLocal(SAMPLE).valid, true);
});

await test("offline: KNOWN cross-language divergence -- an integral-valued float literal in created_at is indistinguishable from an int after JSON.parse", async () => {
  // Found by MattyIceMatrix (trustless-ai/recompute-kit#48, testing the PUBLISHED 0.4.1/1.1.2 packages, not just source review):
  // raw JSON `"created_at": 1781569676.0` -- Python's json.loads keeps it a float, so it correctly fails strict-typing and rejects.
  // JS's JSON.parse collapses 1781569676.0 to the plain number 1781569676; Number.isSafeInteger() then passes, and re-serializing
  // it (JSON.stringify) also drops the ".0", so the recomputed hash matches the original signed bytes and this verifies VALID here.
  // Same input bytes, different verdict per language. Impact is low -- the hashed value is identical either way, so nothing forged
  // ever verifies -- but it is a real, disclosed parity gap, not a silent one. Root cause: verifyProofLocal/nostrEventId take an
  // ALREADY-PARSED object; by the time this library sees the value, the raw literal's int-vs-float distinction is already gone.
  // Closing it for real needs a raw-JSON-text-aware entry point across the whole call chain (a real, scoped follow-up -- see
  // BUILD_QUEUE.md), not a quick patch to this function. This test PINS the current, disclosed behavior so a future change to it
  // is a deliberate decision, not an accidental regression.
  const rawText = readFileSync(new URL("./sample_proof.json", import.meta.url), "utf8")
    .replace(`"created_at":${SAMPLE.created_at}`, `"created_at":${SAMPLE.created_at}.0`);
  const parsed = JSON.parse(rawText);
  assert.equal(Number.isSafeInteger(parsed.created_at), true, "JS collapsed the .0 literal into a safe integer, as expected");
  assert.equal(verifyProofLocal(parsed).valid, true, "disclosed divergence: JS currently accepts this; Python correctly rejects it");
});

if (process.argv.includes("--live")) {
  await test("LIVE: preflight our own reference provider", async () => {
    const rep = await preflightVerify("https://api.babyblueviper.com");
    assert.equal(rep.ok, true);
    assert.ok(rep.trackRecord.entries > 0);
    console.log("    live:", rep.trustFlag, JSON.stringify(rep.trackRecord));
  });
}

console.log(`\n${passed} passed`);
