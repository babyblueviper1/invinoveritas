"""Tests on real recorded data (BOLT11 spec vectors, real L402 challenges, real signed invinoveritas verdicts) plus
synthetic invoices/verdicts where a known preimage is needed. No network, no payments.

    python3 -m unittest discover -s tests -v
"""
import base64
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

from helpers import ISSUER_PK, aperture_macaroon, bech32, make_invoice, node_pubkey, sign_verdict  # noqa: E402
from l402_verdict_gate import (GATE_TOOL, ChallengeError, InvoiceError, MockWallet, PaymentBlocked,  # noqa: E402
                               PreimageMismatch, VerdictGate, build_receipt, decode_invoice, l402_request,
                               parse_challenge, verify_receipt, verify_verdict_proof)
from l402_verdict_gate import verify as verify_cli  # noqa: E402
from l402_verdict_gate.bolt11 import _bech32_decode  # noqa: E402
from l402_verdict_gate.receipt import _rid  # noqa: E402


def fx(name):
    with open(os.path.join(HERE, "fixtures", name)) as f:
        return json.load(f)


QUOTE = fx("l402_quote_verdict.json")          # real challenge + real signed approve_with_concerns over it
JOKE = fx("lightningfaucet_joke_402.json")     # real challenge, other endpoint
REJECT = fx("exhibit3_reject.json")            # real signed reject (EIP-3009 payment), reused from the QBT example
SPEC = fx("bolt11_spec_vectors.json")["vectors"]
EV = QUOTE["review_response"]["proof"]["event"]
VERIFIED_AT = json.loads(EV["content"])["verified_at"]
SPEC_HASH = "0001020304050607080900010203040506070809000102030405060708090102"
SPEC_PAYEE = "03e7156ae33b0a208d0744199163177e909e80176e55d97a2f221ede0f934dd9ad"


def quote_gate(**kw):
    cfg = dict(max_cost_sat=100, accountable_party="operator of the daily-briefing agent", now=lambda: VERIFIED_AT + 5)
    cfg.update(kw)
    return VerdictGate(**cfg)


def recorded_post(review, sink=None):
    def post(url, body, headers, timeout):
        if sink is not None:
            sink.append((url, body, headers))
        return 200, copy.deepcopy(review)
    return post


class Http:
    """Fake L402 server: 402 with the given challenge until it sees `L402 <cred>:<preimage>` with a valid preimage."""

    def __init__(self, www, payment_hash):
        self.www, self.ph, self.requests = www, payment_hash, []

    def __call__(self, method, url, headers, body):
        self.requests.append(dict(headers))
        auth = headers.get("Authorization", "")
        if auth.startswith(("L402 ", "LSAT ")):
            pre = auth.rsplit(":", 1)[1]
            if hashlib.sha256(bytes.fromhex(pre)).hexdigest() == self.ph:
                return 200, {"content-type": "application/json"}, b'{"quote": "ok"}'
        return 402, {"www-authenticate": self.www}, b"{}"


class Bolt11(unittest.TestCase):
    def test_spec_vectors(self):
        amounts = [None, 250_000_000, 250_000_000, 2_000_000_000, 2_000_000_000]
        for v, amt in zip(SPEC, amounts):
            d = decode_invoice(v["invoice"])
            self.assertEqual(d.payment_hash, SPEC_HASH)
            self.assertEqual(d.payee_pubkey, SPEC_PAYEE)  # recovered from the signature; the vectors carry no n field
            self.assertEqual(d.timestamp, 1496314658)
            self.assertEqual(d.amount_msat, amt)
        self.assertEqual(decode_invoice(SPEC[0]["invoice"]).description, "Please consider supporting this project")
        self.assertEqual(decode_invoice(SPEC[1]["invoice"]).expiry, 60)
        self.assertEqual(decode_invoice(SPEC[4]["invoice"]).network, "tb")
        self.assertEqual(decode_invoice(SPEC[3]["invoice"]).description_hash,
                         "3925b6f67e2c340036ed12093dd44e0368df1b6ea26c53dbe4811f58fd5db8c1")

    def test_real_invoices_and_payee(self):
        q = decode_invoice(QUOTE["args"]["invoice"])
        j = decode_invoice(JOKE["body"]["invoice"])
        self.assertEqual((q.amount_msat, j.amount_msat), (10_000, 50_000))
        self.assertEqual(q.payee_pubkey, j.payee_pubkey)  # same node issued both
        self.assertEqual(q.payee_pubkey, QUOTE["args"]["payee_pubkey"])
        self.assertEqual(q.expires_at - q.timestamp, 600)

    def test_one_changed_character_fails(self):
        inv = QUOTE["args"]["invoice"]
        i = 60
        bad = inv[:i] + ("q" if inv[i] != "q" else "p") + inv[i + 1:]
        with self.assertRaises(InvoiceError):
            decode_invoice(bad)

    def test_reencoded_amount_changes_recovered_payee(self):
        # An attacker who edits the amount and fixes the checksum cannot keep the payee: recovery yields another key.
        hrp, words = _bech32_decode(QUOTE["args"]["invoice"])
        forged = bech32(hrp.replace("100n", "900n"), words)
        d = decode_invoice(forged)
        self.assertEqual(d.amount_msat, 90_000)
        self.assertNotEqual(d.payee_pubkey, QUOTE["args"]["payee_pubkey"])

    def test_synthetic_roundtrip(self):
        ph = hashlib.sha256(b"x").hexdigest()
        d = decode_invoice(make_invoice(ph, amount="2500u", expiry=300, description="pulse"))
        self.assertEqual((d.payment_hash, d.payee_pubkey, d.amount_msat, d.expiry), (ph, node_pubkey(), 250_000_000, 300))


