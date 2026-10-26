#!/usr/bin/env python3
"""deils-anchor-v1 checker (PROFILE.md), standard library only.

  python3 check.py --vectors vectors.json
  python3 check.py D1.jsonl [D2.jsonl ...] [--records records.jsonl --issuer <x-only pubkey hex>]
                   [--ots D=path.ots ...] [--headers headers.json] [--claim-confirmed D ...]

Days are given oldest first; the first file's prev_root / prev_last_position are taken as given (supply the chain from the first day
to check those too). headers.json is {height: 80-byte header hex}, from your own node or explorers you choose. Prints one JSON result
per day: {date, status (anchored|not_anchored|failed), state (published|pending|confirmed), height, codes}."""
import hashlib, json, os, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bip340, ots_verify  # noqa: E402

SCHEMA = "deils-anchor-v1"
HEADER_KEYS = {"schema", "date", "start", "end", "count", "first_position", "last_position", "prev_last_position", "prev_root",
               "merkle_root"}
LINE_KEYS = {"ledger_position", "proof_id", "commitment_hash", "profile", "record_event_id", "created_at"}
ZERO = "0" * 64
NOT_CONFIRMED = {"ots_bitcoin_header_missing"}   # reasons a stamp is not (yet) confirmation; every other ots code fails the day


def _ok_value(v):
    if v is None or isinstance(v, str) and v.isascii():
        return True
    return type(v) is int and 0 <= v < 2 ** 53


def jcs(o) -> bytes:
    """RFC 8785 for this profile's value types (objects of ASCII strings, non-negative safe integers, null)."""
    if not isinstance(o, dict) or not all(isinstance(k, str) and k.isascii() and _ok_value(v) for k, v in o.items()):
        raise ValueError("value outside the profile's types")
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _h(b) -> bytes:
    return hashlib.sha256(b).digest()


def mth(leaves):
    """RFC 9162 Merkle Tree Hash over leaf inputs (bytes each)."""
    if not leaves:
        return _h(b"")
    if len(leaves) == 1:
        return _h(b"\x00" + leaves[0])
    k = 1
    while k * 2 < len(leaves):
        k *= 2
    return _h(b"\x01" + mth(leaves[:k]) + mth(leaves[k:]))


def log_root(header: dict) -> str:
    return _h(jcs(header)).hex()


def day_edges(date: str):
    s = int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    return s, s + 86400


def event_id(ev) -> str:
    return _h(json.dumps([0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]], separators=(",", ":"),
                         ensure_ascii=False).encode()).hex()


def parse_day(text: str):
    """-> (header, records, codes). Structural rules of section 4 that need only this file."""
    codes = []
    if not text.endswith("\n"):
        codes.append("line_not_canonical")
    raw = text.split("\n")
    if raw and raw[-1] == "":
        raw = raw[:-1]
    objs = []
    for ln in raw:
        try:
            o = json.loads(ln)
            if jcs(o).decode() != ln:
                codes.append("line_not_canonical")
            objs.append(o)
        except ValueError:
            codes.append("line_not_canonical"); objs.append(None)
    if not objs or not isinstance(objs[0], dict) or set(objs[0]) != HEADER_KEYS or objs[0].get("schema") != SCHEMA:
        return None, [], sorted(set(codes + ["bad_fields"]))
    hdr, recs = objs[0], objs[1:]
    if any(not isinstance(r, dict) or set(r) != LINE_KEYS for r in recs):
        codes.append("bad_fields")
        recs = [r for r in recs if isinstance(r, dict) and set(r) == LINE_KEYS]
    return hdr, recs, codes


def check_day(text: str, prev_hdr=None):
    hdr, recs, codes = parse_day(text)
    if hdr is None:
        return None, codes
    if "bad_fields" in codes:
        return hdr, sorted(set(codes)), []   # the day's lines are not this profile's: no further rule is meaningful
    try:
        s, e = day_edges(hdr["date"])
    except (ValueError, TypeError):
        return hdr, sorted(set(codes + ["bad_day_edges"]))
    if hdr["start"] != s or hdr["end"] != e:
        codes.append("bad_day_edges")
    if hdr["count"] != len(recs):
        codes.append("count_mismatch")
    lines = [jcs(r) for r in recs]
    if mth(lines).hex() != hdr["merkle_root"]:
        codes.append("merkle_root_mismatch")
    pos = [r["ledger_position"] for r in recs]
    if not recs:
        if hdr["first_position"] is not None or hdr["last_position"] is not None:
            codes.append("empty_day_positions")
    else:
        if pos[0] != hdr["prev_last_position"] + 1 or hdr["first_position"] != pos[0]:
            codes.append("position_start")
        if any(b != a + 1 for a, b in zip(pos, pos[1:])):
            codes.append("position_gap")
        if hdr["last_position"] != pos[-1]:
            codes.append("position_end")
    for r in recs:
        if r["created_at"] >= e:
            codes.append("created_at_after_day")
        elif r["created_at"] < s:
            codes.append("late_record")
    if prev_hdr is not None:
        try:
            ps, _ = day_edges(prev_hdr["date"])
            if s - ps != 86400:
                codes.append("date_gap")
        except (ValueError, TypeError, KeyError):
            codes.append("date_gap")
        if hdr["prev_root"] != log_root(prev_hdr):
            codes.append("prev_root_mismatch")
        carried = prev_hdr["last_position"] if prev_hdr["count"] else prev_hdr["prev_last_position"]
        if hdr["prev_last_position"] != carried:
            codes.append("prev_last_mismatch")
    return hdr, sorted(set(codes)), recs


