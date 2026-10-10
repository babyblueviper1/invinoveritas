"""The payment receipt: verdict + payment_hash + preimage in one record that anyone can recompute offline.

    python3 -m l402_verdict_gate.verify receipt.json

What a valid receipt establishes: invinoveritas's published key signed a verdict over this exact payment intent
(endpoint, method, invoice, amount, payee, payment_hash, the agent's stated purpose); the verdict allowed paying; the
preimage hashes to that payment_hash, so this invoice was paid (only the payee could reveal it); and the bound invoice
decodes to the bound fields with a valid payee signature.
What it does not establish: that the payment happened after the verdict (paid_at is payer-reported; Lightning has no
public settlement log), that the reviewer had full context, or that the verdict was right.
"""
import hashlib

from . import bolt11
from .jcs import canonicalize
from .proof import verify_verdict_proof

SCHEMA = "invinoveritas.l402_payment_receipt.v1"


def _rid(r: dict) -> str:
    return "sha256:" + hashlib.sha256(canonicalize({k: v for k, v in r.items() if k != "receipt_id"}).encode()).hexdigest()


def build_receipt(tool: str, args: dict, event, preimage: str, paid_at: int, amount_msat: int, fee_msat: int) -> dict:
    r = {"schema": SCHEMA, "tool": tool, "args": args, "verdict_event": event, "payment_hash": args["payment_hash"],
         "preimage": preimage.lower(), "paid_at": int(paid_at), "amount_msat": str(amount_msat), "fee_msat": str(fee_msat),
         "governed": event is not None}
    r["receipt_id"] = _rid(r)
    return r


def verify_receipt(r: dict, pubkey=None) -> dict:
    c = {}
    a = r.get("args") or {}
    try:
        c["receipt_id_recomputes"] = r.get("receipt_id") == _rid(r)
        c["preimage_matches_payment_hash"] = hashlib.sha256(bytes.fromhex(r["preimage"])).hexdigest() == r["payment_hash"]
        c["payment_hash_is_bound"] = r["payment_hash"] == a.get("payment_hash")
        inv = bolt11.decode(a["invoice"])
        c["invoice_matches_bound_fields"] = (inv.payment_hash == a["payment_hash"] and str(inv.amount_msat) == a["amount_msat"]
                                             and inv.payee_pubkey == a["payee_pubkey"]
                                             and str(inv.expires_at) == a["invoice_expires_at"])
        c["paid_before_invoice_expiry"] = int(r["paid_at"]) < int(a["invoice_expires_at"])
        if r.get("verdict_event") is None:
            c["governed"] = False  # paid below the review threshold or fail-open: no verdict covers it
        else:
            p = verify_verdict_proof(r["verdict_event"], pubkey=pubkey, args=a, tool=r["tool"])
            c.update({f"proof_{k}": v for k, v in p["checks"].items()})
            c["verdict_allows_payment"] = p.get("verdict") in a.get("proceed_on", [])
            va = float(p.get("verified_at") or 0)
            c["verdict_before_reported_payment"] = va <= int(r["paid_at"])
            c["verdict_fresh_at_reported_payment"] = int(r["paid_at"]) - va <= int(a.get("max_verdict_age_s", 0))
    except Exception as e:
        return {"valid": False, "checks": c, "error": f"malformed receipt: {e}"}
    return {"valid": all(c.values()), "checks": c}