class Challenges(unittest.TestCase):
    def test_token_variant_real(self):
        c = parse_challenge(QUOTE["www_authenticate"])
        self.assertEqual((c.prefix, c.credential_param), ("L402", "token"))
        self.assertEqual(c.credential_payment_hash, QUOTE["args"]["payment_hash"])
        self.assertEqual(c.credential_location, "lightningfaucet.com")

    def test_aperture_macaroon(self):
        ph = "ab" * 32
        mac = base64.b64encode(aperture_macaroon(ph, caveats=("services=pulse:0", "pulse_valid_until=1791659000"))).decode()
        c = parse_challenge(f'L402 macaroon="{mac}", invoice="{make_invoice(ph)}"')
        self.assertEqual(c.credential_payment_hash, ph)
        self.assertEqual(c.credential_location, "api.example.com")
        self.assertEqual(c.credential_caveats, ("services=pulse:0", "pulse_valid_until=1791659000"))
        self.assertEqual(c.credential_expires_at, 1791659000)
        self.assertEqual(c.authorization("cd" * 32), f"L402 {mac}:{'cd' * 32}")

    def test_lsat_prefix_is_mirrored(self):
        c = parse_challenge(f'LSAT macaroon="AGIAJEemVQUTEyNCR0exk7ek90Cg==", invoice="{SPEC[1]["invoice"]}"')
        self.assertEqual(c.prefix, "LSAT")
        self.assertTrue(c.authorization("00" * 32).startswith("LSAT "))
        self.assertIsNone(c.credential_payment_hash)

    def test_not_a_challenge(self):
        for h in ['Bearer realm="x"', 'L402 macaroon="abc"', ""]:
            with self.assertRaises(ChallengeError):
                parse_challenge(h)


