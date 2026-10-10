#!/usr/bin/env python3
"""Decision-receipt slot log checker, standard library only, written from SPEC.md (not from the service).

    python3 slot_log_check.py 2026-10-11.jsonl                       # file -> merkle_root -> log_root
    python3 slot_log_check.py 2026-10-12.jsonl --prev 2026-10-11.jsonl  # and the chain to the day before
    python3 slot_log_check.py --inclusion slot.json                  # a GET /decision-receipt/slot/<slot> body (its "log")
    python3 slot_log_check.py 2026-10-11.jsonl --slot <hex>          # the slot is in this snapshot (prints its line)

Each prints the log_root; then check the Bitcoin anchor with the standard OpenTimestamps client:
    ots verify -d <log_root> <date>.ots
Exit 0 iff everything checked holds.
"""
import hashlib
import json
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


def main(argv):
    try:
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
            ph, _pl, proot = check_file(open(argv[argv.index("--prev") + 1], "rb").read())
            if header["prev_root"] != proot:
                raise Bad("prev_root is not the previous snapshot's log_root (history rewritten?)")
            if ph["date"] >= header["date"]:
                raise Bad("previous snapshot is not an earlier day")
            prev_slots = {x["slot"]: x for x in _pl}
            gone = [s for s in prev_slots if s not in {x["slot"] for x in lines}]
            if gone:
                raise Bad(f"{len(gone)} slot(s) of the previous day missing (first: {gone[0]})")
            for x in lines:
                p = prev_slots.get(x["slot"])
                if p and ({k: p[k] for k in LINE_KEYS - {"conflicts"}} != {k: x[k] for k in LINE_KEYS - {"conflicts"}}
                          or x["conflicts"][:len(p["conflicts"])] != p["conflicts"]):
                    raise Bad(f"slot {x['slot']} changed since the previous day (only new conflicts may be appended)")
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
