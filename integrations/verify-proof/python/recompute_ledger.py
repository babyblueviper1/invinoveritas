#!/usr/bin/env python3
"""recompute_ledger — recompute invinoveritas's ENTIRE public verdict ledger yourself, trusting nothing.

This is the whole-ledger companion to invinoveritas_verify.py (which verifies one proof). It pulls the
public ledger, then for every entry fetches the RAW signed verdict event straight from public Nostr
relays (not from us), recomputes the NIP-01 event id from the bytes the relay returns, and verifies the
BIP-340 schnorr signature against invinoveritas's PUBLISHED key. A verdict only counts as verified if
the math you ran on relay-served bytes agrees — our API's claim is never trusted.

Zero dependencies, on purpose: the crypto is the audited pure-stdlib code in invinoveritas_verify.py,
and the Nostr relay fetch is a minimal stdlib WebSocket client (socket + ssl) — nothing to pip-install,
nothing to trust but code you can read.

Honest about coverage: verdict events are NIP-33 parameterized-replaceable (kind 30078), so an older
verdict's raw event may have rotated off relays. Those can't be schnorr-recomputed from relays anymore,
but every entry also carries a Bitcoin-PoW OpenTimestamps anchor on its event id — recompute that,
relay-independently, with:  ots verify -d <event_id> <event_id>.ots

Usage:
    python recompute_ledger.py                      # recompute the live public ledger
    python recompute_ledger.py --ledger URL         # point at a specific /ledger
    python recompute_ledger.py --json               # machine-readable result
    python recompute_ledger.py --pubkey HEX         # pin a different expected key

Exit 0 iff every relay-retrievable verdict verified against the published key.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

# Reuse the audited, zero-dependency crypto — never re-implement it (one source of truth).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from invinoveritas_verify import nostr_event_id, schnorr_verify, PUBLISHED_PUBKEY  # noqa: E402

DEFAULT_LEDGER = "https://api.babyblueviper.com/ledger"


# ── minimal Nostr relay fetch over a stdlib WebSocket (no external deps) ──────────────────────────────
def _ws_fetch_event(relay_url: str, event_id: str, timeout: float = 6.0) -> dict | None:
    """Open a WebSocket to a Nostr relay, REQ one event by id, return the raw event dict (or None)."""
    return _ws_fetch_ids(relay_url, [event_id], timeout=timeout).get(event_id)


def _ws_connect(relay_url: str, timeout: float):
    """Open + handshake a relay WebSocket; return (sock, leftover_buf) or (None, b'') on failure."""
    u = urlparse(relay_url if "://" in relay_url else "wss://" + relay_url)
    host = u.hostname
    port = u.port or (443 if u.scheme == "wss" else 80)
    path = u.path or "/"
    raw = socket.create_connection((host, port), timeout=min(timeout, 8.0))
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if u.scheme == "wss" else raw
    sock.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(handshake.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(4096)
        if not chunk:
            sock.close()
            return None, b""
        resp += chunk
    if b" 101 " not in resp.split(b"\r\n", 1)[0]:
        sock.close()
        return None, b""
    return sock, resp.split(b"\r\n\r\n", 1)[1]


def _ws_req(sock, buf: bytes, req: list, timeout: float) -> list:
    """Send a REQ, collect EVENTs until EOSE/CLOSED/timeout. Returns the raw event dicts."""
    _ws_send(sock, json.dumps(req))
    deadline = time.time() + timeout
    got: list = []
    while time.time() < deadline:
        try:
            msg, buf = _ws_read_frame(sock, buf)
        except (socket.timeout, ConnectionError, OSError):
            break
        if msg is None:
            continue
        try:
            data = json.loads(msg)
        except Exception:
            continue
        if data and data[0] == "EVENT" and len(data) >= 3 and isinstance(data[2], dict):
            got.append(data[2])
        elif data and data[0] in ("EOSE", "CLOSED"):
            break
    return got


def _ws_fetch_ids(relay_url: str, event_ids: list, timeout: float = 15.0) -> dict:
    """One connection, one REQ for many ids; return {id: raw event} for what the relay served.
    Batching is what keeps a full-ledger run inside a CI time limit: one connection per event
    per relay took over 10 minutes on a 269-entry ledger (vlc-1#16)."""
    ids = [i for i in dict.fromkeys(event_ids) if i]
    if not ids:
        return {}
    sock, buf = _ws_connect(relay_url, timeout)
    if sock is None:
        return {}
    try:
        events = _ws_req(sock, buf, ["REQ", "s", {"ids": ids, "limit": len(ids)}], timeout)
        return {str(ev.get("id", "")): ev for ev in events}
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _ws_fetch_filter(relay_url: str, nostr_filter: dict, timeout: float = 15.0) -> list:
    """One connection, one arbitrary-filter REQ (kind/author/tag, not just ids); return every raw
    event the relay serves before EOSE/CLOSED/timeout. Used for the broadcast-head discovery query
    below, which — unlike the per-verdict fetch above — doesn't know an event id in advance."""
    sock, buf = _ws_connect(relay_url, timeout)
    if sock is None:
        return []
    try:
        return _ws_req(sock, buf, ["REQ", "h", nostr_filter], timeout)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _ws_send(sock, text: str) -> None:
    """Send one masked text frame (clients MUST mask, RFC 6455)."""
    payload = text.encode()
    header = bytearray([0x81])  # FIN + text opcode
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    mask = os.urandom(4)
    header += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(header) + masked)


