#!/usr/bin/env python3
"""check_traces.py — independent referee grader for a submitted benchmark trace dump (S213).

General conformance-registry intake: given a JSONL of decision traces, recompute each row's verdict
from its OWN bytes and grade it in the depth vocabulary —
  CERTIFIED : the pass/fail verdict is logic-consistent AND tolerance-stable (the observed scorer
              jitter cannot flip it: |score - threshold| > jitter_margin)
  PARTIAL   : verdict is logic-consistent but sits INSIDE the jitter band (bounded by scorer
              reproducibility — the margin does not beat the row's own jitter)
  DEPTH-0   : not recomputable — an injected/observed fault (diagnosis set), or the verdict
              contradicts its own numbers (pass != score>=threshold)

Applies babyblueviper1's tolerance-stable rule EXACTLY: |score - threshold| > jitter_margin.

Referee-hard (the whole point): we do NOT run the producer's recompute.py and report its output —
we recompute independently from the bytes. We ALSO replicate the producer's own cut and report
where the two grades DIVERGE (referee-of-referees: recompute the recomputers). The score values
themselves are producer-asserted (no live scorer); CERTIFIED is a verdict-reproducibility claim,
with the model/probe digests graded separately as the reproducible-fingerprint tier.

Run: python3 check_traces.py --traces /path/to/traces.jsonl
"""
import argparse
import hashlib
import json
from collections import Counter

FAULT_DIAGNOSES = {"unrecoverable_fault", "network_layer", "provider_reject", "unknown"}


# --- independent digest recompute (reproducible-fingerprint tier) ---
def recompute_model_digest(t: dict) -> bool:
    raw = f"{t['provider']}:{t['model']}:v1.1.0:stable"
    return t.get("model_digest") == hashlib.sha256(raw.encode()).hexdigest()[:16]


def recompute_probe_digest(t: dict) -> bool:
    probes = [
        "The quick brown fox jumps over the lazy dog.",
        "Explain quantum computing in one sentence.",
        "What is 2+2?",
        "Translate 'hello' to French.",
        "Summarize: The sun rises in the east.",
    ]
    raw = f"{t['provider']}:{t['model']}:" + "|".join(
        hashlib.md5(f"{p}:{t['provider']}:{t['model']}".encode()).hexdigest()[:8] for p in probes
    )
    return t.get("probe_digest") == hashlib.sha256(raw.encode()).hexdigest()[:16]


# --- our independent tolerance-stable grade for one dimension ---
def grade_dim(d: dict):
    score, thr = d.get("score"), d.get("threshold", 0.8)
    jit, diag, rec_pass = d.get("jitter_margin", 0.0), d.get("diagnosis"), d.get("pass")
    logic_pass = score is not None and score >= thr
    logic_ok = rec_pass == logic_pass  # does the recorded verdict match its own numbers?
    if diag in FAULT_DIAGNOSES or score is None:
        return "DEPTH-0", logic_ok
    if not logic_ok:
        return "DEPTH-0", logic_ok  # verdict contradicts its own score = not recomputable
    margin = abs(score - thr)
    return ("CERTIFIED" if margin > jit else "PARTIAL"), logic_ok


def roll_up(dim_tiers):
    if all(c == "CERTIFIED" for c in dim_tiers):
        return "CERTIFIED"
    if all(c in ("CERTIFIED", "PARTIAL") for c in dim_tiers):
        return "PARTIAL"
    if any(c in ("CERTIFIED", "PARTIAL") for c in dim_tiers):
        return "PARTIAL"
    return "DEPTH-0"


# --- the producer's OWN cut, replicated, for the referee-of-referees comparison ---
def their_dim(d: dict) -> str:
    score, thr, jit = d.get("score", 0), d.get("threshold", 0.8), d.get("jitter_margin", 0)
    if d.get("diagnosis") in FAULT_DIAGNOSES:
        return "DEPTH-0"
    if jit == 0 and score < thr:
        return "DEPTH-0"
    if score > thr and jit > 0:
        return "CERTIFIED" if jit > 0.01 else "PARTIAL"
    if score >= thr:
        return "PARTIAL"
    return "DEPTH-0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--traces", default="traces.jsonl")
    args = ap.parse_args()

    overall = Counter()
    dim_tier = Counter()
    logic_fail = 0
    md_ok = pd_ok = 0
    crosscheck_ok = 0
    diverge = 0  # rows where our overall grade differs from the producer's cut
    diverge_examples = []
    n = 0

    for line in open(args.traces):
        line = line.strip()
        if not line:
            continue
        t = json.loads(line)
        n += 1
        dims = t.get("six_dimensions", {})
        mine, theirs = [], []
        for dn, dd in dims.items():
            tier, logic_ok = grade_dim(dd)
            dim_tier[tier] += 1
            if not logic_ok:
                logic_fail += 1
            mine.append(tier)
            theirs.append(their_dim(dd))
        my_overall = roll_up(mine)
        their_overall = roll_up(theirs)
        overall[my_overall] += 1
        if my_overall != their_overall and len(diverge_examples) < 5:
            diverge_examples.append((t["trace_id"], t["group"], my_overall, their_overall))
        if my_overall != their_overall:
            diverge += 1
        if recompute_model_digest(t):
            md_ok += 1
        if recompute_probe_digest(t):
            pd_ok += 1
        # cross-check: does the recorded validation_result agree with our recomputed verdict?
        rec_pass = t.get("validation_result") == "PASS"
        my_pass = my_overall in ("CERTIFIED", "PARTIAL")
        if rec_pass == my_pass:
            crosscheck_ok += 1

    print("=" * 72)
    print("INDEPENDENT REFEREE GRADE — Correctover benchmark (recomputed from bytes, not via their recompute.py)")
    print("=" * 72)
    print(f"\ntraces graded: {n}")
    print("\n-- per-row overall (our tolerance-stable grade: |score-threshold| > jitter_margin) --")
    for c in ("CERTIFIED", "PARTIAL", "DEPTH-0"):
        print(f"   {c:10}: {overall[c]:6} ({overall[c]/n*100:5.1f}%)")
    print("\n-- per-dimension tiers --")
    tot_d = sum(dim_tier.values())
    for c in ("CERTIFIED", "PARTIAL", "DEPTH-0"):
        print(f"   {c:10}: {dim_tier[c]:6} ({dim_tier[c]/tot_d*100:5.1f}%)")
    print("\n-- integrity / fingerprint tier (recomputed from the published recipe) --")
    print(f"   model_digest reproduces : {md_ok}/{n} ({md_ok/n*100:.1f}%)")
    print(f"   probe_digest reproduces : {pd_ok}/{n} ({pd_ok/n*100:.1f}%)")
    print(f"   verdict logic-consistent (pass == score>=threshold): {n*6-logic_fail}/{n*6} "
          f"({(n*6-logic_fail)/(n*6)*100:.2f}%)")
    print(f"   cross-check vs recorded validation_result: {crosscheck_ok}/{n} ({crosscheck_ok/n*100:.1f}%)")
    print("\n-- referee-of-referees: our grade vs their recompute.py cut --")
    print(f"   rows where grades DIVERGE: {diverge} ({diverge/n*100:.1f}%)")
    print("   (divergence = their `jitter>0.01` cut grades CERTIFIED where the margin does NOT beat")
    print("    the row's own jitter — i.e. inside-band verdicts we hold to PARTIAL)")
    for tid, g, mine_o, theirs_o in diverge_examples:
        print(f"     trace {tid} (grp {g}): ours={mine_o}  theirs={theirs_o}")


if __name__ == "__main__":
    main()
