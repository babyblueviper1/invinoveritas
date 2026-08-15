# WYRIWE Step 3 — zkTLS input-source authentication (standalone demo)

**This is not WYRIWE spec text.** WYRIWE is co-authored. This folder is a
mechanism demo: one real off-chain HTTPS response, one real Primus zkTLS
SDK, one `inputHash`, one live `/review` that *names* that hash. It does
not propose fields, steps, or conformance language for the ERC.

## Two primitives, not one

| Leg | Question | Who |
|---|---|---|
| zkTLS (Primus) | Did this HTTPS response actually come from the claimed host? | `@primuslabs/zktls-core-sdk` |
| `/review` | Given that authenticated fact, is the *reasoning* over it reasonable? | invinoveritas |

A forged Coinbase print can still produce a "valid" `/review` verdict if
the reasoning follows the forged numbers. Step 3 of WYRIWE already
*commits* what the model received. This demo is the missing
*authentication* of the off-chain source, composed in front of `/review`
as `inputHash=sha256(canonical attested payload)`.

They stack. They are not the same claim. zkTLS does not judge the trade.
`/review` does not prove the HTTPS source.

## Why Coinbase BTC-USD spot

The cited fact is `GET https://api.coinbase.com/v2/prices/BTC-USD/spot`
→ `{data: {amount, base, currency}}`.

- A trading `/review` on this platform often treats a last price as a
  stated fact. Authenticating *that* GET is the gap.
- Independent public venue (not our Hyperliquid execution feed).
- Simple GET, no API key.
- **Not** the SDK's stock OKX `instType` example. `responseResolves` are
  `$.data.amount` / `$.data.base` / `$.data.currency`.
- Binance's public ticker is geo-blocked from this box (`Service
  unavailable from a restricted location`). Coinbase and Hyperliquid both
  answered from here; Coinbase is the GET.

## What's real vs demo-scope

| Real | Not this folder |
|---|---|
| `npm install @primuslabs/zktls-core-sdk@0.3.7` (not vendored) | Formal WYRIWE spec language |
| `init(appId, appSecret)` against the live native addon | A standing pre-step before every `/review` |
| Credentials from `../../.env` (`PRIMUS_APP_ID` / `PRIMUS_APP_SECRET`) — secret never printed | Production subprocess wiring from FastAPI |
| `generateRequestParams` + `sign` + `startAttestation` + `verifyAttestation` | Mapping every off-chain source we might cite |
| `bind_to_verdict.py` live `/review` + `/verify-proof` **once an attestation exists** | Claiming the ERC-8281 observation-commitment leg is also implemented here |

Honest remaining gap: even when attestation succeeds, this is **one**
source, run by hand. Production would be a Node subprocess the Python
pipeline shells out to *before* every `/review` that cites an off-chain
fact. That wire-up is not built.

## Reproduce

From this directory, Node ≥18, repo `.env` populated:

```bash
npm install
node verify_input_source.js          # writes outputs/attestation.json
# then, only if verifyResult === true:
../../venv/bin/python bind_to_verdict.py
```

`bind_to_verdict.py` POSTs `http://127.0.0.1:8000/review` (`sign=true`,
`seed=true`, `artifact_type=analysis`) with `inputHash` in the artifact
and context, then POSTs `/verify-proof` with no auth. Auth is
`HL_REVIEW_BEARER` then `OPERATOR_FULL_API_KEY` on 402 — same fallback
as the Article 12 demo.

## What actually happened on this box (2026-08-15, live)

Re-ran end-to-end against the live SDK after the working Primus project's
credentials were written to `.env` (`PRIMUS_APP_ID` / `PRIMUS_APP_SECRET`).
Secret length at load: `secret_len=66` (`0x` + 64 hex). Secret not printed,
not padded.

A first success wrote `attestation.json` with `signatures` / `recipient` /
`attestorAddr` replaced by `"0x[redacted]"` because `redactSecrets()`
blanket-regexed every `0x` hex string. Those fields are the **public**
part of the zkTLS proof (same category as our `/review` event.sig, which
was never redacted). The regex is gone. Redaction is now exact key name
(`appSecret` / `APP_SECRET` / `PRIMUS_APP_SECRET` / `privateKey`) plus
the literal `appSecret` value if it ever appears in an error string.
The attestation object is written untouched.

This folder's saved run is the **post-fix** live attestation (a new
Coinbase print — the previous persist cannot be un-redacted).

1. `node verify_input_source.js` — native addon loaded (`Use Native Mode`,
   algorithm 1.4.33). `init()` `retcode=0`. **`sign()` succeeded.
   `startAttestation()` succeeded. `verifyAttestation()` returned `true`.**
