# invinoveritas verdict gate for L402

**ES:** L402 resuelve si un agente *puede* pagar (tiene billetera, presupuesto y una factura). No resuelve si *debería*:
el endpoint correcto, el precio correcto, el momento correcto. Este ejemplo pone un veredicto firmado e independiente
entre el `402` y el pago, ligado a los bytes exactos de la intención de pago, y deja un recibo que une veredicto,
`payment_hash` y preimagen, verificable por cualquiera sin conexión.

**EN:** L402 answers whether an agent *can* pay (it has a wallet, a budget and an invoice). It doesn't answer whether it
*should*: right endpoint, right price, right moment. This example puts an independent, signed verdict between the `402`
and the payment, bound to the exact payment intent, and leaves a receipt binding verdict, `payment_hash` and preimage
that anyone can recompute offline.

Python 3.9+, **standard library only** (BOLT11 decoding, secp256k1 key recovery, BIP-340 and JCS are all in the package).

## Flow

1. The agent requests an L402-protected URL and gets `402` with `WWW-Authenticate: L402 macaroon="…", invoice="lnbc…"`
   (also accepts `token="…"` and the legacy `LSAT` prefix, and mirrors the server's prefix the way
   [lnget](https://github.com/lightninglabs/lnget) does).
2. **Free local checks, before anything is reviewed or paid:** the BOLT11 signature verifies and the payee key is
   recovered from it; the invoice has an amount, is on the expected network, is unexpired and under `max_cost_sat`; the
   credential commits to the same `payment_hash` (Aperture macaroon identifier, or a `payment_hash` caveat) and is
   scoped to the host being called.
3. **Verdict:** `POST /review` (`sign: true`) with the exact intent as `action_binding.args`: method, URL, the full
   invoice, amount, payee pubkey, `payment_hash`, creation and expiry, a hash of the credential, the agent's stated
   purpose, and the `proceed_on` and max-age rules. The proof is checked **offline**: BIP-340 signature, pinned issuer
   key, NIP-01 id, `decision_ref` recompute, `sha256(JCS(args))`, tool hash.
4. **Pay** only if the verdict is in `proceed_on`, younger than `max_verdict_age_s` (default 120 s), and the invoice
   is still unexpired. The wallet is pluggable.
5. **After paying:** `sha256(preimage) == payment_hash` is checked *before* the credential is presented, then a receipt
   is written. `python3 -m l402_verdict_gate.verify receipt.json` re-checks everything offline.

Fail modes: `fail_mode="closed"` (the default) blocks when the reviewer is unreachable, and `"open"` pays and flags
`fail_open`. A proof that fails verification always blocks.

## Integration

```python
from l402_verdict_gate import VerdictGate, LndRestWallet, l402_request

gate = VerdictGate(api_key=os.environ["INVINOVERITAS_KEY"],   # free: POST https://api.babyblueviper.com/register
                   review_above_sat=5_000,                     # review only payments that matter
                   max_cost_sat=50_000, accountable_party="ops@yourco")
wallet = LndRestWallet("https://127.0.0.1:8080", "pay-only.macaroon", "tls.cert")
status, headers, body, receipt = l402_request(
    "https://api.example.com/v1/report", gate, wallet,
    purpose="monthly churn report the user asked for; budget 50k sats")
json.dump(receipt, open("receipt.json", "w"))                 # verdict + payment_hash + preimage
```

`PaymentBlocked` means nothing was paid (`e.decision.reason` says why). `PreimageMismatch` means the wallet returned a
preimage that does not open the invoice, so the credential is never sent.

## Wallets

`Wallet` is one method: `pay_invoice(bolt11, max_fee_sat, timeout_s) -> PaymentResult(preimage, amount_msat, fee_msat)`.

- `MockWallet`: used by the tests. It moves no money.
- `LndRestWallet`: LND REST `POST /v1/channels/transactions`. Use a pay-only macaroon
  (`lncli bakemacaroon offchain:read offchain:write`), not `admin.macaroon`. The tests don't exercise it.
- **Wavelength** (Lightning Labs' embedded self-custodial wallet): its send path is already two-phase. `PrepareSend`
  previews the payment, or `dry_run` over MCP, and the real send needs explicit consent (`yes: true`). The verdict fits
  between those two steps: preview, then gate, then confirm. A `pay_invoice` that calls `wavecli send`, or the
  `WalletService.Send` RPC, is the whole adapter.
- **Core Lightning, NWC, LNbits:** any call that pays a BOLT11 and returns the preimage works.

With **lnget**, the gate has to run inside its challenge handler, before `PayInvoice`. Each `402` from Aperture carries
a fresh invoice, so checking one challenge and then letting `lnget` request again would pay an invoice the verdict
never saw. A pre-pay hook in `lnget`'s `l402.Handler` is the natural place for it.

## CAN pay vs SHOULD pay

| | L402 / your wallet | this gate |
|---|---|---|
| Is the invoice real and unexpired, and is the amount under my cap? | yes (`lnget --max-cost`) | rechecked locally, for free |
| Is this the endpoint, price and moment my task needs? | no | signed verdict over the exact intent |
| Can someone else check later what was approved and paid? | the preimage proves payment | receipt: verdict + `payment_hash` + preimage, checkable offline |

## Cost and latency

A review costs about $1 (1,000 sats on a Bearer key) and takes about 20 to 60 s. The recorded one took 17 s. That
doesn't make sense for a 10-sat call. Set `review_above_sat`, or gate only new endpoints, price changes and
budget-sized purchases. Calls below the threshold are paid without a review, and their receipts say `governed: false`.

## What a valid receipt does and doesn't show

It shows that invinoveritas's published key signed a verdict over this exact intent, that the verdict allowed paying,
that the invoice decodes to the bound fields with a valid payee signature, and that the preimage opens it, so it was
paid. It does **not** show that the payment happened after the verdict: `paid_at` is reported by the payer, because
the payer can't choose a Lightning `payment_hash` and there is no public settlement log. It also doesn't show that the
reviewer had full context, or that the verdict was right.

**Decision-receipt slots were evaluated and left out.** A [decision receipt](../decision-receipt/SPEC.md) with a
decider-scoped slot keyed to `payment_hash` would make a second, conflicting signed decision by the same agent key for
the same invoice publicly visible. That needs a second review bound to the `decision_receipt` tool, though (about
$1 more per payment, plus 100 sats). It also covers the agent re-deciding, not "ask twice and keep the approve", and an
invoice can be paid only once anyway. It's worth adding where one agent key pays many invoices for a principal that
audits it.

## Tests

```sh
python3 -m unittest discover -s tests -v   # 27 tests, no network
python3 demo.py                            # offline walkthrough of the recorded verdict + a full mock loop
```

Fixtures: the [BOLT #11](https://github.com/lightning/bolts/blob/master/11-payment-encoding.md) spec vectors; two
real `402` challenges from `lightningfaucet.com` (never paid); a real signed `approve_with_concerns` verdict over the
quote challenge (`tests/fixtures/l402_quote_verdict.json`, recorded with `record_fixture.py`); and a real signed `reject`
reused from [`qbtlabs-x402-verdict-gate`](../qbtlabs-x402-verdict-gate). The recorded verdict raised two concerns. One
was that the credential's scope wasn't checked, so that check is now a free local check. The other was that freshness
must be enforced at dispatch, which the gate already does. Full-loop tests use a synthetic invoice and a test issuer
key, because only a real payment reveals a real preimage.

References: [L402 protocol](https://github.com/lightninglabs/L402) ·
[Aperture](https://github.com/lightninglabs/aperture) · [lnget](https://github.com/lightninglabs/lnget) ·
[Wavelength](https://wavelength.lightning.engineering/).
