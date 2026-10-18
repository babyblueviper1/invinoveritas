#!/usr/bin/env python3
"""Decision-receipt slot log checker, standard library only, written from SPEC.md (not from the service).

    python3 slot_log_check.py 2026-10-11.jsonl                       # file -> merkle_root -> log_root
    python3 slot_log_check.py 2026-10-12.jsonl --prev 2026-10-11.jsonl  # and the chain to the day before
    python3 slot_log_check.py --inclusion slot.json                  # a GET /decision-receipt/slot/<slot> body (its "log")
    python3 slot_log_check.py 2026-10-11.jsonl --slot <hex>          # the slot is in this snapshot (prints its line)
    python3 slot_log_check.py --profile index.json                   # the profile this kit carries is the one the
                                                                     # GET /decision-receipt/slots/log body declares,
                                                                     # then every case in slot_log_vectors.json
    python3 slot_log_check.py --profile index.json --fetch           # same, but pull the profile doc + vector file
                                                                     # cold from url/vectors_url instead of trusting
                                                                     # the bundled copies -- a fetch failure prints
                                                                     # profile_unavailable, a hash disagreement
                                                                     # prints profile_mismatch, never conflated
    python3 slot_log_check.py --vectors slot_log_vectors.json        # the vector cases alone

Each prints the log_root; then check the Bitcoin anchor with the standard OpenTimestamps client:
    ots verify -d <log_root> <date>.ots
Exit 0 iff everything checked holds. For --profile: 1 = profile_mismatch or a vector disagrees, 2 = profile_unavailable
(the profile or vector file could not be read). Exit 2 is about the verifier's ability to check, not about the log.
"""
import hashlib
import json
import os
import re
import sys

