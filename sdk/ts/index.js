/**
 * invinoveritas-verify — verify-before-pay / demand-a-proof primitives for the
 * x402 + agent-to-agent ecosystem (TypeScript/JavaScript).
 *
 * Make peer verification a DEFAULT, not an opt-in. The way browsers made "Not Secure"
 * a warning until HTTPS was table-stakes, an agent about to pay or rely on another agent
 * should check whether that counterparty carries a *verifiable* track record — and refuse
 * to silently trust an unverifiable one.
 *
 *   preflightVerify(providerUrl)   — before paying an x402 provider, check it advertises a
 *       verifiable track record (reads the x402-signals `verification` block on
 *       /.well-known/x402, falling back to the X-Verification-Handshake header). Returns a
 *       report with a human-readable trust flag — the "Not Secure" warning for payments.
 *
 *   verifyAttachedProof(proof)     — when an agent attaches a signed verdict proof to its
 *       output, confirm it is authentically the named verifier's — WITHOUT trusting the
 *       presenter (free, no-auth schnorr check against the published key). This is the call
 *       that makes peer verification real and ungameable.
 *
 *   verifyProofLocal(proof)        — verify a proof OFFLINE, recomputing the NIP-01 event id and the
 *       BIP-340 schnorr signature against the published key on YOUR machine. No API call, no trust in
 *       us at all — the trustless path. (verifyAttachedProof is the convenient online equivalent.)
 *
 * Convention: x402-signals verification signal (github.com/sF1nX/x402-signals/issues/2).
 * Reference provider (block + header are live): https://api.babyblueviper.com
 * The online primitives (discover/preflight/verifyAttachedProof) use only global fetch (Node 18+,
 * browsers, workers). verifyProofLocal adds OFFLINE verification via @noble/curves (audited).
 */
import { schnorr } from "@noble/curves/secp256k1";
import { sha256 } from "@noble/hashes/sha256";

export const DEFAULT_VERIFIER = "https://api.babyblueviper.com";
const HANDSHAKE_HEADER = "x-verification-handshake";

// invinoveritas's published verifier key (x-only hex). Re-derive any time:
// GET https://api.babyblueviper.com/.well-known/agent-handshake → verifier_pubkey.
export const PUBLISHED_PUBKEY = "6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7";
const PROOF_KIND = 30078;
const SCHEMA_PREFIX = "invinoveritas.";

/** @param {string} value @returns {Record<string,string>} */
function parseHandshakeHeader(value) {
  /** @type {Record<string,string>} */
  const out = {};
  for (const part of (value || "").split(";")) {
    const p = part.trim();
    const i = p.indexOf("=");
    if (i > 0) out[p.slice(0, i).trim()] = p.slice(i + 1).trim();
  }
  return out;
}