2. Revealed Coinbase payload (live print, not mocked):
   `{"amount":"62916.215","base":"BTC","currency":"USD"}`.
   Request URL in the attestation is
   `GET https://api.coinbase.com/v2/prices/BTC-USD/spot`.
   Public proof fields in `outputs/attestation.json` are the real values
   Primus returned — not placeholders:
   - `recipient` = `0x0000000000000000000000000000000000000000`
     (zero address, as issued; this is not a redaction)
   - `attestors[0].attestorAddr` = `0xdb736b13e2f522dbe18b2015d0291e4b193d8ef6`
   - `signatures[0]` = `0x274b5e9a…553d1c` (132-char hex, 65-byte eth sig)
   `attestation_timestamp=1786797420230`. App secret is not in the file.
3. `canonicalize.py` inputHash over that persisted attested payload
   (sorted keys, compact separators, no floats), including the real
   recipient:
   `sha256:06fbeb9630a84d7f465b49a852af87bf1b470f85c69961081c87e68bd617fe44`
   (`outputs/input_hash.txt`).
4. `bind_to_verdict.py` live `POST http://127.0.0.1:8000/review`
   (`sign=true`, `seed=true`, `artifact_type=analysis`). Not mocked.
   Re-bound so this folder is one coherent run (new attestation ⇒ new
   `inputHash`). The earlier `/review` proof
   (`decision_ref=sha256:b0ead23b…8763d`, independently
   `/verify-proof` valid) is still a valid event; it is just not the file
   in this directory anymore.

| | |
|---|---|
| `inputHash` | `sha256:06fbeb9630a84d7f465b49a852af87bf1b470f85c69961081c87e68bd617fe44` |
| `/review` verdict | **approve_with_concerns** (confidence 0.94) |
| `decision_ref` | `sha256:de01a8b64204a3687821d73380eea45421a250f872a280ee16c7d7ad0c35f452` |
| proof event id | `cfdeb79d154b3fcbd3b4f6631dbaff7319117dcca5a6424404171dcb50356bb1` |
| signer | published key `6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7` |
| `/verify-proof` | `valid: true` (id_integrity, signature_valid, issued_by_invinoveritas, decision_ref_recomputes) |

Summary from `/review`: reasonable to cite as independently
source-authenticated evidence that Coinbase returned BTC-USD spot
`amount='62916.215'` at the attested timestamp; not sufficient by itself
to price, size, or validate execution risk on Hyperliquid.

Auth note: `HL_REVIEW_BEARER` returned **402** (same as the Article 12
demo). Retried once with `OPERATOR_FULL_API_KEY`. Recorded as `auth_used`
in `outputs/review_response.json`. `seed=true` on localhost still counts
this as `proofs_seeded`.

This is still **one** source, run by hand. Production subprocess wiring
from FastAPI is not built.

## Known issue, worked around (do not pad)

The first Primus throwaway project this folder used handed out a
dashboard secret of `0x` + **63** hex digits. `init()` accepted it
(`retcode=0`); `sign()` threw `INVALID_ARGUMENT: hex data is odd-length`
because `ethers.Wallet(appSecret)` needs a 32-byte key (`0x` + 64).
That was a **one-off dashboard glitch**, not systemic — a second project
produced a proper 64-hex secret (this run). The broken pair is still in
`.env` as commented `PRIMUS_APP_ID_BROKEN_ODD_LENGTH` /
`PRIMUS_APP_SECRET_BROKEN_ODD_LENGTH`. Do not use those. Do not invent a
64th nibble.

`probe_secret_as_is.js` is the diagnostic that split `init` vs `sign` vs
`ethers.Wallet` on the unmodified secret. It is not part of the
reproduce path. The redacted first failure is kept as
`outputs/attestation_error.json`.

## Files

| file | role |
|---|---|
| `verify_input_source.js` | live zkTLS: init → generateRequestParams → sign → startAttestation → verifyAttestation |
| `canonicalize.py` | sorted-key sha256 of the attested payload → `inputHash` |
| `bind_to_verdict.py` | `inputHash` into live `/review` + `/verify-proof` |
| `outputs/source.json` | the Coinbase request/responseResolves we sent |
| `outputs/attestation.json` | this run's live attestation (`verifyResult=true`; public sig/recipient/attestor intact; app secret never written) |
| `outputs/input_hash.txt` | `sha256:…` of the canonical attested payload |
| `outputs/review_response.json` | live `/review` request + body |
| `outputs/verify_proof_response.json` | independent `/verify-proof` result |
| `outputs/attestation_error.json` | historical: first project's odd-length `sign()` failure (secret redacted) |
| `probe_secret_as_is.js` | diagnostic record of that first-project bug; not in the live flow |
