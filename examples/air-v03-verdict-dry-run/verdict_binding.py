"""Build an AIR v0.3-draft-2 `authorizations` binding from a real /ledger proof.

The bound artifact is a live invinoveritas kind-30078 verdict proof (ledger
entry #62): fetched from a public relay (or a previously-fetched cache),
hashed as RFC 8785 JCS of the seven NIP-01 fields, and encoded as an
`issuer_signed` binding whose field set matches draft-2 §2.2 exactly.

Out-of-band retrieval (relay REQ-by-id, same pattern as
`scripts/ledger_relay_audit.py`) is deliberately separate from the §2.7
verification procedure: steps 1–5 are offline against bytes already held.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.proof_signing import PUBLISHED_PUBKEY  # noqa: E402

# Ledger #62 — pre-action /review proof, later cited proven_right by #242.
# Relay-held on nos.lol at dry-run time; OTS-confirmed at bitcoin block 956932.
DEFAULT_EVENT_ID = "926831de4d62bdd5facf5aa01e8fceb17dc489f73addee8c695c2c28b7a1c54f"
DEFAULT_LEDGER_ENTRY = 62
DEFAULT_LEDGER_URL = "https://api.babyblueviper.com/ledger/62"
SCHEME = "invinoveritas.verdict_proof.v1"
SPEC_VERSION = "0.3-draft-2"

# Same relay set the ledger audit already uses.
RELAYS = [
    "nos.lol",
    "relay.damus.io",
    "relay.primal.net",
    "nostr.wine",
    "relay.nostr.band",
]

NIP01_FIELDS = ("id", "pubkey", "created_at", "kind", "tags", "content", "sig")

FIXTURES = _HERE / "fixtures"
ARTIFACT_PATH = FIXTURES / "artifact.json"
FETCH_META_PATH = FIXTURES / "fetch_meta.json"
BINDING_PATH = FIXTURES / "binding.json"


def jcs(value: Any) -> str:
    """RFC 8785 subset used by proof_signing: sorted keys, compact, raw UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_from_artifact_bytes(blob: bytes) -> dict[str, Any]:
    obj = json.loads(blob.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("artifact bytes are not a JSON object")
    return obj


def artifact_dict(event: dict[str, Any]) -> dict[str, Any]:
    missing = [k for k in NIP01_FIELDS if k not in event]
    if missing:
        raise ValueError(f"event missing NIP-01 fields: {missing}")
    return {k: event[k] for k in NIP01_FIELDS}


def artifact_bytes(event: dict[str, Any]) -> bytes:
    """Canonical artifact bytes: JCS of the seven NIP-01 fields.

    Draft-2 §2.3 requires SHA-256 of 'the exact bytes the binding party
    verified'. Relay JSON is not byte-stable across implementations, so this
    dry-run pins those bytes to JCS. That choice is load-bearing and is
    reported as a spec clarification, not hidden.
    """
    return jcs(artifact_dict(event)).encode("utf-8")


def authorization_sha256(event: dict[str, Any]) -> str:
    return hashlib.sha256(artifact_bytes(event)).hexdigest()


def authority_ref_for(pubkey: str) -> str:
    return f"nostr:{pubkey.strip().lower()}"


def published_authority_ref() -> str:
    key = (PUBLISHED_PUBKEY or "").strip().lower()
    if not key:
        raise RuntimeError("PUBLISHED_PUBKEY is empty — cannot mint authority_ref")
    return authority_ref_for(key)


def decision_ref_from_event(event: dict[str, Any]) -> str:
    payload = json.loads(event["content"])
    ref = payload.get("decision_ref")
    if not isinstance(ref, str) or not ref.startswith("sha256:"):
        raise ValueError("event content has no scheme-defined decision_ref")
    return ref


async def _query_relay_for_event(url: str, event_id: str) -> tuple[str, Optional[dict[str, Any]], Optional[str]]:
    """REQ-by-id, same shape as scripts/ledger_relay_audit._query_relay, but
    returns the full event rather than a held-id set."""
    try:
        import websockets
    except ImportError as exc:
        return url, None, f"websockets not installed: {exc}"
    try:
        async with websockets.connect(f"wss://{url}", open_timeout=8, close_timeout=3) as ws:
            await ws.send(json.dumps(["REQ", "air-dryrun", {"ids": [event_id]}]))
            try:
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=8))
                    if msg[0] == "EVENT" and isinstance(msg[2], dict) and msg[2].get("id") == event_id:
                        return url, msg[2], None
                    if msg[0] == "EOSE":
                        return url, None, None
            except asyncio.TimeoutError:
                return url, None, "timeout waiting for EVENT/EOSE"
    except Exception as exc:
        return url, None, f"{type(exc).__name__}: {exc}"