async function _fetch(url, opts, timeout) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), (timeout || 10) * 1000);
  try {
    return await fetch(url, { ...(opts || {}), signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
}

/**
 * Return the provider's verification pointer, or null if it advertises none.
 * @param {string} providerUrl
 * @param {number} [timeout] seconds
 * @returns {Promise<Object|null>}
 */
export async function discoverVerification(providerUrl, timeout = 10) {
  const base = providerUrl.replace(/\/+$/, "");
  // 1) the structured x402-signals verification block
  try {
    const r = await _fetch(`${base}/.well-known/x402`, {}, timeout);
    if (r.ok) {
      const body = await r.json();
      const block = body && body.verification;
      if (block && typeof block === "object" && block.pubkey) return { ...block };
    }
  } catch (_) { /* fall through */ }
  // 2) the header beacon (present on every response of a conforming provider)
  try {
    const r = await _fetch(`${base}/`, {}, timeout);
    const hv = r.headers.get(HANDSHAKE_HEADER);
    if (hv) {
      const kv = parseHandshakeHeader(hv);
      if (kv.verify) {
        return {
          scheme: kv.scheme || "handshake.header",
          verify_endpoint: kv.verify,
          handshake: kv.handshake,
          track_record: kv.ledger,
          pubkey: kv.pubkey, // may be absent on the header form
        };
      }
    }
  } catch (_) { /* fall through */ }
  return null;
}

/**
 * @typedef {Object} VerificationReport
 * @property {string} providerUrl
 * @property {boolean} hasSignal
 * @property {string} trustFlag
 * @property {"pay"|"caution"|"review"} recommend
 * @property {string=} pubkey
 * @property {string=} verifyEndpoint
 * @property {string=} trackRecordUrl
 * @property {Object} trackRecord
 * @property {string} detail
 * @property {boolean} ok
 */

/**
 * Check whether an x402 provider carries a verifiable track record BEFORE you pay it.
 * @param {string} providerUrl
 * @param {{require?: boolean, timeout?: number}} [opts]
 * @returns {Promise<VerificationReport>}
 */
export async function preflightVerify(providerUrl, opts = {}) {
  const { require: req = false, timeout = 10 } = opts;
  const block = await discoverVerification(providerUrl, timeout);
  if (!block) {
    if (req) throw new Error(`preflightVerify: ${providerUrl} has no verifiable track record`);
    return {
      providerUrl, hasSignal: false, trustFlag: "⚠ no verifiable track record",
      recommend: "caution", trackRecord: {}, ok: false,
      detail: "Provider advertises no x402-signals verification block or handshake header. " +
              "You would be trusting it on assertion alone.",
    };
  }
  let summary = {};
  if (block.track_record) {
    try {
      const r = await _fetch(block.track_record, {}, timeout);
      if (r.ok) {
        const d = await r.json();
        const tr = (d && d.track_record) || {};
        summary = {
          entries: d.count ?? d.ledger_entries,
          wins: tr.wins, losses: tr.losses,
          winRatePct: tr.win_rate_pct, settled: tr.live_trades_closed,
        };
      }
    } catch (_) { /* best-effort */ }
  }
  const showsLosses = Number.isInteger(summary.losses) && summary.losses > 0;
  const recommend = showsLosses ? "pay" : "review";
  const trustFlag = showsLosses
    ? "✓ verifiable track record"
    : "✓ verification signal (verify the record yourself)";
  return {
    providerUrl, hasSignal: true, trustFlag, recommend,
    pubkey: block.pubkey, verifyEndpoint: block.verify_endpoint,
    trackRecordUrl: block.track_record, trackRecord: summary,
    ok: recommend !== "caution",
    detail: "Recompute it yourself: " + (block.recompute ||
      "verify each entry's signature against pubkey; outcomes settle where the issuer can't edit them."),
  };
}

/**
 * Confirm a signed verdict proof an agent attached to its output is authentic — WITHOUT
 * trusting the presenter. Free, no-auth schnorr check against the verifier's published key.
 * @param {Object} proof signed event {id,pubkey,created_at,kind,tags,content,sig}
 * @param {{verifyEndpoint?: string, expectedPubkey?: string, timeout?: number}} [opts]
 * @returns {Promise<Object>} result; `valid` is the authenticity boolean
 */
export async function verifyAttachedProof(proof, opts = {}) {
  const { verifyEndpoint, expectedPubkey, timeout = 10 } = opts;
  const endpoint = verifyEndpoint || `${DEFAULT_VERIFIER}/verify-proof`;
  let result;
  try {
    const r = await _fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event: proof }),
    }, timeout);
    result = await r.json();
  } catch (e) {
    result = { valid: false, error: String((e && e.message) || e) };
  }
  if (expectedPubkey && result && result.valid) {
    const signer = (proof && proof.pubkey) || result.pubkey;
    if (signer !== expectedPubkey) {
      return { valid: false, error: "signature valid but signer != expectedPubkey", signer, expected: expectedPubkey };
    }
  }
  return result;
}

