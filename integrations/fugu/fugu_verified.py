"""fugu_verified — run Sakana Fugu as the engine, gate on an independent invinoveritas verdict.

Fugu (https://sakana.ai/fugu) is an OpenAI-compatible orchestration model whose routing is
withheld by design, and whose only "Verifier" role is one of its own pooled models grading the
others. The one role it can't self-staff is an INDEPENDENT verifier outside the pool. This is it:
call Fugu, then before any irreversible step get a neutral verdict + portable signed proof from
invinoveritas (/review, /verify-proof) that anyone re-checks without trusting Fugu or us.

Zero framework deps (just `requests`); Fugu is reached over its OpenAI-compatible endpoint, so you
can equally point the official `openai` SDK at FUGU_BASE_URL — this module avoids the dep on purpose.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import requests

FUGU_BASE_URL = os.getenv("FUGU_BASE_URL", "https://api.sakana.ai/v1")
IVV_BASE_URL = os.getenv("IVV_BASE_URL", "https://api.babyblueviper.com")

# verdict ordering, best -> worst; `require` gates on "at least this good"
_VERDICT_RANK = {"approve": 0, "approve_with_concerns": 1, "reject": 2}


def _fugu_complete(task: str, *, model: str, system: str | None, timeout: int) -> str:
    """Call Fugu's OpenAI-compatible chat endpoint and return the assistant text."""
    key = os.environ["FUGU_API_KEY"]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": task})
    r = requests.post(
        f"{FUGU_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _review(artifact: str, *, artifact_type: str, context: str,
            include_trading_state: bool, timeout: int) -> dict[str, Any]:
    """Independent verdict from invinoveritas, signed so it's portable + recomputable."""
    key = os.environ["IVV_API_KEY"]
    body: dict[str, Any] = {
        "artifact": artifact,
        "artifact_type": artifact_type,
        "context": context,
        "sign": True,
    }
    if include_trading_state:
        body["include_trading_state"] = True
    r = requests.post(
        f"{IVV_BASE_URL}/review",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def verify_proof(proof_event: dict, *, expect_artifact_hash: str | None = None,
                 timeout: int = 30) -> dict[str, Any]:
    """Re-check a verdict proof with no auth and no trust in the issuer (free endpoint)."""
    body: dict[str, Any] = {"event": proof_event}
    if expect_artifact_hash:
        body["expect_artifact_hash"] = expect_artifact_hash
    r = requests.post(f"{IVV_BASE_URL}/verify-proof", json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fugu_verified(
    task: str,
    *,
    artifact_type: str = "text",
    context: str = "",
    require: str = "approve",
    fugu_model: str = "fugu-ultra",
    system: str | None = None,
    include_trading_state: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    """Run Fugu, then gate its output on an independent invinoveritas verdict.

    Returns a dict with:
      output    – Fugu's answer
      verdict   – approve | approve_with_concerns | reject
      blocked   – True if verdict is worse than `require`
      issues    – list of issues the verdict raised
      proof     – portable schnorr-signed verdict (attach it downstream); None if unsigned
      artifact_sha256 – sha256 of the exact output the verdict ran on
    """
    if require not in _VERDICT_RANK:
        raise ValueError(f"require must be one of {list(_VERDICT_RANK)}")

    output = _fugu_complete(task, model=fugu_model, system=system, timeout=timeout)
    review = _review(
        output, artifact_type=artifact_type, context=context,
        include_trading_state=include_trading_state, timeout=timeout,
    )
    verdict = review.get("verdict", "reject")
    blocked = _VERDICT_RANK.get(verdict, 99) > _VERDICT_RANK[require]
    return {
        "output": output,
        "verdict": verdict,
        "blocked": blocked,
        "issues": review.get("issues", []),
        "proof": review.get("proof"),
        "artifact_sha256": hashlib.sha256(output.encode()).hexdigest(),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Run Sakana Fugu behind an independent verify gate.")
    ap.add_argument("task", help="the prompt / task for Fugu")
    ap.add_argument("--type", default="text", dest="artifact_type",
                    help="artifact_type: text | code_diff | command | trade | plan")
    ap.add_argument("--context", default="", help="context for the verdict")
    ap.add_argument("--require", default="approve",
                    help="gate threshold: approve | approve_with_concerns | reject")
    ap.add_argument("--model", default="fugu-ultra", dest="fugu_model")
    ap.add_argument("--proof-out", default=None, help="write the signed proof to this path")
    args = ap.parse_args()

    res = fugu_verified(
        args.task, artifact_type=args.artifact_type, context=args.context,
        require=args.require, fugu_model=args.fugu_model,
    )
    if args.proof_out and res.get("proof"):
        with open(args.proof_out, "w") as fh:
            json.dump(res["proof"], fh, indent=2)
    print(json.dumps({k: v for k, v in res.items() if k != "output"}, indent=2))
    print("\n--- Fugu output ---\n" + res["output"])
    raise SystemExit(1 if res["blocked"] else 0)