SCHEMA = "invinoveritas.decision_receipt.slot_log.v1"
GENESIS = "0" * 64
EMPTY = hashlib.sha256(f"{SCHEMA}|empty".encode()).hexdigest()
HEX64 = re.compile(r"^[0-9a-f]{64}$")
LINE_KEYS = {"slot", "scope", "event_ids", "taken_at", "claim_sha256", "decider_sig", "conflicts"}


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def jcs(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pair(a, b):
    return sha(a + b)


def merkle_root(leaves):
    if not leaves:
        return EMPTY
    level = list(leaves)
    while len(level) > 1:
        level = [pair(level[i], level[i + 1] if i + 1 < len(level) else level[i]) for i in range(0, len(level), 2)]
    return level[0]


def fold(leaf, path):
    h = leaf
    for step in path:
        h = pair(h, step["hash"]) if step["side"] == "R" else pair(step["hash"], h)
    return h


class Bad(Exception):
    pass


def check_file(data):
    """(header, lines, log_root) for snapshot bytes, or raise Bad(reason)."""
    if not data.endswith(b"\n"):
        raise Bad("not newline-terminated")
    raw = data.decode("utf-8").split("\n")[:-1]
    if not raw:
        raise Bad("empty file")
    header = json.loads(raw[0])
    if jcs(header) != raw[0]:
        raise Bad("header is not canonical JSON")
    if header.get("schema") != SCHEMA:
        raise Bad("unknown schema")
    lines = []
    for r in raw[1:]:
        x = json.loads(r)
        if jcs(x) != r:
            raise Bad("a slot line is not canonical JSON")
        if set(x) != LINE_KEYS or not HEX64.match(x["slot"]) or x["scope"] not in ("account", "decider"):
            raise Bad("malformed slot line")
        lines.append(x)
    slots = [x["slot"] for x in lines]
    if slots != sorted(slots) or len(set(slots)) != len(slots):
        raise Bad("slot lines not strictly sorted by slot (a slot listed twice?)")
    if header.get("n_slots") != len(lines):
        raise Bad("n_slots does not match the lines")
    if merkle_root([sha(r) for r in raw[1:]]) != header.get("merkle_root"):
        raise Bad("merkle_root does not match the lines")
    if any(x["taken_at"] >= header["cutoff"] for x in lines):
        raise Bad("a slot taken after the cutoff")
    return header, lines, sha(raw[0])


def check_inclusion(log):
    """log = the "log" object of a slot GET response. Returns log_root or raises Bad."""
    leaf = sha(jcs(log["line"]))
    if leaf != log["leaf"]:
        raise Bad("leaf is not sha256(JCS(line))")
    if fold(leaf, log["merkle_path"]) != log["header"]["merkle_root"]:
        raise Bad("merkle_path does not reach header.merkle_root")
    root = sha(jcs(log["header"]))
    if root != log["log_root"]:
        raise Bad("log_root is not sha256(JCS(header))")
    return root


def check_chain(header, lines, prev_data):
    """Raise Bad unless this snapshot chains to the previous day's snapshot bytes."""
    ph, pl, proot = check_file(prev_data)
    if header["prev_root"] != proot:
        raise Bad("prev_root is not the previous snapshot's log_root (history rewritten?)")
    if ph["date"] >= header["date"]:
        raise Bad("previous snapshot is not an earlier day")
    prev_slots = {x["slot"]: x for x in pl}
    gone = [s for s in prev_slots if s not in {x["slot"] for x in lines}]
    if gone:
        raise Bad(f"{len(gone)} slot(s) of the previous day missing (first: {gone[0]})")
    for x in lines:
        p = prev_slots.get(x["slot"])
        if p and ({k: p[k] for k in LINE_KEYS - {"conflicts"}} != {k: x[k] for k in LINE_KEYS - {"conflicts"}}
                  or x["conflicts"][:len(p["conflicts"])] != p["conflicts"]):
            raise Bad(f"slot {x['slot']} changed since the previous day (only new conflicts may be appended)")


def run_vectors(doc):
    """Check every case; return the number that disagree with their expected result."""
    bad = 0
    for v in doc["vectors"]:
        try:
            header, lines, root = check_file(v["file"].encode("utf-8"))
            if v.get("prev") is not None:
                check_chain(header, lines, v["prev"].encode("utf-8"))
            got, detail = "ok", root
        except (Bad, ValueError, KeyError, TypeError) as e:
            got, detail = "reject", str(e)
        agree = got == v["expect"] and (got != "ok" or detail == v.get("log_root"))
        bad += not agree
        print(f"  {'agree' if agree else 'DISAGREE'} {v['id']}: {got}" + ("" if got == "ok" else f" ({detail})"))
    print(f"{len(doc['vectors']) - bad}/{len(doc['vectors'])} vectors agree")
    return bad


def check_profile(index, here, fetch=False):
    """Compare the profile + vector files with index["profile"]; then run the vectors.

    fetch=False (default): read SLOT_LOG_PROFILE.md / slot_log_vectors.json bundled beside this
    checker. fetch=True: ignore the local files and pull prof["url"] / prof["vectors_url"] instead --
    url/vectors_url are retrieval hints only, so a fetch failure is profile_unavailable (the
    checker's problem) and a hash disagreement is profile_mismatch (the hint's problem), never
    conflated with recompute_mismatch (an inputs disagreement, from run_vectors below).
    """
    prof = index.get("profile") or {}
    try:
        if fetch:
            import urllib.request
            pbytes = urllib.request.urlopen(prof["url"], timeout=15).read()
            vbytes = urllib.request.urlopen(prof["vectors_url"], timeout=15).read()
        else:
            pbytes = open(os.path.join(here, "SLOT_LOG_PROFILE.md"), "rb").read()
            vbytes = open(os.path.join(here, "slot_log_vectors.json"), "rb").read()
    except (OSError, KeyError) as e:
        print(f"profile_unavailable: {e}")
        return 2
    got = {"sha256": hashlib.sha256(pbytes).hexdigest(), "vectors_sha256": hashlib.sha256(vbytes).hexdigest()}
    if prof.get("id") != SCHEMA:
        print(f"profile_mismatch: index declares profile id {prof.get('id')!r}, this checker implements {SCHEMA}")
        return 1
    for k, val in got.items():
        if prof.get(k) != val:
            src = "the fetched bytes hash" if fetch else "the local file hashes"
            print(f"profile_mismatch: {k} declared {prof.get(k)} but {src} to {val}")
            return 1
    print(f"profile ok: {SCHEMA} sha256 {got['sha256']} vectors_sha256 {got['vectors_sha256']}")
    return 1 if run_vectors(json.loads(vbytes)) else 0


def main(argv):
    try:
        if "--profile" in argv:
            index = json.load(open(argv[argv.index("--profile") + 1]))
            return check_profile(index, os.path.dirname(os.path.abspath(__file__)), fetch="--fetch" in argv)
        if "--vectors" in argv:
            return 1 if run_vectors(json.load(open(argv[argv.index("--vectors") + 1]))) else 0
        if "--inclusion" in argv:
            body = json.load(open(argv[argv.index("--inclusion") + 1]))
            log = body.get("log", body)
            root = check_inclusion(log)
            print(f"inclusion ok: slot {log['line']['slot']} in {log['header']['date']} log_root {root}")
            print(f"next: ots verify -d {root} {log['header']['date']}.ots")
            return 0
        path = argv[1]
        header, lines, root = check_file(open(path, "rb").read())
        if "--prev" in argv:
            check_chain(header, lines, open(argv[argv.index("--prev") + 1], "rb").read())
        elif header["prev_root"] == GENESIS:
            print("first snapshot (prev_root = genesis)")
        if "--slot" in argv:
            s = argv[argv.index("--slot") + 1]
            hit = [x for x in lines if x["slot"] == s]
            if not hit:
                raise Bad(f"slot {s} is not in this snapshot")
            print(jcs(hit[0]))
        print(f"ok: {header['date']} n_slots {header['n_slots']} log_root {root}")
        print(f"next: ots verify -d {root} {header['date']}.ots")
        return 0
    except Bad as e:
        print(f"REJECT: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
