#!/usr/bin/env node
/**
 * Live Primus zkTLS attestation of one off-chain HTTPS response.
 *
 * Reads PRIMUS_APP_ID / PRIMUS_APP_SECRET from ../../.env (never prints the secret).
 * Source: Coinbase public BTC-USD spot — a fact a trading /review might cite.
 * This is a standalone demo of the mechanism, not WYRIWE spec text.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { PrimusCoreTLS } = require("@primuslabs/zktls-core-sdk");

const HERE = __dirname;
const ENV_PATH = path.resolve(HERE, "../../.env");
const OUT_DIR = path.join(HERE, "outputs");

// Independent public spot. GET, no auth. Shape is NOT the SDK's OKX instruments example.
const SOURCE = {
  name: "coinbase_btc_usd_spot",
  request: {
    url: "https://api.coinbase.com/v2/prices/BTC-USD/spot",
    method: "GET",
    header: { Accept: "application/json" },
    body: "",
  },
  responseResolves: [
    { keyName: "amount", parsePath: "$.data.amount" },
    { keyName: "base", parsePath: "$.data.base" },
    { keyName: "currency", parsePath: "$.data.currency" },
  ],
  justification:
    "A trading /review on this platform often cites a last price as a stated fact. " +
    "Coinbase's public spot is an independent HTTPS source (not Hyperliquid, not Binance — " +
    "Binance is geo-blocked from this box). Authenticating THAT response is the Step-3 gap: " +
    "prove the cited print came from api.coinbase.com, then let /review judge the reasoning.",
};

function loadDotenv(filePath) {
  const env = {};
  if (!fs.existsSync(filePath)) {
    throw new Error(`missing ${filePath}`);
  }
  for (const raw of fs.readFileSync(filePath, "utf8").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const i = line.indexOf("=");
    const k = line.slice(0, i).trim();
    let v = line.slice(i + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    env[k] = v;
  }
  return env;
}

function isSecretKey(name) {
  // Exact field names that are the app secret or raw private-key material.
  // Do NOT match "signatures", "recipient", "attestorAddr" — those are public.
  const n = String(name).replace(/-/g, "_").toLowerCase();
  return (
    n === "appsecret" ||
    n === "app_secret" ||
    n === "primus_app_secret" ||
    n === "privatekey" ||
    n === "private_key"
  );
}

function redactSecrets(obj, appSecret) {
  // Redact only the literal appSecret (and fields named as such). Never
  // blanket-regex 0x hex — attestation signatures / recipient / attestor
  // addresses are the public, independently-checkable part of the proof.
  if (obj === null || obj === undefined) return obj;
  if (typeof obj === "string") {
    if (!appSecret) return obj;
    let s = obj;
    if (appSecret && s.includes(appSecret)) {
      s = s.split(appSecret).join("[redacted]");
    }
    const body = appSecret.toLowerCase().startsWith("0x") ? appSecret.slice(2) : appSecret;
    if (body && body.length >= 16 && s.includes(body)) {
      s = s.split(body).join("[redacted]");
    }
    return s;
  }
  if (Array.isArray(obj)) return obj.map((v) => redactSecrets(v, appSecret));
  if (typeof obj === "object") {
    const out = {};
    for (const [k, v] of Object.entries(obj)) {
      out[k] = isSecretKey(k) ? "[redacted]" : redactSecrets(v, appSecret);
    }
    return out;
  }
  return obj;
}

async function main() {
  const env = loadDotenv(ENV_PATH);
  const appId = (env.PRIMUS_APP_ID || process.env.PRIMUS_APP_ID || "").trim();
  const appSecret = (env.PRIMUS_APP_SECRET || process.env.PRIMUS_APP_SECRET || "").trim();
  if (!appId || !appSecret) {
    console.error("PRIMUS_APP_ID / PRIMUS_APP_SECRET missing from ../../.env");
    process.exit(2);
  }
  // Do not print appSecret. Confirm presence only.
  console.error(`primus appId present=${appId.length > 0} secret_present=${appSecret.length > 0} secret_len=${appSecret.length}`);

  fs.mkdirSync(OUT_DIR, { recursive: true });
  fs.writeFileSync(
    path.join(OUT_DIR, "source.json"),
    JSON.stringify({ source: SOURCE }, null, 2) + "\n"
  );

  const zkTLS = new PrimusCoreTLS();
  let initResult;
  try {
    initResult = await zkTLS.init(appId, appSecret);
  } catch (err) {
    console.error("init() failed:", err && err.message ? err.message : err);
    process.exit(1);
  }
  console.error("initResult=", typeof initResult === "string" ? initResult : JSON.stringify(initResult));

  const generateRequest = zkTLS.generateRequestParams(
    SOURCE.request,
    SOURCE.responseResolves
  );
  generateRequest.setAttMode({ algorithmType: "proxytls" });
  generateRequest.setAdditionParams(
    JSON.stringify({
      demo: "wyriwe-step3-zktls-demo",
      source: SOURCE.name,
      note: "standalone mechanism demo; not WYRIWE spec text",
    })
  );

  let signedRequestStr;
  try {
    signedRequestStr = await zkTLS.sign(generateRequest.toJsonString());
  } catch (err) {
    const payload = {
      ok: false,
      stage: "sign",
      error: {
        name: err && err.name,
        message: err && err.message,
        code: err && err.code,
      },
      diagnosis:
        "PRIMUS_APP_SECRET is loaded from ../../.env (not printed). " +
        "zktls-core-sdk sign() constructs ethers.Wallet(appSecret). " +
        "A first Primus dashboard project once handed out 0x+63 hex (odd-length); " +
        "that was a one-off, diagnosed by probe_secret_as_is.js. This catch is " +
        "generic — do not assume the current secret is the odd-length one.",
    };
    fs.writeFileSync(
      path.join(OUT_DIR, "attestation_error.json"),
      JSON.stringify(redactSecrets(payload, appSecret), null, 2) + "\n"
    );
    console.error("sign() failed:", redactSecrets(payload.error.message, appSecret));
    console.error(payload.diagnosis);
    console.error("wrote outputs/attestation_error.json (no secret)");
    await zkTLS.close().catch(() => {});
    process.exit(1);
  }

  let attestation;
  try {
    attestation = await zkTLS.startAttestation(signedRequestStr, { timeout: 180000 });
  } catch (err) {
    const payload = {
      ok: false,
      stage: "startAttestation",
      error: {
        name: err && err.name,
        message: err && err.message,
        code: err && err.code,
        stack: err && err.stack ? String(err.stack).split("\n").slice(0, 12) : null,
      },
    };
    fs.writeFileSync(
      path.join(OUT_DIR, "attestation_error.json"),
      JSON.stringify(redactSecrets(payload, appSecret), null, 2) + "\n"
    );
    console.error("startAttestation() failed:", payload.error.message || payload.error);
    console.error("wrote outputs/attestation_error.json (no secret)");
    await zkTLS.close().catch(() => {});
    process.exit(1);
  }

  let verifyResult;
  try {
    verifyResult = zkTLS.verifyAttestation(attestation);
  } catch (err) {
    console.error("verifyAttestation() threw:", err && err.message ? err.message : err);
    verifyResult = { threw: true, message: err && err.message };
  }

  const out = {
    ok: verifyResult === true,
    source: SOURCE,
    initResult,
    attestation: redactSecrets(attestation, appSecret),
    verifyResult,
    captured_at: new Date().toISOString(),
  };
  fs.writeFileSync(path.join(OUT_DIR, "attestation.json"), JSON.stringify(out, null, 2) + "\n");
  console.error("verifyResult=", verifyResult);
  console.error("wrote outputs/attestation.json");
  // Safe summary only — attestation.data is the revealed payload, not a secret.
  if (attestation && attestation.data) {
    console.error("attestation.data=", attestation.data);
  }
  await zkTLS.close().catch(() => {});
  process.exit(verifyResult === true ? 0 : 1);
}

main().catch((err) => {
  console.error("fatal:", err && err.message ? err.message : err);
  process.exit(1);
});
