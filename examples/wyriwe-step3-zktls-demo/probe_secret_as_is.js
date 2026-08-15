#!/usr/bin/env node
/**
 * Diagnostic record — not part of the live reproduce path.
 * Isolated the first Primus project's odd-length (0x+63) dashboard secret:
 * init() accepted it; sign() / ethers.Wallet rejected it. Worked around by
 * using a second project's proper 0x+64 secret. Never prints the secret.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { ethers } = require("ethers");
const { PrimusCoreTLS } = require("@primuslabs/zktls-core-sdk");

function loadDotenv(filePath) {
  const env = {};
  for (const raw of fs.readFileSync(filePath, "utf8").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const i = line.indexOf("=");
    let v = line.slice(i + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
    env[line.slice(0, i).trim()] = v;
  }
  return env;
}
function redact(msg) {
  return String(msg)
    .replace(/0x[0-9a-fA-F]{16,}/g, "0x[redacted]")
    .replace(/value="[0-9a-fA-F]{16,}"/g, 'value="[redacted]"');
}

(async () => {
  const env = loadDotenv(path.resolve(__dirname, "../../.env"));
  const appId = (env.PRIMUS_APP_ID || "").trim();
  const appSecret = (env.PRIMUS_APP_SECRET || "").trim();
  const body = appSecret.toLowerCase().startsWith("0x") ? appSecret.slice(2) : appSecret;
  const report = {
    secret_meta: {
      total_len: appSecret.length,
      has_0x_prefix: appSecret.slice(0, 2).toLowerCase() === "0x",
      body_len: body.length,
      body_even: body.length % 2 === 0,
      body_is_hex: /^[0-9a-fA-F]+$/.test(body),
    },
    init: {},
    sign: {},
    ethers_wallet_as_is: {},
    ethers_wallet_stripped_prefix: {},
  };

  const zk = new PrimusCoreTLS();
  try {
    const ir = await zk.init(appId, appSecret);
    report.init = { threw: false, retcode: ir && ir.retcode, retdesc: ir && ir.retdesc };
  } catch (e) {
    report.init = { threw: true, message: redact(e.message), name: e.name };
  }

  if (!report.init.threw) {
    try {
      const req = zk.generateRequestParams(
        { url: "https://api.coinbase.com/v2/prices/BTC-USD/spot", method: "GET", header: {}, body: "" },
        [{ keyName: "amount", parsePath: "$.data.amount" }]
      );
      await zk.sign(req.toJsonString());
      report.sign = { threw: false };
    } catch (e) {
      report.sign = {
        threw: true,
        name: e.name,
        code: e.code,
        message_redacted: redact(e.message),
      };
    }
  }

  function tryWallet(val) {
    try {
      new ethers.Wallet(val);
      return { ok: true };
    } catch (e) {
      return { ok: false, code: e.code, message_redacted: redact(e.message) };
    }
  }
  report.ethers_wallet_as_is = tryWallet(appSecret);
  report.ethers_wallet_stripped_prefix = tryWallet(body);

  await zk.close().catch(() => {});
  console.log(JSON.stringify(report, null, 2));
})().catch((e) => {
  console.error(redact(e.message || e));
  process.exit(1);
});