def fetch_event_from_relay(
    event_id: str = DEFAULT_EVENT_ID,
    relays: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch a signed event from the first relay that still holds it.

    Tries the audit relay set in order. Unreachable relays are recorded, not
    treated as 'not held'.
    """
    targets = list(relays or RELAYS)

    async def _all():
        return await asyncio.gather(*[_query_relay_for_event(u, event_id) for u in targets])

    results = asyncio.run(_all())
    tried: list[dict[str, Any]] = []
    found: Optional[tuple[str, dict[str, Any]]] = None
    for url, event, err in results:
        entry = {"relay": url, "held": event is not None, "error": err}
        tried.append(entry)
        if event is not None and found is None:
            found = (url, event)
    if found is None:
        raise RuntimeError(
            f"event {event_id} not returned by any relay in {targets}; tried={tried}"
        )
    url, event = found
    meta = {
        "event_id": event_id,
        "ledger_entry": DEFAULT_LEDGER_ENTRY,
        "ledger_url": DEFAULT_LEDGER_URL,
        "fetched_from": f"wss://{url}",
        "fetched_at": int(time.time()),
        "transport": "relay_event",
        "relays_tried": tried,
        "canonicalization": (
            "RFC 8785 JCS (sorted keys, compact separators, ensure_ascii=False) "
            "over NIP-01 fields {id,pubkey,created_at,kind,tags,content,sig}"
        ),
    }
    return event, meta


def load_cached_artifact(path: Path = ARTIFACT_PATH) -> Optional[bytes]:
    if not path.is_file():
        return None
    return path.read_bytes()


def ledger_anchor_ref(entry: int = DEFAULT_LEDGER_ENTRY) -> dict[str, Any]:
    """Courtesy pull of the public /ledger entry's relay + OTS stamps.

    Not part of the issuer_signed binding (those fields would be
    non-conforming). Recorded so the dry-run can cite the chain-anchored
    precedent on the same event_id.
    """
    import urllib.request

    url = f"https://api.babyblueviper.com/ledger/{entry}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"}
    ots = doc.get("ots_anchor") or (doc.get("commitment_proof") or {}).get("ots_anchor") or {}
    relay = doc.get("relay_anchor") or (doc.get("commitment_proof") or {}).get("relay_anchor") or {}
    outcome = doc.get("outcome_evidence") or {}
    return {
        "ok": True,
        "url": url,
        "event_id": doc.get("event_id"),
        "relay_anchor": relay,
        "ots_anchor": {
            "status": ots.get("status"),
            "precedence": ots.get("precedence"),
            "bitcoin_block_height": ots.get("bitcoin_block_height"),
            "bitcoin_block_hash": ots.get("bitcoin_block_hash"),
            "bitcoin_block_time": ots.get("bitcoin_block_time"),
        },
        "outcome_status": outcome.get("status"),
        "outcome_current": ((outcome.get("per_entry_resolution") or {}).get("current") or {}).get("outcome"),
    }


def write_artifact_cache(
    event: dict[str, Any],
    meta: dict[str, Any],
    artifact_path: Path = ARTIFACT_PATH,
    meta_path: Path = FETCH_META_PATH,
) -> bytes:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    blob = artifact_bytes(event)
    artifact_path.write_bytes(blob)
    meta = dict(meta)
    meta["authorization_sha256"] = hashlib.sha256(blob).hexdigest()
    meta["artifact_bytes"] = len(blob)
    if "ledger_anchor_ref" not in meta:
        meta["ledger_anchor_ref"] = ledger_anchor_ref()
    meta_path.write_text(jcs(meta) + "\n", encoding="utf-8")
    return blob


def obtain_event(
    event_id: str = DEFAULT_EVENT_ID,
    *,
    refetch: bool = False,
    artifact_path: Path = ARTIFACT_PATH,
    meta_path: Path = FETCH_META_PATH,
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    """Return (event, artifact_bytes, obtain_meta).

    Cache hit is the normal path (bytes already held). A miss or `--refetch`
    runs the out-of-band relay fetch and refreshes the cache.
    """
    cached = None if refetch else load_cached_artifact(artifact_path)
    cached_meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            cached_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            cached_meta = {}
    if cached is not None:
        event = event_from_artifact_bytes(cached)
        if event.get("id") == event_id:
            meta = {
                "source": "cache",
                "path": str(artifact_path),
                "originally_fetched_from": cached_meta.get("fetched_from"),
                "cache_fetched_at": cached_meta.get("fetched_at"),
                "bytes": len(cached),
            }
            return event, cached, meta
    event, fetch_meta = fetch_event_from_relay(event_id)
    blob = write_artifact_cache(event, fetch_meta, artifact_path, meta_path)
    meta = {
        "source": "relay",
        "fetched_from": fetch_meta["fetched_from"],
        "fetched_at": fetch_meta["fetched_at"],
        "bytes": len(blob),
        "relays_tried": fetch_meta["relays_tried"],
    }
    return event, blob, meta


def point_in_time_axes() -> dict[str, Any]:
    """§2.5 point-in-time rule, matching worked example (1) byte-for-byte in shape.

    precedence declared; freshness and correctness present-and-null. All three
    keys MUST be present — omission is a different canonical form.
    """
    return {
        "precedence": {"field": "created_at"},
        "freshness": None,
        "correctness": None,
    }


def build_binding(
    event: dict[str, Any],
    *,
    transport_hint: str = "relay_event",
    authorization_uri: str | None = None,
) -> dict[str, Any]:
    """One `authorizations` element: common core + issuer_signed conditional set.

    Field set is the draft-2 table, not a paraphrase:
      common: scheme, decision_ref, trust_model, authority_ref, axes
      issuer_signed: authorization_sha256, authorization_uri, transport_hint
    `anchor` / `locator` are chain_anchored-only and MUST be absent.
    """
    if transport_hint not in {"raw_url", "relay_event", "bundle", "other"}:
        raise ValueError(f"illegal transport_hint: {transport_hint}")
    digest = authorization_sha256(event)
    if authorization_uri is None:
        if transport_hint == "bundle":
            authorization_uri = None
        elif transport_hint == "relay_event":
            authorization_uri = f"nostr:{event['id']}"
        else:
            authorization_uri = DEFAULT_LEDGER_URL
    binding = {
        "scheme": SCHEME,
        "decision_ref": decision_ref_from_event(event),
        "trust_model": "issuer_signed",
        "authority_ref": published_authority_ref(),
        "authorization_uri": authorization_uri,
        "authorization_sha256": digest,
        "transport_hint": transport_hint,
        "axes": point_in_time_axes(),
    }
    problems = binding_shape_errors(binding)
    if problems:
        raise ValueError("constructed binding is non-conforming: " + "; ".join(problems))
    return binding


def binding_shape_errors(binding: Any) -> list[str]:
    """Mechanical draft-2 §2.2 shape check. Empty list = conforming shape."""
    errors: list[str] = []
    if not isinstance(binding, dict):
        return ["binding is not an object"]
    for key in ("scheme", "decision_ref", "trust_model", "authority_ref", "axes"):
        if key not in binding:
            errors.append(f"missing common-core field {key}")
    if binding.get("trust_model") != "issuer_signed":
        errors.append("this builder only emits trust_model=issuer_signed")
        return errors
    for key in ("authorization_sha256", "authorization_uri", "transport_hint"):
        if key not in binding:
            errors.append(f"missing issuer_signed field {key}")
    for illegal in ("anchor", "locator"):
        if illegal in binding:
            errors.append(f"{illegal} is chain_anchored-only; illegal on issuer_signed")
    digest = binding.get("authorization_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or digest != digest.lower() or any(
        c not in "0123456789abcdef" for c in digest
    ):
        errors.append("authorization_sha256 must be 64 lowercase hex")
    hint = binding.get("transport_hint")
    if hint not in {"raw_url", "relay_event", "bundle", "other"}:
        errors.append(f"illegal transport_hint {hint!r}")
    if hint != "bundle" and binding.get("authorization_uri") in (None, ""):
        errors.append("authorization_uri may be null only with transport_hint=bundle")
    axes = binding.get("axes")
    if not isinstance(axes, dict):
        errors.append("axes must be an object")
    else:
        for key in ("precedence", "freshness", "correctness"):
            if key not in axes:
                errors.append(f"axes missing required key {key} (present-and-null, never omitted)")
    return errors


def authorizations_envelope(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "spec_version": SPEC_VERSION,
        "ledger_entry": DEFAULT_LEDGER_ENTRY,
        "ledger_url": DEFAULT_LEDGER_URL,
        "authorizations": [binding],
    }


def write_binding(binding: dict[str, Any], path: Path = BINDING_PATH) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(authorizations_envelope(binding), indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    refetch = "--refetch" in (argv or sys.argv[1:])
    event, blob, meta = obtain_event(refetch=refetch)
    binding = build_binding(event)
    write_binding(binding)
    print(f"obtain: {json.dumps(meta, sort_keys=True)}")
    print(f"artifact_bytes: {len(blob)}")
    print(f"authorization_sha256: {binding['authorization_sha256']}")
    print(f"decision_ref: {binding['decision_ref']}")
    print(f"authority_ref: {binding['authority_ref']}")
    print(f"wrote {ARTIFACT_PATH}")
    print(f"wrote {BINDING_PATH}")
    print(json.dumps(authorizations_envelope(binding), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
