"""Pluggable Lightning wallet. The gate never touches keys; it only decides whether pay_invoice() is called.

Any wallet works if it can pay a BOLT11 invoice and return the preimage: LND, Core Lightning, a Wavelength embedded
wallet, NWC, an LNbits key. Implement `pay_invoice` and pass it in.
"""
import base64
import json
import ssl
import urllib.request
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class PaymentResult:
    preimage: str          # 64 hex
    amount_msat: int
    fee_msat: int = 0


class Wallet(Protocol):
    def pay_invoice(self, bolt11: str, max_fee_sat: int, timeout_s: int) -> PaymentResult: ...


class MockWallet:
    """Test wallet: returns preimages it was given, keyed by payment_hash. Records every call. Moves no money."""

    def __init__(self, preimages: dict, fee_msat: int = 0):
        self.preimages, self.fee_msat, self.calls = dict(preimages), fee_msat, []

    def pay_invoice(self, bolt11: str, max_fee_sat: int, timeout_s: int) -> PaymentResult:
        from .bolt11 import decode
        inv = decode(bolt11)
        self.calls.append(bolt11)
        if inv.payment_hash not in self.preimages:
            raise RuntimeError("mock wallet: no route")
        return PaymentResult(self.preimages[inv.payment_hash], inv.amount_msat or 0, self.fee_msat)


class LndRestWallet:
    """LND over its REST API (POST /v1/channels/transactions). Use a macaroon baked for payments only, e.g.
    `lncli bakemacaroon offchain:read offchain:write`, never admin.macaroon. Not exercised by the tests (no real payments)."""

    def __init__(self, host: str, macaroon_path: str, tls_cert_path: Optional[str] = None):
        self.host = host.rstrip("/")
        with open(macaroon_path, "rb") as f:
            self._mac = f.read().hex()
        self._ctx = ssl.create_default_context(cafile=tls_cert_path) if tls_cert_path else ssl.create_default_context()

    def pay_invoice(self, bolt11: str, max_fee_sat: int, timeout_s: int) -> PaymentResult:
        body = {"payment_request": bolt11, "fee_limit": {"fixed": str(max_fee_sat)}}
        req = urllib.request.Request(f"{self.host}/v1/channels/transactions", data=json.dumps(body).encode(), method="POST",
                                     headers={"Grpc-Metadata-macaroon": self._mac, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s, context=self._ctx) as r:
            j = json.loads(r.read())
        if j.get("payment_error"):
            raise RuntimeError(f"lnd: {j['payment_error']}")
        pre = base64.b64decode(j["payment_preimage"]).hex()
        route = j.get("payment_route") or {}
        return PaymentResult(pre, int(route.get("total_amt_msat", 0)), int(route.get("total_fees_msat", 0)))
