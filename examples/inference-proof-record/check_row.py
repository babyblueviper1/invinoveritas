#!/usr/bin/env python3
"""Validate an invinoveritas.inference_benchmark_row.v0 row (stdlib only). Exit 0 = the row is complete and self-consistent.

Checks: every section and field is present and filled (no '<...>' placeholders); the referee verifier is the system's own and its
commit is a 40-hex id; the verdict is YES or NO and matches the result line where the line carries a status; at least one negative
control, every one expected NO and observed as a refusal; the gates list both what the run covers and what it does not; the checker
names its relation to the producer and the sha256 of the full record.
It checks the ROW, not the proof: re-run the referee verifier yourself to check the proof.
usage: python3 check_row.py ROW.json [ROW.json ...]"""
import json, re, sys

REQ = {
    "system": ["name", "repo", "commit", "license", "modified"],
    "request_shape": ["request_length", "checked_positions", "next_token_included", "decoding", "proof_timing", "model"],
    "hardware": ["prove", "verify"],
    "numbers": ["prove_seconds", "prove_peak_rss_kb", "proof_bytes", "verify_seconds", "verify_peak_rss_kb"],
    "referee": ["verifier", "verifier_commit", "verifier_source_digest", "verdict", "result_line"],
    "negative_controls": None,
    "gates": ["covers", "does_not_cover"],
    "checker": ["party", "independent_of_producer", "checked_at", "record_sha256"],
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def check(row):
    errs = []
    if row.get("schema") != "invinoveritas.inference_benchmark_row.v0":
        errs.append("schema is not invinoveritas.inference_benchmark_row.v0")
    for sec, keys in REQ.items():
        if sec not in row:
            errs.append(f"missing section {sec}"); continue
        for k in keys or []:
            if k not in row[sec]:
                errs.append(f"missing {sec}.{k}")
    if "<" in json.dumps(row):
        errs.append("unfilled '<...>' placeholder left in the row")
    sysc, ref = row.get("system", {}), row.get("referee", {})
    for k in ("commit",):
        if not HEX40.match(str(sysc.get(k, ""))):
            errs.append(f"system.{k} is not a 40-hex commit")
    if not HEX40.match(str(ref.get("verifier_commit", ""))):
        errs.append("referee.verifier_commit is not a 40-hex commit")
    v = ref.get("verdict")
    if v not in ("YES", "NO"):
        errs.append("referee.verdict must be YES or NO")
    m = re.search(r"status=(\d+)", str(ref.get("result_line", "")))
    if m and v in ("YES", "NO") and (m.group(1) == "0") != (v == "YES"):
        errs.append(f"verdict {v} contradicts the result line's status={m.group(1)}")
    nc = row.get("negative_controls") or []
    if not nc:
        errs.append("no negative controls")
    for i, c in enumerate(nc):
        if c.get("expected") != "NO":
            errs.append(f"negative_controls[{i}].expected must be NO")
        if not str(c.get("observed", "")).startswith("NO"):
            errs.append(f"negative_controls[{i}] was not refused (observed {c.get('observed')!r})")
    g = row.get("gates", {})
    if not g.get("covers") or not g.get("does_not_cover"):
        errs.append("gates must list both covers and does_not_cover")
    ch = row.get("checker", {})
    if not re.match(r"^[0-9a-f]{64}$", str(ch.get("record_sha256", ""))):
        errs.append("checker.record_sha256 is not a sha256")
    return errs


def main():
    bad = 0
    for p in sys.argv[1:]:
        errs = check(json.load(open(p)))
        print(f"{p}: {'OK' if not errs else 'FAIL'}")
        for e in errs:
            print(f"  - {e}")
        bad += bool(errs)
    sys.exit(1 if bad or len(sys.argv) < 2 else 0)


if __name__ == "__main__":
    main()
