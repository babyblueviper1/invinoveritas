#!/usr/bin/env python3
"""deils-anchor-v1 checker (PROFILE.md), standard library only.

  python3 check.py --vectors vectors.json
  python3 check.py D1.jsonl [D2.jsonl ...] [--records records.jsonl --issuer <x-only pubkey hex>]
                   [--ots D=path.ots ...] [--headers headers.json] [--pins pins.json] [--claim-confirmed D ...]

Days are given oldest first; the first file's prev_root / prev_last_position are taken as given (supply the chain from the first day
to check those too). headers.json is {height: 80-byte header hex}, from your own node or explorers you choose. Prints one JSON result
per day: {date, status (anchored|not_anchored|failed), state (published|pending|confirmed), height, codes}."""
import hashlib, json, os, re, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bip340, ots_verify  # noqa: E402

SCHEMA = "deils-anchor-v1"
HEADER_KEYS = {"schema", "date", "start", "end", "count", "first_position", "last_position", "prev_last_position", "prev_root",
               "merkle_root"}
LINE_KEYS = {"ledger_position", "proof_id", "commitment_hash", "profile", "record_event_id", "created_at"}
ZERO = "0" * 64
NOT_CONFIRMED = ots_verify.NOT_CONFIRMING   # reasons a stamp is not (yet) confirmation; every other ots code fails the day
# review 4 (Echo, TG 5880): `$` also matched before a trailing "\n", so an id with "\n" appended passed -- two spellings of one id.
# fullmatch + re.ASCII: the whole string, and \d is 0-9 only.
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)
GRACE_S = 86400   # a late record more than one day before its log's day is reported separately (section 4)


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


_NIP01_ESC = {"\n": "\\n", "\"": "\\\"", "\\": "\\\\", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def _nip01(v) -> str:
    """NIP-01 serialization: in strings escape only \\n \\" \\\\ \\r \\t \\b \\f; every other character verbatim (UTF-8)."""
    if isinstance(v, str):
        return '"' + "".join(_NIP01_ESC.get(c, c) for c in v) + '"'
    if isinstance(v, list):
        return "[" + ",".join(_nip01(x) for x in v) + "]"
    if type(v) is int:
        return str(v)
    raise ValueError("value outside NIP-01 event types")


def event_id(ev) -> str:
    return _h(_nip01([0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]]).encode("utf-8")).hex()


def _types_ok(o, spec) -> bool:
    for k, kind in spec.items():
        v = o.get(k)
        if kind == "int" and type(v) is not int: return False
        if kind == "int?" and v is not None and type(v) is not int: return False
        if kind == "str" and not isinstance(v, str): return False
        if kind == "hex64" and not (isinstance(v, str) and HEX64.fullmatch(v)): return False
        if kind == "date" and not (isinstance(v, str) and DATE_RE.fullmatch(v)): return False
    return True


HEADER_TYPES = {"schema": "str", "date": "date", "start": "int", "end": "int", "count": "int", "first_position": "int?",
                "last_position": "int?", "prev_last_position": "int", "prev_root": "hex64", "merkle_root": "hex64"}
LINE_TYPES = {"ledger_position": "int", "proof_id": "str", "commitment_hash": "str", "profile": "str", "record_event_id": "hex64",
              "created_at": "int"}


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
    if (not objs or not isinstance(objs[0], dict) or set(objs[0]) != HEADER_KEYS or objs[0].get("schema") != SCHEMA
            or not _types_ok(objs[0], HEADER_TYPES)):
        return None, [], sorted(set(codes + ["bad_fields"]))
    hdr, recs = objs[0], objs[1:]
    if any(not isinstance(r, dict) or set(r) != LINE_KEYS or not _types_ok(r, LINE_TYPES) for r in recs):
        codes.append("bad_fields")
        recs = [r for r in recs if isinstance(r, dict) and set(r) == LINE_KEYS]
    return hdr, recs, codes


def check_day(text: str, prev_hdr=None):
    """-> (header, codes, records, notices). notices = late_record: a real record first published after its own day's log was
    sealed. It is reported, not a failure: the issuer's recovery path is to publish it in the next log (PROFILE.md section 4)."""
    hdr, recs, codes = parse_day(text)
    notices = []
    if hdr is None:
        return None, codes, [], notices
    if "bad_fields" in codes:
        return hdr, sorted(set(codes)), [], notices   # the day's lines are not this profile's: no further rule is meaningful
    try:
        s, e = day_edges(hdr["date"])
    except (ValueError, TypeError):
        return hdr, sorted(set(codes + ["bad_day_edges"])), [], notices
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
            # review 4: the anchor bounds when the record was PUBLISHED, never when it was created; its signed created_at is the
            # issuer's claim only. More than GRACE_S before the day is a separate notice (still not a failure: a failed day is
            # terminal for every later day, so failing would turn one honest late publish into a permanently broken chain).
            notices.append("late_record_beyond_grace" if r["created_at"] < s - GRACE_S else "late_record")
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
    return hdr, sorted(set(codes)), recs, sorted(set(notices))