def check_records(recs, records, issuer):
    codes = []
    for r in recs:
        ev = records.get(r["record_event_id"])
        if ev is None:
            codes.append("record_missing"); continue
        if event_id(ev) != ev.get("id") or ev.get("id") != r["record_event_id"]:
            codes.append("record_id_mismatch"); continue
        if ev.get("pubkey") != issuer or not bip340.verify(bytes.fromhex(ev["pubkey"]), bytes.fromhex(ev["id"]), bytes.fromhex(ev["sig"])):
            codes.append("record_signature_invalid"); continue
        try:
            c = json.loads(ev["content"])
        except ValueError:
            codes.append("record_mismatch"); continue
        if any(c.get(k) != r[k] for k in ("proof_id", "ledger_position", "commitment_hash", "profile")):
            codes.append("record_mismatch")
        if ev["created_at"] != r["created_at"]:
            codes.append("record_created_at_mismatch")
    return codes


def check_chain(days, records=None, issuer=None, ots=None, headers=None, claims=()):
    """days: list of file texts, oldest first. Returns one result dict per day."""
    out, prev, chain_ok = [], None, True
    for text in days:
        res = check_day(text, prev)
        hdr, codes = res[0], list(res[1])
        recs = res[2] if len(res) > 2 else []
        if hdr is not None and records is not None:
            codes += check_records(recs, records, issuer)
        date = hdr.get("date") if hdr else None
        state, height = "published", None
        if hdr is not None and ots and date in ots:
            try:
                o = ots_verify.check(ots[date], log_root(hdr), headers or {})
                state, height = o["state"], o["height"]
                if state == "none":
                    state = "published"
                codes += [c for c in o["codes"] if c not in NOT_CONFIRMED]
            except ots_verify.OtsError as e:
                codes.append("ots_digest_mismatch" if "proof is for" in str(e) else "ots_malformed")
        if date in claims and state != "confirmed":
            codes.append("pending_claimed_confirmed")
        codes = sorted(set(codes))
        if codes:
            status = "failed"
        elif state == "confirmed" and chain_ok:
            status = "anchored"
        else:
            status = "not_anchored"
        chain_ok = chain_ok and not codes
        out.append({"date": date, "status": status, "state": state, "height": height, "codes": codes})
        prev = hdr if hdr is not None else prev
    return out


def run_vectors(path):
    v = json.load(open(path))
    ok = bad = 0
    for t in v["vectors"]:
        if t.get("ots_only"):
            w = t["expect"]
            try:
                g = ots_verify.check(bytes.fromhex(t["ots_hex"]), t["digest"], {int(k): x for k, x in t["headers"].items()})
                same = "error" not in w and (g["state"], g["height"], sorted(g["codes"])) == (w["state"], w["height"], sorted(w["codes"]))
            except ots_verify.OtsError as e:
                g = {"error": "ots_digest_mismatch" if "proof is for" in str(e) else "ots_malformed"}
                same = g == w
            ok += same; bad += not same
            print(("PASS " if same else "FAIL ") + t["name"] + ("" if same else f"\n  want {w}\n  got  {g}"))
            continue
        recs = None
        if t.get("records") is not None:
            recs = {ev["id"]: ev for ev in t["records"]}
        ots = {d: bytes.fromhex(h) for d, h in (t.get("ots") or {}).items()}
        got = check_chain(t["days"], recs, v.get("issuer"), ots, {int(k): x for k, x in (t.get("headers") or {}).items()},
                          set(t.get("claims") or ()))
        want = t["expect"]
        same = [(g["status"], g["state"], g["codes"]) for g in got] == [(w["status"], w["state"], w["codes"]) for w in want]
        ok += same; bad += not same
        print(("PASS " if same else "FAIL ") + t["name"] + ("" if same else f"\n  want {want}\n  got  {got}"))
    print(f"{ok}/{ok + bad} vectors pass")
    return 0 if not bad else 1


def main(argv):
    if argv[:1] == ["--vectors"]:
        return run_vectors(argv[1])
    days, ots, claims, records, issuer, headers = [], {}, set(), None, None, {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--records":
            records = {ev["id"]: ev for ev in map(json.loads, open(argv[i + 1]))}; i += 2
        elif a == "--issuer":
            issuer = argv[i + 1]; i += 2
        elif a == "--ots":
            d, p = argv[i + 1].split("=", 1); ots[d] = open(p, "rb").read(); i += 2
        elif a == "--headers":
            headers = {int(k): x for k, x in json.load(open(argv[i + 1])).items()}; i += 2
        elif a == "--claim-confirmed":
            claims.add(argv[i + 1]); i += 2
        else:
            days.append(open(a, encoding="utf-8", newline="").read()); i += 1
    res = check_chain(days, records, issuer, ots, headers, claims)
    for r in res:
        print(json.dumps(r))
    return 1 if any(r["status"] == "failed" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
