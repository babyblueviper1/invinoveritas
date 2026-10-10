"""invinoveritas verdict gate for L402: an independent, signed answer to "should this agent pay this invoice?"

L402 already answers whether the agent CAN pay (it has a wallet, a budget, and an invoice). The gate answers whether it
SHOULD: right endpoint, right price, right moment, for the purpose the agent states. Flow:
  1. Local checks, free: the invoice signature verifies, it has an amount, it is unexpired, it is on the expected
     network, it is within max_cost_sat, and the credential commits to the same payment_hash.
  2. POST /review with the exact payment intent as action_binding.args (sign=true).
  3. Verify the returned proof OFFLINE: signature, pinned key, decision_ref, args hash, tool hash.
  4. Allow only if the verdict is in proceed_on, it is younger than max_verdict_age_s, and the invoice is still unexpired.
Fail mode: "closed" (default) blocks when the reviewer is unreachable; "open" allows and flags fail_open.
A proof that fails verification ALWAYS blocks: a bad proof is a finding, not an outage.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from . import bolt11
from .challenge import Challenge
from .proof import sha256_hex, verify_verdict_proof

DEFAULT_BASE_URL = "https://api.babyblueviper.com"
GATE_TOOL = "l402_lightning_payment"
PREIMAGE_RULE = "pay only the invoice bound here; sha256(preimage) must equal payment_hash"


@dataclass
class Decision:
    allowed: bool
    reason: str
    args: Optional[dict] = None
    verdict: Optional[str] = None
    confidence: Optional[float] = None
    summary: Optional[str] = None
    event: Optional[dict] = None
    proof: Optional[dict] = None
    fail_open: bool = False
    skipped: bool = False
    review: Any = None
    invoice: Optional[bolt11.Invoice] = field(default=None, repr=False)


def _post_json(url, body, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())


class VerdictGate:
    def __init__(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL,
                 proceed_on=("approve", "approve_with_concerns"), fail_mode: str = "closed",
                 max_verdict_age_s: int = 120, review_above_sat: Optional[int] = None,
                 max_cost_sat: Optional[int] = None, network: str = "bc", agent_id: str = "l402-agent",
                 accountable_party: Optional[str] = None, context: Optional[str] = None, pubkey: Optional[str] = None,
                 timeout_s: int = 120, now: Callable[[], float] = time.time,
                 post_json: Callable = _post_json, tool: str = GATE_TOOL):
        """review_above_sat: invoices below this many sats pass without a review (decision.skipped). A review costs
        about 1,000 sats and takes 20-60 s, so gate the payments that matter, not every 10-sat call.
        max_cost_sat: hard ceiling checked locally, like lnget --max-cost; above it nothing is reviewed or paid."""
        self.api_key, self.base_url = api_key, base_url.rstrip("/")
        self.proceed_on, self.fail_mode = list(proceed_on), fail_mode
        self.max_age, self.review_above_sat, self.max_cost_sat = max_verdict_age_s, review_above_sat, max_cost_sat
        self.network, self.agent_id, self.accountable_party, self.context = network, agent_id, accountable_party, context
        self.pubkey, self.timeout_s, self.now, self._post, self.tool = pubkey, timeout_s, now, post_json, tool

    # ---- the exact intent the verdict binds -------------------------------------------------------------------
    def bind_args(self, method: str, url: str, challenge: Challenge, purpose: Optional[str], inv: bolt11.Invoice) -> dict:
        a = {
            "protocol": challenge.prefix, "method": method.upper(), "url": url,
            "invoice": inv.bolt11, "network": inv.network,
            "amount_msat": str(inv.amount_msat), "payee_pubkey": inv.payee_pubkey, "payment_hash": inv.payment_hash,
            "invoice_created_at": str(inv.timestamp), "invoice_expires_at": str(inv.expires_at),
            "credential_sha256": sha256_hex(challenge.credential),
            "preimage_rule": PREIMAGE_RULE, "proceed_on": self.proceed_on, "max_verdict_age_s": str(self.max_age),
        }
        if inv.description is not None:
            a["invoice_description"] = inv.description
        if purpose:
            a["purpose"] = purpose
        if self.accountable_party:
            a["accountable_party"] = self.accountable_party
        return a

    def local_checks(self, challenge: Challenge, url: Optional[str] = None) -> tuple:
        """Free checks before anything is reviewed or paid. Returns (invoice, None) or (invoice|None, reason)."""
        try:
            inv = bolt11.decode(challenge.invoice)
        except bolt11.InvoiceError as e:
            return None, f"invoice does not decode/verify: {e}"
        if inv.network != self.network:
            return inv, f"invoice is for network {inv.network!r}, expected {self.network!r}"
        if inv.amount_msat is None:
            return inv, "amount-less invoice: refusing to let the payer pick the amount"
        if self.max_cost_sat is not None and inv.amount_msat > self.max_cost_sat * 1000:
            return inv, f"invoice is {inv.amount_msat // 1000} sats, above max_cost_sat {self.max_cost_sat}"
        if self.now() >= inv.expires_at:
            return inv, "invoice already expired"
        if challenge.credential_payment_hash and challenge.credential_payment_hash != inv.payment_hash:
            return inv, "credential commits to a different payment_hash than the invoice"
        # Added after the recorded verdict flagged it (tests/fixtures/l402_quote_verdict.json, issue 2): a credential
        # scoped to another origin is worthless here, so do not pay for it.
        host = (urlsplit(url).hostname or "").lower() if url else ""
        loc = (challenge.credential_location or "").lower()
        if host and loc and not (host == loc or host.endswith("." + loc) or urlsplit("//" + loc).hostname == host):
            return inv, f"credential is scoped to {challenge.credential_location!r}, not {host!r}"
        if challenge.credential_expires_at is not None and self.now() >= challenge.credential_expires_at:
            return inv, "credential already expired"
        return inv, None

    def _artifact(self, a: dict) -> str:
        sats = int(a["amount_msat"]) / 1000
        return "\n\n".join([
            f"An AI agent is about to pay a Lightning invoice to access an {a['protocol']}-protected HTTP endpoint: "
            f"{a['method']} {a['url']}, {sats:g} sats to node {a['payee_pubkey']}.",
            f"Agent's stated purpose: {a['purpose']}" if a.get("purpose") else "Purpose: not stated by the agent.",
            "Exact payment intent (the agent pays only this invoice, and only if this verdict allows it): "
            + json.dumps({k: a[k] for k in a if k != "proceed_on"}, sort_keys=True),
            "Checks the payer already ran locally: the BOLT11 signature verifies and recovers payee_pubkey; the invoice has "
            "an amount, is unexpired and within the agent's per-call ceiling; the L402 credential commits to this payment_hash. "
            "Question for the reviewer: given the stated purpose, is this the right endpoint, a sensible price and the right "
            f"moment to pay? The payer proceeds only on {json.dumps(a['proceed_on'])}.",
        ])

    def _unavailable(self, reason, args, inv):
        if self.fail_mode == "open":
            return Decision(True, f"reviewer unavailable ({reason}); allowed because fail_mode is 'open'", args, fail_open=True, invoice=inv)
        return Decision(False, f"reviewer unavailable ({reason}); blocked because fail_mode is 'closed'", args, invoice=inv)

    def decide(self, review: Any, args: dict, inv: Optional[bolt11.Invoice] = None) -> Decision:
        """Decide from an already-obtained /review response (no network). Used for tests and replays."""
        rv = review if isinstance(review, dict) else {}
        res = rv.get("result") if isinstance(rv.get("result"), dict) else rv
        pb = res.get("proof") or rv.get("proof")
        event = pb.get("event", pb) if isinstance(pb, dict) else None
        if not isinstance(event, dict) or "sig" not in event:
            d = self._unavailable("response carried no signed proof", args, inv)
            d.review = review
            return d
        proof = verify_verdict_proof(event, pubkey=self.pubkey, args=args, tool=self.tool)
        base = dict(args=args, verdict=proof.get("verdict"), confidence=res.get("confidence"),
                    summary=res.get("summary"), event=event, proof=proof, review=review, invoice=inv)
        if not proof["valid"]:
            failed = [k for k, v in proof["checks"].items() if not v]
            return Decision(False, f"proof failed local verification: {', '.join(failed) or proof.get('error')}", **base)
        if proof["verdict"] not in self.proceed_on:
            return Decision(False, f"verdict {proof['verdict']!r} is not in proceed_on {self.proceed_on}", **base)
        t = self.now()
        age = t - float(proof["verified_at"])
        if not age <= self.max_age:
            return Decision(False, f"verdict is {age:.0f}s old (max {self.max_age}s)", **base)
        if t >= int(args["invoice_expires_at"]):
            return Decision(False, "invoice expired before it could be paid", **base)
        return Decision(True, f"verdict {proof['verdict']!r} verified offline", **base)

    def check(self, method: str, url: str, challenge: Challenge, purpose: Optional[str] = None) -> Decision:
        inv, problem = self.local_checks(challenge, url)
        if problem:
            return Decision(False, problem, invoice=inv)
        args = self.bind_args(method, url, challenge, purpose, inv)
        if self.review_above_sat is not None and inv.amount_msat < self.review_above_sat * 1000:
            return Decision(True, f"below the review threshold of {self.review_above_sat} sats", args, skipped=True, invoice=inv)
        body = {
            "artifact": self._artifact(args), "artifact_type": "onchain_action", "sign": True,
            "action_binding": {"tool": self.tool, "agent_id": self.agent_id, "args": args},
            "severity_threshold": "medium", "confidentiality_tier": "partial_disclosure",
            "disclosed_summary": f"L402 payment {inv.amount_msat / 1000:g} sats for {method.upper()} {url}",
        }
        if self.context:
            body["context"] = self.context
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            status, review = self._post(f"{self.base_url}/review", body, headers, self.timeout_s)
        except urllib.error.HTTPError as e:
            return self._unavailable(f"/review returned HTTP {e.code}", args, inv)
        except Exception as e:  # timeout, DNS, refused
            return self._unavailable(type(e).__name__, args, inv)
        if status != 200:
            return self._unavailable(f"/review returned HTTP {status}", args, inv)
        return self.decide(review, args, inv)