def _ws_read_frame(sock, buf: bytes):
    """Read one server text frame from buf (+socket). Returns (text_or_None, remaining_buf)."""
    def _need(n):
        nonlocal buf
        while len(buf) < n:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("relay closed")
            buf += chunk
    _need(2)
    b1, b2 = buf[0], buf[1]
    opcode = b1 & 0x0F
    length = b2 & 0x7F
    masked = b2 & 0x80
    idx = 2
    if length == 126:
        _need(4); length = struct.unpack(">H", buf[2:4])[0]; idx = 4
    elif length == 127:
        _need(10); length = struct.unpack(">Q", buf[2:10])[0]; idx = 10
    mask = b""
    if masked:
        _need(idx + 4); mask = buf[idx:idx + 4]; idx += 4
    _need(idx + length)
    payload = bytearray(buf[idx:idx + length])
    buf = buf[idx + length:]
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if opcode == 0x8:  # close
        raise ConnectionError("relay sent close")
    if opcode in (0x1, 0x2):
        return payload.decode("utf-8", "replace"), buf
    return None, buf  # ping/pong/continuation — ignore for our purpose


GENESIS_MARKER = "invinoveritas-ledger-genesis:before-entry-40"


def _canon_json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _genesis_head_hash() -> str:
    import hashlib
    return hashlib.sha256(GENESIS_MARKER.encode("utf-8")).hexdigest()


def _verify_chain(entries: list[dict], ledger_url: str) -> list[dict]:
    """Independently recompute the hash-chain (entries from #40 on) — not from the index's own
    `chain` field taken on faith, but by fetching each entry's full record from /ledger/{n} and
    recomputing content_hash + head_hash from raw bytes, then checking prev_head_hash actually
    matches the previous entry's independently-recomputed head_hash (true continuity, not just
    isolated per-entry arithmetic)."""
    import hashlib
    chained = sorted([e for e in entries if e.get("chain")], key=lambda e: e.get("entry", 0))
    results = []
    prev_head = _genesis_head_hash()
    base = ledger_url.rsplit("/ledger", 1)[0]

    def fetch(n):
        # The API rate-limits; back off on 429 rather than report a link as unverifiable.
        delay = 1.0
        for attempt in range(6):
            try:
                with urllib.request.urlopen(f"{base}/ledger/{n}", timeout=20) as r:
                    return n, json.load(r), None
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 5:
                    return n, None, exc
                try:
                    delay = max(delay, float(exc.headers.get("Retry-After") or 0))
                except ValueError:
                    pass
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
            except Exception as exc:  # recorded per entry below
                return n, None, exc

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        docs = {n: (d, x) for n, d, x in pool.map(fetch, [e.get("entry") for e in chained])}
    for e in chained:
        n = e.get("entry")
        claimed = e.get("chain") or {}
        res = {"entry": n, "status": "unverified", "checks": {}}
        try:
            doc, exc = docs[n]
            if exc is not None:
                raise exc
            record = doc.get("record")
            recomputed_content_hash = hashlib.sha256(_canon_json(record)).hexdigest()
            recomputed_head_hash = hashlib.sha256(
                f"{recomputed_content_hash}|{prev_head}".encode("utf-8")).hexdigest()
            checks = {
                "content_hash_matches": recomputed_content_hash == claimed.get("content_hash"),
                "prev_head_matches_actual_predecessor": claimed.get("prev_head_hash") == prev_head,
                "head_hash_recomputes": recomputed_head_hash == claimed.get("head_hash"),
            }
            res["checks"] = checks
            res["status"] = "verified" if all(checks.values()) else "FAILED"
            res["recomputed_head_hash"] = recomputed_head_hash
            res["chain_head_relays"] = doc.get("chain_head_relays") or []
            # Advance the chain using our OWN recomputed head (not the server's claim) so a
            # tampered middle entry breaks continuity for everything after it, visibly.
            prev_head = recomputed_head_hash
        except Exception as exc:
            res["status"] = "fetch_failed"
            res["error"] = str(exc)
            # can't verify this link, but chain from what the server CLAIMED so a later, otherwise-
            # sound link doesn't get a spurious failure purely from this one being unreachable
            prev_head = claimed.get("head_hash", prev_head)
        results.append(res)
    return results


