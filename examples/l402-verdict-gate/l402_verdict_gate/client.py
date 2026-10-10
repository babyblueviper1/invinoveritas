"""An L402 HTTP client with the verdict gate between the 402 and the payment.

The same loop as lnget (request -> 402 -> parse challenge -> pay -> retry with `Authorization: L402 <mac>:<preimage>`),
with two additions: the payment happens only if the gate allows it, and after paying the client checks
sha256(preimage) == payment_hash before presenting the credential, then writes a receipt.
"""
import hashlib
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from .challenge import parse_challenge
from .gate import Decision, VerdictGate
from .receipt import build_receipt
from .wallet import Wallet


class PaymentBlocked(Exception):
    def __init__(self, decision: Decision):
        super().__init__(f"payment blocked: {decision.reason}")
        self.decision = decision


class PreimageMismatch(Exception):
    pass


def urllib_http(method, url, headers, body, timeout=60):
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def l402_request(url: str, gate: VerdictGate, wallet: Wallet, method: str = "GET", headers: Optional[dict] = None,
                 body: Optional[bytes] = None, purpose: Optional[str] = None, max_fee_sat: int = 10, timeout_s: int = 60,
                 http: Callable = urllib_http, on_decision: Optional[Callable] = None,
                 now: Callable[[], float] = time.time):
    """Returns (status, headers, body, receipt). receipt is None when no payment was needed.
    Raises PaymentBlocked when the gate says no (nothing was paid) and PreimageMismatch when the wallet returns a
    preimage that does not open the invoice (paid, but the credential is never presented)."""
    headers = dict(headers or {})
    status, h, b = http(method, url, headers, body)
    if status != 402 or "www-authenticate" not in h:
        return status, h, b, None
    ch = parse_challenge(h["www-authenticate"])
    d = gate.check(method, url, ch, purpose)
    if on_decision:
        on_decision(d)
    if not d.allowed:
        raise PaymentBlocked(d)
    paid = wallet.pay_invoice(ch.invoice, max_fee_sat, timeout_s)
    if hashlib.sha256(bytes.fromhex(paid.preimage)).hexdigest() != d.args["payment_hash"]:
        raise PreimageMismatch("wallet returned a preimage that does not hash to the bound payment_hash")
    receipt = build_receipt(gate.tool, d.args, d.event, paid.preimage, int(now()),
                            paid.amount_msat or int(d.args["amount_msat"]), paid.fee_msat)
    headers["Authorization"] = ch.authorization(paid.preimage)
    status, h, b = http(method, url, headers, body)
    return status, h, b, receipt