class GateDecisions(unittest.TestCase):
    def setUp(self):
        self.ch = parse_challenge(QUOTE["www_authenticate"])

    def test_recorded_verdict_allows(self):
        g = quote_gate()
        inv, problem = g.local_checks(self.ch, QUOTE["url"])
        self.assertIsNone(problem)
        self.assertEqual(g.bind_args("GET", QUOTE["url"], self.ch, QUOTE["purpose"], inv), QUOTE["args"])
        d = g.decide(QUOTE["review_response"], QUOTE["args"], inv)
        self.assertTrue(d.allowed, d.reason)
        self.assertEqual(d.verdict, "approve_with_concerns")
        self.assertTrue(d.proof["checks"]["args_bound"] and d.proof["checks"]["tool_bound"])

    def test_check_sends_exact_args(self):
        sent = []
        g = quote_gate(post_json=recorded_post(QUOTE["review_response"], sent), api_key="k")
        d = g.check("GET", QUOTE["url"], self.ch, QUOTE["purpose"])
        self.assertTrue(d.allowed, d.reason)
        url, body, headers = sent[0]
        self.assertTrue(url.endswith("/review"))
        self.assertEqual(body["action_binding"], {"tool": GATE_TOOL, "agent_id": "l402-agent", "args": QUOTE["args"]})
        self.assertTrue(body["sign"])
        self.assertEqual(headers["Authorization"], "Bearer k")

    def test_drift_in_any_bound_field_blocks(self):
        g = quote_gate()
        for k, v in [("url", "https://lightningfaucet.com/api/l402/joke"), ("amount_msat", "20000"),
                     ("purpose", "something else"), ("method", "POST"), ("payee_pubkey", node_pubkey())]:
            args = dict(QUOTE["args"], **{k: v})
            d = g.decide(QUOTE["review_response"], args)
            self.assertFalse(d.allowed, k)
            self.assertIn("args_bound", d.reason)

    def test_stale_verdict_blocks(self):
        d = quote_gate(now=lambda: VERIFIED_AT + 121).decide(QUOTE["review_response"], QUOTE["args"])
        self.assertFalse(d.allowed)
        self.assertIn("old", d.reason)

    def test_expired_invoice_blocks_even_with_fresh_verdict(self):
        exp = int(QUOTE["args"]["invoice_expires_at"])
        d = quote_gate(now=lambda: exp, max_verdict_age_s=10**6).decide(QUOTE["review_response"], QUOTE["args"])
        self.assertFalse(d.allowed)
        self.assertIn("expired", d.reason)

    def test_tampered_proof_blocks_in_any_fail_mode(self):
        rv = copy.deepcopy(QUOTE["review_response"])
        rv["proof"]["event"]["content"] = rv["proof"]["event"]["content"].replace("approve_with_concerns", "approve")
        for mode in ("closed", "open"):
            d = quote_gate(fail_mode=mode).decide(rv, QUOTE["args"])
            self.assertFalse(d.allowed)
            self.assertIn("proof failed", d.reason)

    def test_other_issuer_key_blocks(self):
        d = quote_gate(pubkey=ISSUER_PK).decide(QUOTE["review_response"], QUOTE["args"])
        self.assertFalse(d.allowed)
        self.assertIn("issued_by_invinoveritas", d.reason)

    def test_real_signed_reject_blocks(self):
        g = VerdictGate(tool=REJECT["tool"], now=lambda: 1791480971)
        self.assertTrue(verify_verdict_proof(REJECT["review_response"]["proof"]["event"], args=REJECT["args"], tool=REJECT["tool"])["valid"])
        d = g.decide(REJECT["review_response"], REJECT["args"])
        self.assertFalse(d.allowed)
        self.assertEqual(d.verdict, "reject")
        self.assertIn("not in proceed_on", d.reason)

    def test_strict_proceed_on(self):
        d = quote_gate(proceed_on=["approve"]).decide(QUOTE["review_response"], dict(QUOTE["args"], proceed_on=["approve"]))
        self.assertFalse(d.allowed)  # args now differ from what was signed, and the verdict is not plain approve

    def test_fail_closed_and_open(self):
        def down(*a):
            raise TimeoutError()
        d = quote_gate(post_json=down).check("GET", QUOTE["url"], self.ch, QUOTE["purpose"])
        self.assertFalse(d.allowed)
        self.assertIn("closed", d.reason)
        d = quote_gate(post_json=down, fail_mode="open").check("GET", QUOTE["url"], self.ch, QUOTE["purpose"])
        self.assertTrue(d.allowed and d.fail_open)
        d = quote_gate(post_json=lambda *a: (200, {"verdict": "approve"})).check("GET", QUOTE["url"], self.ch, QUOTE["purpose"])
        self.assertFalse(d.allowed)
        self.assertIn("no signed proof", d.reason)

    def test_threshold_skips_review(self):
        def never(*a):
            raise AssertionError("review must not be called below the threshold")
        d = quote_gate(post_json=never, review_above_sat=1000).check("GET", QUOTE["url"], self.ch, QUOTE["purpose"])
        self.assertTrue(d.allowed and d.skipped)

    def test_local_checks_block_before_review(self):
        def never(*a):
            raise AssertionError("review must not be called")
        cases = [
            (quote_gate(post_json=never, max_cost_sat=5), self.ch, QUOTE["url"], "above max_cost_sat"),
            (quote_gate(post_json=never, network="tb"), self.ch, QUOTE["url"], "network"),
            (quote_gate(post_json=never, now=lambda: 1791658598), self.ch, QUOTE["url"], "expired"),
            (quote_gate(post_json=never), self.ch, "https://evil.example/api/l402/quote", "scoped to"),
            (quote_gate(post_json=never), parse_challenge(f'L402 macaroon="AGIA", invoice="{SPEC[0]["invoice"]}"'),
             QUOTE["url"], "amount-less"),
        ]
        # the joke endpoint's credential paired with the quote endpoint's invoice
        joke_tok = parse_challenge(JOKE["www_authenticate"]).credential
        mixed = parse_challenge(f'L402 token="{joke_tok}", invoice="{QUOTE["args"]["invoice"]}"')
        cases.append((quote_gate(post_json=never), mixed, QUOTE["url"], "different payment_hash"))
        for g, ch, url, want in cases:
            d = g.check("GET", url, ch, "x")
            self.assertFalse(d.allowed, want)
            self.assertIn(want, d.reason)