def _fetch_broadcast_head_claims(relays: list, expect_pubkey: str, timeout: float = 15.0) -> list:
    """Discover invinoveritas.ledger_chain_head.v1 events on `relays` WITHOUT knowing an event id in
    advance — a broad (kind, author) query, filtered client-side by the content payload's schema.
    This is the same discovery mechanism a third-party capture used to find our head broadcasts on
    2 of 6 relays with no cooperation from us (vlc-1#16) — recompute_ledger.py should use it too, not
    just the id-keyed per-verdict fetch above, or a dropped newest entry / consistent rewrite from
    genesis would pass silently (the chain-only check above can't see it: it only walks entries the
    /ledger index still lists). Returns verified claims (id_recomputed + issued_by + sig all hold),
    newest `entry` first."""
    req = {"kinds": [30078], "authors": [expect_pubkey], "#t": ["invinoveritas"], "limit": 500}
    seen: dict = {}
    for relay in relays:
        try:
            for ev in _ws_fetch_filter(relay, req, timeout):
                seen[str(ev.get("id", ""))] = ev
        except Exception:
            continue
    claims = []
    for eid, ev in seen.items():
        try:
            payload = json.loads(ev.get("content", "") or "{}")
        except Exception:
            continue
        if payload.get("schema") != "invinoveritas.ledger_chain_head.v1":
            continue
        try:
            id_ok = eid and nostr_event_id(ev) == eid
            pk_ok = str(ev.get("pubkey", "")).lower() == expect_pubkey
            sig_ok = schnorr_verify(bytes.fromhex(eid), bytes.fromhex(str(ev.get("pubkey", ""))),
                                     bytes.fromhex(str(ev.get("sig", ""))))
        except Exception:
            continue
        if not (id_ok and pk_ok and sig_ok):
            continue
        claims.append({"entry": payload.get("entry"), "head_hash": payload.get("head_hash"),
                        "content_hash": payload.get("content_hash"),
                        "prev_head_hash": payload.get("prev_head_hash"), "event_id": eid})
    claims.sort(key=lambda c: c.get("entry") if isinstance(c.get("entry"), int) else -1, reverse=True)
    return claims


def _check_broadcast_head(chain_results: list, broadcast_claims: list) -> dict:
    """Compare the newest independently-verified broadcast head claim against what THIS run's own
    chain walk reached. A dropped newest entry (the /ledger index truncated) or a consistent rewrite
    from genesis both still recompute a clean local chain — the only way to catch either is a signed
    head from outside the index agreeing with the local recompute, which is what this checks."""
    local_by_entry = {r["entry"]: r.get("recomputed_head_hash") for r in chain_results
                       if r.get("recomputed_head_hash")}
    if not broadcast_claims:
        return {"status": "no_claim_found", "note": "no verifiable broadcast head claim found on the "
                "queried relays -- this run could not rule out truncation or a consistent rewrite"}
    newest = broadcast_claims[0]
    claimed_entry = newest.get("entry")
    local_max = max(local_by_entry) if local_by_entry else None
    if local_max is None or (isinstance(claimed_entry, int) and claimed_entry > local_max):
        return {"status": "TRUNCATION_SUSPECTED", "claimed_entry": claimed_entry, "local_max_entry": local_max,
                "note": f"relays hold a signed head naming entry {claimed_entry}, but this run's "
                f"independently recomputed chain only reaches entry {local_max} -- a dropped newest "
                f"entry or a truncated index would look exactly like this"}
    if local_by_entry.get(claimed_entry) != newest.get("head_hash"):
        return {"status": "MISMATCH", "claimed_entry": claimed_entry,
                "note": f"relays hold a signed head for entry {claimed_entry} that does not match what "
                f"this run independently recomputed for that entry -- possible rewrite"}
    return {"status": "matches", "claimed_entry": claimed_entry,
            "note": f"newest broadcast head (entry {claimed_entry}) matches the independently "
            f"recomputed chain -- no truncation or rewrite detected"}