function _toHex(bytes) {
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Recompute the canonical NIP-01 event id from a signed event's fields.
 * @param {Object} ev @returns {string} hex id
 */
export function nostrEventId(ev) {
  const serial = JSON.stringify([
    0, String(ev.pubkey).toLowerCase(), Number(ev.created_at), Number(ev.kind),
    ev.tags || [], String(ev.content),
  ]);
  return _toHex(sha256(new TextEncoder().encode(serial)));
}

/**
 * Verify an invinoveritas proof OFFLINE — recompute the event id, BIP-340 schnorr-check it against the
 * published key, confirm authorship + proof shape — entirely on your machine, with no API call and no
 * trust in us. Never throws; returns { valid, checks, ... }. Verdicts are byte-identical to the online
 * /verify-proof endpoint; this is the same check without the round trip.
 * @param {Object} proof signed event {id,pubkey,created_at,kind,tags,content,sig}
 * @param {{expectedPubkey?: string}} [opts]
 * @returns {{valid: boolean, checks: Object, issued_by_invinoveritas: boolean, published_pubkey: string}}
 */
export function verifyProofLocal(proof, opts = {}) {
  const pin = (opts.expectedPubkey || PUBLISHED_PUBKEY || "").trim().toLowerCase();
  const checks = {
    id_integrity: false, signature_valid: false,
    issued_by_invinoveritas: false, is_proof_event: false,
  };
  const out = {
    valid: false, checks, published_pubkey: PUBLISHED_PUBKEY, issued_by_invinoveritas: false,
    how_to_verify: "Recompute id = sha256(JSON [0,pubkey,created_at,kind,tags,content]); schnorr-verify " +
      "sig over it vs pubkey; confirm pubkey == published_pubkey. NIP-01.",
  };
  if (!proof || typeof proof !== "object") { out.error = "proof must be an object"; return out; }
  const content = proof.content ?? "";
  const tags = proof.tags ?? [];
  if (typeof content !== "string" || content.length > 65536) { out.error = "content too large/not a string"; return out; }
  if (!Array.isArray(tags) || tags.length > 256 || JSON.stringify(tags).length > 65536) { out.error = "tags too large"; return out; }
  for (const k of ["id", "pubkey", "created_at", "kind", "content", "sig"]) {
    if (proof[k] === undefined || proof[k] === null || proof[k] === "") { out.error = "missing required fields"; return out; }
  }
  try {
    checks.id_integrity = nostrEventId(proof).toLowerCase() === String(proof.id).toLowerCase();
    try {
      checks.signature_valid = schnorr.verify(String(proof.sig), String(proof.id), String(proof.pubkey));
    } catch (_) { checks.signature_valid = false; }
    checks.issued_by_invinoveritas = !!pin && String(proof.pubkey).trim().toLowerCase() === pin;
    let schema = "";
    try { schema = (JSON.parse(String(proof.content)).schema) || ""; } catch (_) { schema = ""; }
    checks.is_proof_event = Number(proof.kind) === PROOF_KIND
      && typeof schema === "string" && schema.startsWith(SCHEMA_PREFIX);
  } catch (e) {
    out.error = `malformed event: ${e}`;
    return out;
  }
  out.issued_by_invinoveritas = checks.issued_by_invinoveritas;
  out.valid = Object.values(checks).every(Boolean);
  if (checks.signature_valid && checks.issued_by_invinoveritas && !checks.is_proof_event) {
    out.error = "authentically signed by invinoveritas, but NOT a verdict/action proof (wrong kind/schema).";
  }
  try { out.proof_payload = JSON.parse(proof.content); } catch (_) { out.proof_payload = null; }
  return out;
}

export default {
  DEFAULT_VERIFIER, PUBLISHED_PUBKEY,
  discoverVerification, preflightVerify, verifyAttachedProof, verifyProofLocal, nostrEventId,
};
