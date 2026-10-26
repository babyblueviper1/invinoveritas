#!/usr/bin/env python3
"""Builds vectors.json for deils-anchor-v1 (PROFILE.md). Deterministic: a fixed TEST key (sha256 of a public string, never a real
key) signs synthetic DEILS commitment records; the OTS vectors use real proofs and real Bitcoin headers (ots/ and headers.json).

  python3 gen_vectors.py && python3 check.py --vectors vectors.json"""
import copy, hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bip340  # noqa: E402
from check import ZERO, day_edges, event_id, jcs, log_root, mth  # noqa: E402

SK = hashlib.sha256(b"deils-anchor-v1 test vectors -- not a real key").digest()
PUB = bip340.pubkey(SK).hex()


def record(pos, created_at, profile="deils-reveal-v1"):
    commitment = "sha256:" + hashlib.sha256(f"test content {pos}".encode()).hexdigest()
    pid = f"proof_test{pos:04d}"
    content = jcs({"type": "deils-commitment-record", "proof_id": pid, "ledger_position": pos, "commitment_hash": commitment,
                   "profile": profile}).decode()
    ev = {"pubkey": PUB, "created_at": created_at, "kind": 30078,
          "tags": [["d", f"invinoveritas-commitment-{pid}"], ["t", "deils-commitment-record"], ["profile", profile]],
          "content": content}
    ev["id"] = event_id(ev)
    ev["sig"] = bip340.sign(SK, bytes.fromhex(ev["id"]), bytes(32)).hex()
    line = {"ledger_position": pos, "proof_id": pid, "commitment_hash": commitment, "profile": profile,
            "record_event_id": ev["id"], "created_at": created_at}
    return line, ev


def day(date, lines, prev_hdr):
    s, e = day_edges(date)
    if prev_hdr is None:
        prev_root, prev_last = ZERO, 0
    else:
        prev_root = log_root(prev_hdr)
        prev_last = prev_hdr["last_position"] if prev_hdr["count"] else prev_hdr["prev_last_position"]
    hdr = {"schema": "deils-anchor-v1", "date": date, "start": s, "end": e, "count": len(lines),
           "first_position": lines[0]["ledger_position"] if lines else None,
           "last_position": lines[-1]["ledger_position"] if lines else None,
           "prev_last_position": prev_last, "prev_root": prev_root, "merkle_root": mth([jcs(l) for l in lines]).hex()}
    return hdr, lines


def text(hdr, lines):
    return "".join(jcs(o).decode() + "\n" for o in [hdr] + lines)


def chain(spec):
    """spec: [(date, [(pos, created_at), ...]), ...] -> (texts, headers, events)"""
    texts, hdrs, evs, prev = [], [], [], None
    for date, recs in spec:
        ls = []
        for pos, ca in recs:
            l, ev = record(pos, ca); ls.append(l); evs.append(ev)
        hdr, ls = day(date, ls, prev)
        texts.append(text(hdr, ls)); hdrs.append(hdr); prev = hdr
    return texts, hdrs, evs


S1, _ = day_edges("2026-10-20"); S2, _ = day_edges("2026-10-21"); S3, E3 = day_edges("2026-10-22")
BASE = [("2026-10-20", [(1, S1), (2, S1 + 3600), (3, S1 + 86399)]), ("2026-10-21", []), ("2026-10-22", [(4, S3 + 10), (5, S3 + 7200)])]


def ok(n):
    return [{"status": "not_anchored", "state": "published", "codes": []}] * n


def fail(codes, state="published"):
    return {"status": "failed", "state": state, "codes": sorted(codes)}


