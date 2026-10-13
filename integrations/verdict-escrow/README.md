# VerdictGatedEscrow: a payment that moves only on an independent approval

An agent pays into a contract. The contract releases the funds to the payee **only** when it is shown an approving
verdict, signed by an independent reviewer, for that exact payment request under that exact written policy. It checks
the signature itself, on-chain. A rejection is signed too, and the contract refuses it. With no approval, the payer takes
the funds back after a deadline.

This turns a verdict from a record that came first into a precondition the payment cannot skip.

**Deployed on Base:** [`0xfC4Da1b7C56D46AB23c750c0890025F6335bCA3F`](https://basescan.org/address/0xfC4Da1b7C56D46AB23c750c0890025F6335bCA3F)
(token: USDC on Base; verifier: the published invinoveritas key `6786e18a…22fbb7`,
[verifier-keys.json](https://api.babyblueviper.com/.well-known/verifier-keys.json)). Anyone can use it; the payee, amount
and terms are set by whoever funds an escrow.

## How it works

```
payer ──fund(payee, amount, H(request), H(policy), deadline)──▶ VerdictGatedEscrow (holds the funds)
  │                                                                     ▲
  └─ request + policy ─▶ POST /review (sign=true, verdict_relay) ─▶ signed verdict ──release()─┘  (anyone may submit)
```

1. **`fund()`** fixes the payee, the amount, the SHA-256 of the exact payment request text and the SHA-256 of the policy.
   None of these can change afterwards. Escrow ids are derived from the payer, so nobody can take another payer's id.
2. **`POST /review`** with a `verdict_relay` block reviews the request against the policy and returns a BIP-340 signature
   over the verdict-relay v2 digest: chain, contract, escrow id, request hash, policy hash, `approved`, and the verdict's
   `decision_ref`. It signs only if the request hash equals the hash of the exact text it reviewed, and only for a clean
   `approve` (approved = 1) or `reject` (approved = 0); `approve_with_concerns` gets no signature.
3. **`release()`** recomputes that digest with `approved = 1` and checks the signature against the verifier key. Anything
   else reverts with `BadVerdict`. Funds can only go to the stored payee, once.
4. **`refund()`**: with no approval, the payer reclaims the funds after `refundAfter`.

### Policy-governed review (optional; rolling out 2026-10-13)

`/review` also accepts a `policy` block with structured `facts` and `evidence`. Deterministic rules (recipient
allow-list, amount cap, network, token) are checked in code first, and any failure rejects with no model call. Only the
substantive conditions go to the model, which returns `VERIFIED`, `DECLARED_ONLY`, `CONTRADICTED` or `INSUFFICIENT` per
condition. A fixed rule, set in the policy rather than by the model, decides, and the approval says whether it is a
*factual* claim (every condition verified by evidence) or only a *declarative* one (the request's statement is consistent
with the policy). Pass it with `escrow_client.py review --policy-json`.

## Use it

```sh
pip install web3 eth-account
export PAYER_KEY=0x...      # USDC + a little ETH on Base
export IVV_API_KEY=...      # POST https://api.babyblueviper.com/register

python3 escrow_client.py fund    --payee 0x... --amount 1.00 --request request.txt --policy policy.txt --refund-after 3600
python3 escrow_client.py review  --id <escrow id> --request request.txt --policy policy.txt
python3 escrow_client.py release --id <escrow id> --verdict verdict_<id>.json
python3 escrow_client.py status  --id <escrow id>
```

`request.txt` is the payment request exactly as the reviewer should see it; `policy.txt` is the rule set it is judged
against. Write the policy so a compliant request can be approved without judgment calls; a vague policy gets a qualified
answer, and qualified answers do not release funds.

## Tests

```sh
forge install foundry-rs/forge-std   # once
forge test                           # 7 tests; ffi calls test/sign.py (stdlib + ../../examples/decision-receipt/bip340.py)
```

The tests use a throwaway key, never the production one. They cover: the contract's digest equals the signer's byte for
byte; an approval releases once; no verdict, a reject, or an approval for another request, escrow, submission or decision
cannot release; refund timing; id squatting.

## What a release establishes, and what it does not

- **Establishes:** the configured verifier key approved this exact request under this exact policy, bound to a
  recomputable `decision_ref`; and the funds could not have reached the payee through this contract any other way.
- **Does not establish:** that the approval was right; anything about delivery after payment; that the payer could not
  have paid outside the contract (making the escrow the only path needs a wallet-level restriction, such as a smart
  account that may only pay through it).
- **One verifier key** controls releases. There is no threshold of several verifiers, and changing the key needs a new deployment.
- **Unaudited.** Source not yet verified on Basescan; the bytecode can be recompiled from `src/` and compared. Use small amounts.

## Files

- `src/VerdictGatedEscrow.sol`: the contract. `src/BIP340.sol`: on-chain BIP-340 verification via `ecrecover`, verbatim from
  TMerlini/hack-ens-recovery (Apache-2.0, credited in its header).
- `escrow_client.py`: fund / review / release / refund / status.
- `test/`: Foundry tests and the ffi signing helper.