class Client(unittest.TestCase):
    def test_real_verdict_wrong_preimage_never_presented(self):
        ph = QUOTE["args"]["payment_hash"]
        http = Http(QUOTE["www_authenticate"], ph)
        wallet = MockWallet({ph: "00" * 32})  # a wallet/route that lies about the preimage
        g = quote_gate(post_json=recorded_post(QUOTE["review_response"]))
        with self.assertRaises(PreimageMismatch):
            l402_request(QUOTE["url"], g, wallet, purpose=QUOTE["purpose"], http=http, now=lambda: VERIFIED_AT + 6)
        self.assertEqual(len(wallet.calls), 1)
        self.assertEqual(len(http.requests), 1)  # credential never sent

    def test_blocked_means_wallet_untouched(self):
        ph = QUOTE["args"]["payment_hash"]
        http = Http(QUOTE["www_authenticate"], ph)
        wallet = MockWallet({ph: "00" * 32})
        g = quote_gate(post_json=recorded_post(QUOTE["review_response"]))
        with self.assertRaises(PaymentBlocked) as cm:
            l402_request(QUOTE["url"], g, wallet, purpose="a different purpose than the verdict saw", http=http)
        self.assertEqual(wallet.calls, [])
        self.assertIn("args_bound", cm.exception.decision.reason)

    def _synthetic(self, verdict="approve"):
        pre = hashlib.sha256(b"preimage").hexdigest()
        ph = hashlib.sha256(bytes.fromhex(pre)).hexdigest()
        inv = make_invoice(ph, amount="10u", timestamp=1791657998, expiry=600, description="pulse match stats")
        mac = base64.b64encode(aperture_macaroon(ph, location="pulse.example")).decode()
        www = f'L402 macaroon="{mac}", invoice="{inv}"'
        url = "https://pulse.example/v1/match/fra-mar/live"
        g = VerdictGate(pubkey=ISSUER_PK, now=lambda: 1791658015)
        ch = parse_challenge(www)
        args = g.bind_args("GET", url, ch, "live stats for the agent's match summary", decode_invoice(inv))
        g._post = recorded_post(sign_verdict(args, GATE_TOOL, verdict=verdict))
        return g, url, www, ph, pre

    def test_end_to_end_receipt(self):
        g, url, www, ph, pre = self._synthetic()
        http = Http(www, ph)
        status, _, body, receipt = l402_request(url, g, MockWallet({ph: pre}, fee_msat=3000), purpose="live stats for the agent's match summary",
                                                http=http, now=lambda: 1791658020)
        self.assertEqual((status, body), (200, b'{"quote": "ok"}'))
        self.assertTrue(http.requests[1]["Authorization"].startswith("L402 ") and http.requests[1]["Authorization"].endswith(":" + pre))
        r = verify_receipt(receipt, pubkey=ISSUER_PK)
        self.assertTrue(r["valid"], r)
        self.assertEqual(receipt["fee_msat"], "3000")
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "receipt.json")
            with open(path, "w") as f:
                json.dump(receipt, f)
            with redirect_stdout(out):
                self.assertEqual(verify_cli.main([path, "--pubkey", ISSUER_PK]), 0)
                self.assertEqual(verify_cli.main([path]), 1)  # default pin = invinoveritas key
        self.assertIn("FAIL proof_issued_by_invinoveritas", out.getvalue())

    def test_synthetic_reject_blocks(self):
        g, url, www, ph, pre = self._synthetic(verdict="reject")
        wallet = MockWallet({ph: pre})
        with self.assertRaises(PaymentBlocked):
            l402_request(url, g, wallet, purpose="live stats for the agent's match summary", http=Http(www, ph))
        self.assertEqual(wallet.calls, [])


class Receipts(unittest.TestCase):
    def test_real_verdict_receipt_checks(self):
        # Real verdict + real invoice. We do not know the real preimage (nothing was paid), so every check passes
        # except the preimage one: the receipt format catches a payer who claims a payment it cannot prove.
        r = build_receipt(GATE_TOOL, QUOTE["args"], EV, "00" * 32, VERIFIED_AT + 6, 10_000, 0)
        v = verify_receipt(r)
        failed = [k for k, ok in v["checks"].items() if not ok]
        self.assertEqual(failed, ["preimage_matches_payment_hash"])

    def test_tampering_breaks_receipt(self):
        g, url, www, ph, pre = Client()._synthetic()
        _, _, _, receipt = l402_request(url, g, MockWallet({ph: pre}), purpose="live stats for the agent's match summary",
                                        http=Http(www, ph), now=lambda: 1791658020)
        for k, v in [("paid_at", 1791658999), ("preimage", "11" * 32), ("amount_msat", "1")]:
            bad = dict(receipt, **{k: v})
            self.assertFalse(verify_receipt(bad, pubkey=ISSUER_PK)["valid"], k)
        late = dict(receipt, paid_at=1791658200)
        late["receipt_id"] = _rid(late)
        c = verify_receipt(late, pubkey=ISSUER_PK)["checks"]
        self.assertFalse(c["verdict_fresh_at_reported_payment"])


if __name__ == "__main__":
    unittest.main()
