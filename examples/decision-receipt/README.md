# Decision receipts

A decision receipt is a signed record, made before an action, of a bounded-choice decision (OpenAI's Decisions API, Jev, any classifier that picks one of N fixed answers). It holds salted commitments to the question, options, context, choice and gate policy, never the plaintext, and says whether the choice may execute: options marked irreversible need a signed `/review` proof over the same input. The decision is caller-reported; the receipt attests the commitment and the gate, not that the decider chose it. Issued by `POST https://api.babyblueviper.com/decision-receipt`; the signature checks with the free `POST /verify-proof`.

Uniqueness has two scopes, named by `slot_scope` in the signed receipt:

- **account**: one receipt per paying account and `decider.request_id`. Two accounts get two slots.
- **decider**: the decider signs a BIP-340 claim over the commitments with its own key (`decider.pubkey`, `decider_sig`, `salt`, `decider_claimed_at`). One receipt per decider key and `request_id`, whoever pays. A second, different claim is refused uncharged and listed on the slot as a public conflict.

Slots are free to read at `GET /decision-receipt/slot/{slot}`. Every slot goes into a daily, chained Merkle snapshot at `GET /decision-receipt/slots/log`, whose root is stamped with OpenTimestamps.

Check offline, standard library only (Python 3):

    python3 check.py vectors-v0.4.json               # also vectors.json, vectors-v0.2.json, vectors-v0.3.json
    python3 slot_log_check.py 2026-10-10.jsonl --prev 2026-10-09.jsonl  # days from GET /decision-receipt/slots/log/<date>
    python3 slot_log_check.py --inclusion slot.json  # a saved GET /decision-receipt/slot/<slot> body
    python3 -I probes/two_receipt_probe.py .         # Oga's two-receipt probe

`gen_vectors.py` regenerates the vectors. The rules, fields and limits (it binds a key, not a person; only the declared `request_id`; one-day log granularity) are in [SPEC.md](SPEC.md).

Credit: Toshikatsu Oga (HORIZON SHIELD / NENRIN) found that one decision could get two receipts (2026-10-10 00:48 UTC). That finding led to the v0.3 `conflicting_choice` rule and the v0.4 decider-scoped slots. His probe is in `probes/`, unmodified.