def check_records(recs, records, issuer):
    codes = []
    for r in recs:
        ev = records.get(r["record_event_id"])
        if ev is None:
            codes.append("record_missing"); continue
        try:
            same_id = event_id(ev) == ev.get("id") == r["record_event_id"]
        except (KeyError, ValueError, TypeError):
            same_id = False
        if not same_id:
            codes.append("record_id_mismatch"); continue
        try:
            sig_ok = (ev.get("pubkey") == issuer and isinstance(ev.get("sig"), str) and len(ev["sig"]) == 128
                      and bip340.verify(bytes.fromhex(ev["pubkey"]), bytes.fromhex(ev["id"]), bytes.fromhex(ev["sig"])))
        except (ValueError, TypeError):
            sig_ok = False
        if not sig_ok:
            codes.append("record_signature_invalid"); continue
        try:
            c = json.loads(ev["content"])
            if not isinstance(c, dict):
                raise ValueError
        except (ValueError, TypeError):
            codes.append("record_mismatch"); continue
        if any(c.get(k) != r[k] for k in ("proof_id", "ledger_position", "commitment_hash", "profile")):
            codes.append("record_mismatch")
        if ev["created_at"] != r["created_at"]:
            codes.append("record_created_at_mismatch")
    return codes


def check_chain(days, records=None, issuer=None, ots=None, headers=None, claims=(), pins=None):
    """days: list of file texts, oldest first. Returns one result dict per day.
    'anchored' needs (1) the day confirmed, (2) the chain checked from GENESIS (first file: prev_root zeros, prev_last_position 0),
    else a pre-window omission is invisible (Echo, review 2), and (3) no failed day anywhere before it: a failed day is permanent
    evidence that the history is broken, so every later day stays not_anchored (terminal by design; PROFILE.md section 7)."""
    out, prev, chain_ok, from_genesis, checked_from = [], None, True, None, None
    for text in days:
        hdr, codes, recs, notices = check_day(text, prev)
        codes = list(codes)
        if hdr is not None and from_genesis is None:
            from_genesis = hdr["prev_root"] == ZERO and hdr["prev_last_position"] == 0
            checked_from = hdr["date"]
        if hdr is not None and records is not None:
            codes += check_records(recs, records, issuer)
        date = hdr.get("date") if hdr else None
        state, height = "published", None
        if hdr is not None and ots and date in ots:
            try:
                o = ots_verify.check(ots[date], log_root(hdr), headers or {}, pins)
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
        elif state == "confirmed" and chain_ok and from_genesis:
            status = "anchored"
        else:
            status = "not_anchored"
        chain_ok = chain_ok and not codes
        out.append({"date": date, "status": status, "state": state, "height": height, "codes": codes, "notices": notices,
                    "checked_from": checked_from, "from_genesis": bool(from_genesis), "after_failure": not chain_ok and not codes})
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
                          set(t.get("claims") or ()), {int(k): int(x) for k, x in (t.get("pins") or {}).items()} or None)
        want = t["expect"]
        # review 4: the output fields of section 8 are compared too (hard-coding any of them survived before); review 5 (Pavlo,
        # TG 5889): every result field, including each day's date and its confirmed Bitcoin height
        F = ("checked_from", "from_genesis", "after_failure", "date", "height")
        same = ([(g["status"], g["state"], g["codes"], g["notices"]) + tuple(g[f] for f in F) for g in got]
                == [(w["status"], w["state"], w["codes"], w.get("notices", [])) + tuple(w[f] for f in F) for w in want])
        ok += same; bad += not same
        print(("PASS " if same else "FAIL ") + t["name"] + ("" if same else f"\n  want {want}\n  got  {got}"))
    print(f"{ok}/{ok + bad} vectors pass")
    return 0 if not bad else 1


def main(argv):
    if argv[:1] == ["--vectors"]:
        return run_vectors(argv[1])
    days, ots, claims, records, issuer, headers, pins = [], {}, set(), None, None, {}, None
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
        elif a == "--pins":
            pins = {int(k): int(v) for k, v in json.load(open(argv[i + 1])).items()}; i += 2
        elif a == "--claim-confirmed":
            claims.add(argv[i + 1]); i += 2
        else:
            days.append(open(a, encoding="utf-8", newline="").read()); i += 1
    res = check_chain(days, records, issuer, ots, headers, claims, pins)
    for r in res:
        print(json.dumps(r))
    return 1 if any(r["status"] == "failed" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