def _entry_event_id(entry: dict):
    return entry.get("event_id") or (entry.get("commitment_proof") or {}).get("event_id")


def _prefetch(entries: list[dict], chunk: int = 100) -> dict:
    """{relay: {event_id: raw event}}: every relay any entry names, queried once per chunk of ids,
    relays in parallel. The bytes are still the relay's; nothing here trusts our API."""
    from concurrent.futures import ThreadPoolExecutor
    by_relay: dict = {}
    for e in entries:
        eid = _entry_event_id(e)
        for relay in (e.get("commitment_proof") or {}).get("relays") or []:
            if eid:
                by_relay.setdefault(relay, []).append(eid)

    def one(relay):
        ids, got = by_relay[relay], {}
        for i in range(0, len(ids), chunk):
            try:
                got.update(_ws_fetch_ids(relay, ids[i:i + chunk]))
            except Exception:
                pass
        return relay, got

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(by_relay)))) as pool:
        return dict(pool.map(one, list(by_relay)))


# ── recompute one entry from relay-served bytes ───────────────────────────────────────────────────────
def _recompute_entry(entry: dict, expect_pubkey: str, cache: dict | None = None) -> dict:
    eid = entry.get("event_id") or (entry.get("commitment_proof") or {}).get("event_id")
    cp = entry.get("commitment_proof") or {}
    relays = cp.get("relays") or []
    res = {"entry": entry.get("entry"), "event_id": eid, "status": "unverified",
           "relay": None, "checks": {}}
    for relay in relays:
        if cache is not None:
            ev = (cache.get(relay) or {}).get(eid)
        else:
            try:
                ev = _ws_fetch_event(relay, eid)
            except Exception:
                ev = None
        if not ev:
            continue
        try:
            id_ok = (ev.get("id") == eid) and (nostr_event_id(ev) == eid)
            pk_ok = (str(ev.get("pubkey", "")).lower() == expect_pubkey)
            sig_ok = schnorr_verify(bytes.fromhex(eid),
                                    bytes.fromhex(str(ev.get("pubkey", ""))),
                                    bytes.fromhex(str(ev.get("sig", ""))))
        except Exception:
            continue
        res["relay"] = relay
        res["checks"] = {"id_recomputed": id_ok, "issued_by_invinoveritas": pk_ok, "signature_valid": sig_ok}
        res["status"] = "verified" if (id_ok and pk_ok and sig_ok) else "FAILED"
        return res
    # not retrievable from any relay — note whether a Bitcoin OTS anchor still attests the id
    ots = cp.get("ots_anchor") or {}
    res["status"] = "relay_unavailable"
    res["ots_anchor"] = ots.get("status")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Recompute the invinoveritas verdict ledger, trusting nothing.")
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--pubkey", default=PUBLISHED_PUBKEY)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    expect = args.pubkey.strip().lower()

    with urllib.request.urlopen(args.ledger, timeout=20) as r:
        ledger = json.load(r)
    entries = ledger.get("entries") or ledger.get("track_record") or []
    served_pubkey = (ledger.get("verifier_pubkey") or "").strip().lower()

    cache = _prefetch(entries)
    results = [_recompute_entry(e, expect, cache) for e in entries]
    verified = [r for r in results if r["status"] == "verified"]
    failed = [r for r in results if r["status"] == "FAILED"]
    relay_gone = [r for r in results if r["status"] == "relay_unavailable"]
    ots_covered = [r for r in relay_gone if r.get("ots_anchor") == "confirmed"]

    chain_results = _verify_chain(entries, args.ledger)
    chain_failed = [r for r in chain_results if r["status"] == "FAILED"]

    # Broadcast-head cross-check: a dropped newest entry or a consistent rewrite from genesis both
    # still recompute a clean chain above (that check only walks what the /ledger index lists) — this
    # is the only check in this script that can catch either, by agreeing (or not) with a signed head
    # discovered independently on public relays (vlc-1#16).
    head_relays = sorted({r for cr in chain_results for r in (cr.get("chain_head_relays") or [])})
    broadcast_claims = _fetch_broadcast_head_claims(head_relays, expect, timeout=20) if head_relays else []
    head_check = _check_broadcast_head(chain_results, broadcast_claims)
    head_check_failed = head_check["status"] in ("TRUNCATION_SUSPECTED", "MISMATCH")

    if args.json:
        print(json.dumps({
            "ledger": args.ledger, "expected_pubkey": expect, "served_pubkey": served_pubkey,
            "total": len(entries), "verified": len(verified), "failed": len(failed),
            "relay_unavailable": len(relay_gone), "ots_confirmed_of_unavailable": len(ots_covered),
            "results": results,
            "chain": {"total": len(chain_results),
                      "verified": len([r for r in chain_results if r["status"] == "verified"]),
                      "failed": len(chain_failed), "results": chain_results},
            "broadcast_head_check": head_check,
        }, indent=2))
        return 1 if (failed or chain_failed or head_check_failed) else 0

    print(f"Recomputing {len(entries)} verdicts from {args.ledger}")
    print(f"Expected verifier key: {expect}")
    if served_pubkey and served_pubkey != expect:
        print(f"  ⚠ served verifier_pubkey ({served_pubkey}) != pinned key — re-derive from "
              f"/.well-known/agent-handshake before trusting")
    print()
    for r in sorted(results, key=lambda x: x.get("entry") or 0):
        if r["status"] == "verified":
            mark = f"✓ verified (relay {r['relay']})"
        elif r["status"] == "FAILED":
            mark = f"✗ FAILED {r['checks']}"
        else:
            mark = f"· raw event off relays (NIP-33 replaced); OTS anchor: {r.get('ots_anchor')}"
        print(f"  entry {str(r.get('entry')):>3}  {str(r.get('event_id'))[:16]}…  {mark}")
    print()
    print(f"RECOMPUTED: {len(verified)}/{len(entries)} verdicts schnorr-verified from relay bytes "
          f"against {expect}.")
    if failed:
        print(f"  ✗ {len(failed)} FAILED verification — this should never happen; investigate.")
    if relay_gone:
        print(f"  · {len(relay_gone)} raw events rotated off relays (NIP-33); {len(ots_covered)} of those "
              f"carry a CONFIRMED Bitcoin-PoW anchor on the event id — recompute with `ots verify`.")

    if chain_results:
        print(f"\nHash-chain (entries #40+, one canonical history not N independent anchors):")
        for r in chain_results:
            if r["status"] == "verified":
                mark = "✓ verified — content_hash + head_hash recompute, links to actual predecessor"
            elif r["status"] == "FAILED":
                mark = f"✗ FAILED {r['checks']}"
            else:
                mark = f"· could not fetch entry ({r.get('error')})"
            print(f"  entry {str(r.get('entry')):>3}  {mark}")
        chain_verified = len(chain_results) - len(chain_failed) - len([r for r in chain_results if r["status"] == "fetch_failed"])
        print(f"  CHAIN: {chain_verified}/{len(chain_results)} links independently recomputed "
              f"(content_hash + head_hash from raw record bytes, prev_head_hash checked against the "
              f"actual predecessor's recomputed head, not the server's claim).")
        if chain_failed:
            print(f"  ✗ {len(chain_failed)} chain link(s) FAILED — either a tampered record or a broken "
                  f"history. This should never happen; investigate.")

    print(f"\nBroadcast head cross-check ({len(head_relays)} relay(s) queried, "
          f"{len(broadcast_claims)} verified claim(s) found): {head_check['status']}")
    print(f"  {head_check['note']}")
    if head_check_failed:
        print("  ✗ this is exactly what a dropped newest entry or a consistent rewrite from genesis "
              "would look like — investigate before trusting the chain result above.")

    print("\nYou trusted no one: the bytes came from public relays, the math ran here.")
    return 1 if (failed or chain_failed or head_check_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