def main():
    V = []
    texts, hdrs, evs = chain(BASE)
    _d3 = os.path.join(HERE, "ots", "base_day3.root")
    open(_d3, "w").write(log_root(hdrs[2]) + "\n")

    def add(name, days, expect, records=True, **kw):
        V.append({"name": name, "days": days, "records": evs if records is True else records, "expect": expect, **kw})

    add("ok: 3 days, empty middle day carries position 3, edges 00:00:00 in and 23:59:59 in", texts, ok(3))
    add("ok: same chain without the signed records (created_at is only asserted)", texts, ok(3), records=None)
    t7, _, e7 = chain([("2026-10-20", [(p, S1 + p) for p in range(1, 8)])])
    add("ok: 7 records in one day (RFC 9162 split at the largest power of two below n: 4 + 3)", t7, ok(1), records=e7)
    t5, _, e5 = chain([("2026-10-20", [(p, S1 + p) for p in range(1, 6)])])
    add("ok: 5 records in one day (split 4 + 1, not 3 + 2)", t5, ok(1), records=e5)

    def mutate_day(i, fn, rehash=True):
        """Edit day i (header dict, line list), recompute its merkle_root/log_root if rehash, re-chain later days."""
        hs = [json.loads(t.split("\n")[0]) for t in texts]
        ls = [[json.loads(x) for x in t.split("\n")[1:] if x] for t in texts]
        fn(hs[i], ls[i])
        if rehash:
            hs[i]["merkle_root"] = mth([jcs(l) for l in ls[i]]).hex()
        for j in range(i + 1, len(hs)):
            hs[j]["prev_root"] = log_root(hs[j - 1])
        return [text(h, l) for h, l in zip(hs, ls)]

    t = list(texts); t[0] = t[0].replace('{"commitment_hash"', '{ "commitment_hash"', 1)
    add("line not JCS (a space)", t, [fail(["line_not_canonical"])] + ok(2))
    add("extra key in a record line", mutate_day(0, lambda h, l: l[0].__setitem__("extra", "x")),
        [fail(["bad_fields"])] + ok(2))
    add("bad day edges (end = start + 86399)", mutate_day(0, lambda h, l: h.__setitem__("end", h["start"] + 86399)),
        [fail(["bad_day_edges"])] + ok(2))
    add("count does not match the lines", mutate_day(0, lambda h, l: h.__setitem__("count", 2)), [fail(["count_mismatch"])] + ok(2))
    add("merkle_root edited", mutate_day(0, lambda h, l: h.__setitem__("merkle_root", "00" * 32), rehash=False),
        [fail(["merkle_root_mismatch"])] + ok(2))
    # an odd node must be carried up, never paired with itself: the duplicated-last-leaf root of 3 leaves is wrong
    def dup_root(h, l):
        a, b, c = [hashlib.sha256(b"\x00" + jcs(x)).digest() for x in l]
        n = lambda x, y: hashlib.sha256(b"\x01" + x + y).digest()
        h["merkle_root"] = n(n(a, b), n(c, c)).hex()
    add("merkle root built by pairing the odd node with itself", mutate_day(0, dup_root, rehash=False),
        [fail(["merkle_root_mismatch"])] + ok(2))
    add("position gap inside a day (1, 2, 4)", chain([("2026-10-20", [(1, S1), (2, S1 + 1), (4, S1 + 2)])])[0],
        [fail(["position_gap"])], records=None)
    add("first position is not prev_last_position + 1 (day 3 starts at 5)",
        mutate_day(2, lambda h, l: (l[0].__setitem__("ledger_position", 5), l[1].__setitem__("ledger_position", 6),
                                    h.__setitem__("first_position", 5), h.__setitem__("last_position", 6))),
        ok(2) + [fail(["position_start", "record_mismatch"])])
    add("last_position does not match the last line", mutate_day(0, lambda h, l: h.__setitem__("last_position", 4)),
        [fail(["position_end"]), fail(["prev_last_mismatch"]), ok(1)[0]])
    add("empty day with non-null positions", mutate_day(1, lambda h, l: (h.__setitem__("first_position", 3), h.__setitem__("last_position", 3))),
        [ok(1)[0], fail(["empty_day_positions"]), ok(1)[0]])
    add("gap hidden behind an empty day (day 2 carries 5, day 3 starts at 6; positions 4-5 never published)",
        [text(h, l) for h, l in zip(*_hidden_gap(texts))],
        [ok(1)[0], fail(["prev_last_mismatch"]), fail(["record_mismatch"])])
    add("record dated after its day (created_at = end, the next day's 00:00:00)",
        mutate_day(2, lambda h, l: l[1].__setitem__("created_at", E3)), ok(2) + [fail(["created_at_after_day", "record_created_at_mismatch"])])
    late_t, _, late_e = chain([BASE[0], BASE[1], ("2026-10-22", [(4, S2 + 100), (5, S3 + 7200)])])
    add("late record: created on day 2 (signed), first published in day 3's log", late_t, ok(2) + [fail(["late_record"])], records=late_e)
    add("missing day (day 2 not published)", [texts[0], texts[2]], [ok(1)[0], fail(["date_gap", "prev_root_mismatch"])])
    add("prev_root does not chain", mutate_day(1, lambda h, l: h.__setitem__("prev_root", "11" * 32)),
        [ok(1)[0], fail(["prev_root_mismatch"]), ok(1)[0]])
    # signed-record checks
    e = copy.deepcopy(evs); e[1]["sig"] = e[1]["sig"][:-2] + ("00" if e[1]["sig"][-2:] != "00" else "01")
    add("record signature invalid", texts, [fail(["record_signature_invalid"])] + ok(2), records=e)
    e = copy.deepcopy(evs); e[0]["content"] = e[0]["content"].replace("proof_test0001", "proof_test9999"); e[0]["id"] = event_id(e[0])
    e[0]["sig"] = bip340.sign(SK, bytes.fromhex(e[0]["id"]), bytes(32)).hex()
    add("record id in the log points to an event that does not exist", texts, [fail(["record_missing"])] + ok(2), records=e)
    e = copy.deepcopy(evs); e[2]["created_at"] += 1
    add("record id does not recompute (event edited after signing)", texts, [fail(["record_id_mismatch"])] + ok(2), records=e)
    add("log line says a different created_at than the signed record", mutate_day(0, lambda h, l: l[1].__setitem__("created_at", S1 + 3601)),
        [fail(["record_created_at_mismatch"])] + ok(2))
    add("log line says a different commitment_hash than the signed record",
        mutate_day(0, lambda h, l: l[0].__setitem__("commitment_hash", "sha256:" + "ab" * 32)), [fail(["record_mismatch"])] + ok(2))

    # OTS layer on REAL data: the 2026-10-09 decision-receipt slot-log stamp (a different log, same OTS mechanics) and real Bitcoin
    # headers. These test the proof logic only; the end-to-end vectors below stamp the BASE chain's own day 3.
    O = json.load(open(os.path.join(HERE, "ots", "real.json")))
    V.append({"name": "ots real confirmed proof + its block header (two explorers agree) -> confirmed", "ots_only": True,
              "digest": O["digest"], "ots_hex": O["confirmed_hex"], "headers": O["headers"],
              "expect": {"state": "confirmed", "height": O["height"], "codes": []}})
    V.append({"name": "ots same proof, no header supplied -> pending (never confirmed on the calendar's word)", "ots_only": True,
              "digest": O["digest"], "ots_hex": O["confirmed_hex"], "headers": {},
              "expect": {"state": "pending", "height": None, "codes": ["ots_bitcoin_header_missing"]}})
    V.append({"name": "ots pending-only proof -> pending", "ots_only": True, "digest": O["digest"], "ots_hex": O["pending_hex"],
              "headers": O["headers"], "expect": {"state": "pending", "height": None, "codes": []}})
    V.append({"name": "ots header of a different block at that height -> mismatch", "ots_only": True, "digest": O["digest"],
              "ots_hex": O["confirmed_hex"], "headers": O["wrong_headers"],
              "expect": {"state": "pending", "height": None, "codes": ["ots_bitcoin_header_mismatch"]}})
    V.append({"name": "ots header with invalid proof of work -> fails", "ots_only": True, "digest": O["digest"],
              "ots_hex": O["confirmed_hex"], "headers": {str(O["height"]): O["headers"][str(O["height"])][:-8] + "00000000"},
              "expect": {"state": "pending", "height": None, "codes": ["ots_bitcoin_header_missing", "ots_header_invalid_pow"]}})
    V.append({"name": "ots proof for a different digest", "ots_only": True, "digest": "00" * 32, "ots_hex": O["confirmed_hex"],
              "headers": O["headers"], "expect": {"error": "ots_digest_mismatch"}})
    # end to end on the BASE chain: the pending proof for day 3, and a pending proof claimed confirmed
    _e = os.path.join(HERE, "ots", "base_day3.json")
    E = json.load(open(_e)) if os.path.exists(_e) else {}
    if E.get("log_root") == log_root(json.loads(texts[2].split("\n")[0])):
        add("end to end: day 3 stamped, calendar only -> not anchored (pending)", texts,
            ok(2) + [{"status": "not_anchored", "state": "pending", "codes": []}], ots={"2026-10-22": E["pending_hex"]})
        add("end to end: day 3 pending but claimed confirmed -> failed", texts,
            ok(2) + [fail(["pending_claimed_confirmed"], "pending")], ots={"2026-10-22": E["pending_hex"]}, claims=["2026-10-22"])
        if E.get("confirmed_hex"):
            add("end to end: day 3 confirmed + its block header -> anchored", texts,
                ok(2) + [{"status": "anchored", "state": "confirmed", "codes": []}], ots={"2026-10-22": E["confirmed_hex"]},
                headers=E["headers"])
    out = {"profile": "deils-anchor-v1", "issuer": PUB, "note": "TEST key, derived from a public string: never trust it for anything",
           "vectors": V}
    json.dump(out, open(os.path.join(HERE, "vectors.json"), "w"), indent=1)
    print(len(V), "vectors;", "day 3 log_root", log_root(json.loads(texts[2].split("\n")[0])))


def _hidden_gap(texts):
    hs = [json.loads(t.split("\n")[0]) for t in texts]
    ls = [[json.loads(x) for x in t.split("\n")[1:] if x] for t in texts]
    hs[1]["prev_last_position"] = 5                      # day 2 (empty) claims day 1 ended at 5
    for l, p in zip(ls[2], (6, 7)):
        l["ledger_position"] = p
    hs[2].update({"first_position": 6, "last_position": 7, "prev_last_position": 5, "merkle_root": mth([jcs(l) for l in ls[2]]).hex()})
    hs[1]["prev_root"] = log_root(hs[0]); hs[2]["prev_root"] = log_root(hs[1])
    return hs, ls


if __name__ == "__main__":
    main()
