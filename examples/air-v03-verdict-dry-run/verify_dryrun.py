"""Run AIR v0.3-draft-2 §2.7 against a real invinoveritas /ledger binding.

Steps 1–5 are structural, deterministic, and offline. Step 6 is the
consumer-judgment step and is where the §2.6 three-state authority fixture
lives. Scheme verification (step 3) is a real call to
`services.proof_signing.verify_proof_event`, not a stub.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from services.proof_signing import PUBLISHED_PUBKEY, verify_proof_event  # noqa: E402

from verdict_binding import (  # noqa: E402
    DEFAULT_EVENT_ID,
    FIXTURES,
    authorization_sha256,
    binding_shape_errors,
    build_binding,
    event_from_artifact_bytes,
    obtain_event,
    published_authority_ref,
)

# ---------------------------------------------------------------------------
# Trust policies — the consumer-side lists §2.6 classifies against.
# Each published classification MUST carry the trust_policy_id it was
# computed against (recomputability rule, pipavlo82).
# ---------------------------------------------------------------------------

POLICY_ACCEPTS = {
    "trust_policy_id": "air.issuer_signed.v0:accepts-invinoveritas-published-key",
    "trust_model": "issuer_signed",
    "accepted_authority_refs": [
        # Filled at load time so a key rotation cannot silently desync the
        # fixture from services.proof_signing.PUBLISHED_PUBKEY.
    ],
}

POLICY_EXCLUDES = {
    "trust_policy_id": "air.issuer_signed.v0:excludes-invinoveritas-key",
    "trust_model": "issuer_signed",
    # A real other key (not ours). Listing *something* makes this a policy
    # that has members, not an empty-list encoding of "no bindings".
    "accepted_authority_refs": [
        "nostr:0000000000000000000000000000000000000000000000000000000000000001"
    ],
}

STRUCTURALLY_INVALID = "structurally_invalid"
STRUCTURALLY_VALID_ZERO_AUTHORITY = "structurally_valid_zero_authority"
VALID_AND_AUTHORIZED = "valid_and_authorized"


def _policies() -> tuple[dict[str, Any], dict[str, Any]]:
    accepts = dict(POLICY_ACCEPTS)
    accepts["accepted_authority_refs"] = [published_authority_ref()]
    return accepts, dict(POLICY_EXCLUDES)


def write_policy_fixtures() -> None:
    accepts, excludes = _policies()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "trust_policy_accepts.json").write_text(
        json.dumps(accepts, indent=2) + "\n", encoding="utf-8"
    )
    (FIXTURES / "trust_policy_excludes.json").write_text(
        json.dumps(excludes, indent=2) + "\n", encoding="utf-8"
    )


def _content_obj(event: dict[str, Any]) -> dict[str, Any]:
    try:
        obj = json.loads(event.get("content") or "")
    except Exception:
        return {}
    return obj if isinstance(obj, dict) else {}


def field_in_artifact(event: dict[str, Any], field: str) -> tuple[bool, str | None, Any]:
    """Locate a declared axis field in the artifact.

    The artifact is the signed Nostr event. Worked example (1) names
    `created_at`, which lives on the envelope. Fields that only exist
    inside `content` (the signed payload) are accepted as in-artifact too.
    """
    if field in event:
        return True, "event", event[field]
    content = _content_obj(event)
    if field in content:
        return True, "content", content[field]
    return False, None, None


# ---------------------------------------------------------------------------
# §2.7 steps
# ---------------------------------------------------------------------------

def step1_obtain(
    binding: dict[str, Any],
    blob: bytes | None,
    obtain_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Obtain the artifact from already-held bytes (out-of-band fetch already done)."""
    hint = binding.get("transport_hint")
    uri = binding.get("authorization_uri")
    if not blob:
        return {
            "step": 1,
            "name": "obtain_artifact",
            "status": "fail",
            "detail": (
                f"no bytes held for transport_hint={hint!r} authorization_uri={uri!r} "
                "(§2.7 step 1 is offline: retrieval happens out-of-band)"
            ),
        }
    try:
        event = event_from_artifact_bytes(blob)
    except Exception as exc:
        return {
            "step": 1,
            "name": "obtain_artifact",
            "status": "fail",
            "detail": f"held bytes are not a parseable event: {type(exc).__name__}: {exc}",
            "bytes": len(blob),
        }
    return {
        "step": 1,
        "name": "obtain_artifact",
        "status": "pass",
        "detail": (
            f"{len(blob)} bytes already held "
            f"(transport_hint={hint}, uri={uri}, source={((obtain_meta or {}).get('source'))})"
        ),
        "bytes": len(blob),
        "event_id": event.get("id"),
        "source": (obtain_meta or {}).get("source"),
        "fetched_from": (obtain_meta or {}).get("fetched_from")
        or (obtain_meta or {}).get("originally_fetched_from"),
    }


def step2_sha256(binding: dict[str, Any], blob: bytes) -> dict[str, Any]:
    recomputed = hashlib.sha256(blob).hexdigest()
    declared = binding.get("authorization_sha256")
    match = recomputed == declared
    return {
        "step": 2,
        "name": "authorization_sha256",
        "status": "pass" if match else "fail",
        "detail": (
            "SHA-256(bytes) == authorization_sha256"
            if match
            else "SHA-256(bytes) != authorization_sha256 — transport failure, not a signing failure (§2.7 step 2)"
        ),
        "declared": declared,
        "recomputed": recomputed,
        "match": match,
    }


def step3_scheme(event: dict[str, Any]) -> dict[str, Any]:
    """Verify the artifact per scheme — real verify_proof_event()."""
    result = verify_proof_event(event)
    checks = result.get("checks") or {}
    valid = bool(result.get("valid"))
    return {
        "step": 3,
        "name": "scheme_verify",
        "status": "pass" if valid else "fail",
        "detail": (
            "verify_proof_event() valid=True on the fetched event"
            if valid
            else f"verify_proof_event() valid=False ({result.get('error') or checks})"
        ),
        "valid": valid,
        "checks": checks,
        "error": result.get("error"),
        "published_pubkey": result.get("published_pubkey") or PUBLISHED_PUBKEY,
        "decision_ref": (result.get("proof_payload") or {}).get("decision_ref"),
        "schema": (result.get("proof_payload") or {}).get("schema"),
    }


def step4_axes(binding: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    axes = binding.get("axes") if isinstance(binding.get("axes"), dict) else {}
    missing_keys = [k for k in ("precedence", "freshness", "correctness") if k not in axes]
    if missing_keys:
        return {
            "step": 4,
            "name": "axes_declaration",
            "status": "fail",
            "detail": f"axes omitted required key(s) {missing_keys} — omission is not a declaration",
            "fields": [],
        }
    fields: list[dict[str, Any]] = []
    failures: list[str] = []
    for axis_name in ("precedence", "freshness", "correctness"):
        decl = axes[axis_name]
        if decl is None:
            fields.append({"axis": axis_name, "declaration": None, "check": "n/a (present-and-null)"})
            continue
        if not isinstance(decl, dict):
            failures.append(f"{axis_name} is neither null nor an object")
            fields.append({"axis": axis_name, "declaration": decl, "check": "fail"})
            continue
        # Point-in-time precedence uses {"field": "..."}. Freshness flavors
        # name different slots; collect every *_field / field value.
        named: list[str] = []
        if isinstance(decl.get("field"), str):
            named.append(decl["field"])
        for k, v in decl.items():
            if k.endswith("_field") and isinstance(v, str):
                named.append(v)
        if not named:
            failures.append(f"{axis_name} declared but names no artifact field")
            fields.append({"axis": axis_name, "declaration": decl, "check": "fail"})
            continue
        for field in named:
            found, loc, value = field_in_artifact(event, field)
            if not found:
                failures.append(f"{axis_name}.{field} not present in the artifact")
                fields.append(
                    {"axis": axis_name, "field": field, "present": False, "check": "fail"}
                )
                continue
            if value is None:
                state = event.get("state")
                if state is None:
                    state = _content_obj(event).get("state")
                # §2.7 step 4: a declared axis may reference a null-valued
                # field only when the artifact's state is a degraded state
                # that licenses the null (§2.5).
                if state not in {"unavailable"}:
                    failures.append(
                        f"{axis_name}.{field} is present-and-null but artifact state={state!r} "
                        "does not license a null coverage slot"
                    )
                    fields.append(
                        {
                            "axis": axis_name,
                            "field": field,
                            "present": True,
                            "value": None,
                            "where": loc,
                            "check": "fail",
                        }
                    )
                    continue
            fields.append(
                {
                    "axis": axis_name,
                    "field": field,
                    "present": True,
                    "where": loc,
                    "value": value,
                    "check": "pass",
                }
            )
    return {
        "step": 4,
        "name": "axes_declaration",
        "status": "pass" if not failures else "fail",
        "detail": (
            "every declared field exists in the artifact"
            if not failures
            else "; ".join(failures)
        ),
        "fields": fields,
    }


def step5_coherence(binding: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """Coherence table — rolling-snapshot `state` only.

    Confirmed against draft-2 §2.5 / §2.7 step 5: the table is keyed on
    `state: fresh | stale | unavailable`, which §2.5 requires of
    rolling-snapshot artifacts and does not require of point-in-time
    verdicts. A point-in-time binding with axes.freshness=null and no
    `state` field has nothing for the table to apply to — N/A, not fail.
    """
    axes = binding.get("axes") if isinstance(binding.get("axes"), dict) else {}
    content = _content_obj(event)
    state = event["state"] if "state" in event else content.get("state") if "state" in content else None
    if state is None and axes.get("freshness") is None:
        return {
            "step": 5,
            "name": "coherence_table",
            "status": "n/a",
            "detail": (
                "point-in-time verdict: artifact has no `state` field and "
                "axes.freshness is null. §2.7 step 5's fresh/stale/unavailable "
                "table applies to rolling-snapshot artifacts (§2.5), not to this class."
            ),
            "state": None,
        }
    if state is None:
        return {
            "step": 5,
            "name": "coherence_table",
            "status": "fail",
            "detail": (
                "freshness is declared but the artifact has no `state` field; "
                "§2.5 rolling-snapshot artifacts MUST carry the closed vocabulary"
            ),
            "state": None,
        }
    # (a) observation timestamp, (b) declared cadence — required present
    # in every snapshot state. We look at the freshness declaration's
    # named fields when present; otherwise the well-known snapshot slots.
    freshness = axes.get("freshness") if isinstance(axes.get("freshness"), dict) else {}
    a_field = freshness.get("observed_at_field") or "fetched_at"
    b_field = freshness.get("max_age_field") or "max_age_seconds"
    a_present, _, a_val = field_in_artifact(event, a_field)
    b_present, _, b_val = field_in_artifact(event, b_field)
    if state in {"fresh", "stale"}:
        ok = a_present and a_val is not None and b_present and b_val is not None
        detail = (
            f"state={state!r} ⇒ (a) {a_field} and (b) {b_field} MUST be value-bearing"
        )
    elif state == "unavailable":
        ok = a_present and a_val is None and b_present and b_val is None
        detail = (
            f"state='unavailable' ⇒ (a) {a_field} and (b) {b_field} MUST be present-and-null"
        )
    else:
        return {
            "step": 5,
            "name": "coherence_table",
            "status": "fail",
            "detail": f"state={state!r} is outside the closed vocabulary fresh|stale|unavailable",
            "state": state,
        }
    return {
        "step": 5,
        "name": "coherence_table",
        "status": "pass" if ok else "fail",
        "detail": detail + ("" if ok else " — not met"),
        "state": state,
        "observation": {"field": a_field, "present": a_present, "value": a_val},
        "cadence": {"field": b_field, "present": b_present, "value": b_val},
    }


def classify_authority(
    *,
    structural_ok: bool,
    authority_ref: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """§2.6 three-state fixture-flip. Classification is a function of
    (structural validity, consumer policy), never of the binding claiming
    authority. The trust_policy_id travels with every published result.
    """
    policy_id = policy.get("trust_policy_id")
    accepted = {str(x).strip().lower() for x in (policy.get("accepted_authority_refs") or [])}
    listed = authority_ref.strip().lower() in accepted
    if not structural_ok:
        classification = STRUCTURALLY_INVALID
    elif not listed:
        classification = STRUCTURALLY_VALID_ZERO_AUTHORITY
    else:
        classification = VALID_AND_AUTHORIZED
    return {
        "classification": classification,
        "trust_policy_id": policy_id,
        "authority_ref": authority_ref,
        "listed_by_policy": listed,
        "structural_ok": structural_ok,
    }


def step6_consumer(
    binding: dict[str, Any],
    structural_ok: bool,
    policies: list[dict[str, Any]],
) -> dict[str, Any]:
    """Consumer-judgment step. Freshness is null here; no network.

    Authority is classified independently against each supplied policy so
    the fixture-flip is a real result, not a narration.
    """
    axes = binding.get("axes") if isinstance(binding.get("axes"), dict) else {}
    freshness_decl = axes.get("freshness")
    freshness = {
        "declared": freshness_decl,
        "computed": None,
        "detail": (
            "axes.freshness is null — a point-in-time verdict visibly claims "
            "nothing about 'still holds'; no consumer freshness function to run"
        ),
    }
    classifications = [
        classify_authority(
            structural_ok=structural_ok,
            authority_ref=str(binding.get("authority_ref") or ""),
            policy=p,
        )
        for p in policies
    ]
    return {
        "step": 6,
        "name": "consumer_judgment",
        "status": "pass",  # step 6 is never format-validity; it always produces a classification
        "detail": (
            "authority classified per §2.6 against each consumer trust-policy; "
            "freshness not declared; anchoring existence N/A (not chain_anchored)"
        ),
        "freshness": freshness,
        "anchoring_existence": {
            "applicable": False,
            "detail": "trust_model=issuer_signed — §3.4 existence check is chain_anchored-only",
        },
        "classifications": classifications,
    }


def run_procedure(
    binding: dict[str, Any],
    blob: bytes,
    obtain_meta: dict[str, Any] | None = None,
    policies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    shape = binding_shape_errors(binding)
    s1 = step1_obtain(binding, blob, obtain_meta)
    event: dict[str, Any] | None = None
    if s1["status"] == "pass":
        event = event_from_artifact_bytes(blob)
        s2 = step2_sha256(binding, blob)
        s3 = step3_scheme(event)
        s4 = step4_axes(binding, event)
        s5 = step5_coherence(binding, event)
    else:
        s2 = {
            "step": 2,
            "name": "authorization_sha256",
            "status": "fail",
            "detail": "skipped — no artifact bytes",
        }
        s3 = {
            "step": 3,
            "name": "scheme_verify",
            "status": "fail",
            "detail": "skipped — no artifact",
        }
        s4 = {
            "step": 4,
            "name": "axes_declaration",
            "status": "fail",
            "detail": "skipped — no artifact",
        }
        s5 = {
            "step": 5,
            "name": "coherence_table",
            "status": "fail",
            "detail": "skipped — no artifact",
        }
    structural_statuses = [s1["status"], s2["status"], s3["status"], s4["status"], s5["status"]]
    # n/a is not a structural failure (step 5 on a point-in-time verdict).
    structural_ok = all(s in {"pass", "n/a"} for s in structural_statuses) and not shape
    if policies is None:
        accepts, excludes = _policies()
        policies = [accepts, excludes]
    s6 = step6_consumer(binding, structural_ok, policies)
    return {
        "spec_version": "0.3-draft-2",
        "shape_errors": shape,
        "structural_ok": structural_ok,
        "steps": [s1, s2, s3, s4, s5, s6],
        "event_id": (event or {}).get("id"),
    }


def tamper_artifact_bytes(blob: bytes) -> bytes:
    """Flip one byte so step 2 genuinely fails. Keeps the blob non-empty."""
    if not blob:
        raise ValueError("nothing to tamper")
    arr = bytearray(blob)
    # Prefer flipping a hex digit inside the JSON so it stays parseable.
    for i, b in enumerate(arr):
        if b in b"abcdef0123456789" and chr(b) != "0":
            arr[i] = ord("0")
            return bytes(arr)
    arr[-1] ^= 0x01
    return bytes(arr)


def fixture_flip(binding: dict[str, Any], blob: bytes) -> dict[str, Any]:
    """Identical bundle, three classifications — closes §6 'fixtures owed'
    for the issuer_signed surface."""
    accepts, excludes = _policies()
    clean = run_procedure(binding, blob, policies=[accepts, excludes])
    tampered_blob = tamper_artifact_bytes(blob)
    broken = run_procedure(binding, tampered_blob, policies=[accepts])
    clean_classes = {
        c["trust_policy_id"]: c["classification"]
        for c in clean["steps"][5]["classifications"]
    }
    broken_class = broken["steps"][5]["classifications"][0]["classification"]
    return {
        "name": "issuer_signed three-state fixture-flip (§2.6 / §6 fixtures owed)",
        "identical_bundle": {
            accepts["trust_policy_id"]: clean_classes.get(accepts["trust_policy_id"]),
            excludes["trust_policy_id"]: clean_classes.get(excludes["trust_policy_id"]),
        },
        "tampered_bundle": {
            accepts["trust_policy_id"]: broken_class,
            "authorization_sha256_declared": binding["authorization_sha256"],
            "authorization_sha256_tampered": hashlib.sha256(tampered_blob).hexdigest(),
        },
        "demonstrated": {
            VALID_AND_AUTHORIZED: clean_classes.get(accepts["trust_policy_id"])
            == VALID_AND_AUTHORIZED,
            STRUCTURALLY_VALID_ZERO_AUTHORITY: clean_classes.get(excludes["trust_policy_id"])
            == STRUCTURALLY_VALID_ZERO_AUTHORITY,
            STRUCTURALLY_INVALID: broken_class == STRUCTURALLY_INVALID,
        },
    }


def _print_step(step: dict[str, Any]) -> None:
    status = step.get("status", "?").upper()
    print(f"  Step {step.get('step')}: {step.get('name')} — {status}")
    print(f"    {step.get('detail')}")
    if step.get("step") == 2:
        print(f"    declared   {step.get('declared')}")
        print(f"    recomputed {step.get('recomputed')}")
    if step.get("step") == 3 and step.get("checks"):
        print(f"    checks     {json.dumps(step['checks'])}")
        if step.get("decision_ref"):
            print(f"    decision_ref {step['decision_ref']}")
    if step.get("step") == 4:
        for f in step.get("fields") or []:
            print(f"    axis {f}")
    if step.get("step") == 6:
        for c in step.get("classifications") or []:
            print(
                f"    {c['classification']}  policy={c['trust_policy_id']}  "
                f"listed={c['listed_by_policy']}"
            )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    refetch = "--refetch" in args
    write_policy_fixtures()
    event, blob, obtain_meta = obtain_event(DEFAULT_EVENT_ID, refetch=refetch)
    binding = build_binding(event)
    from verdict_binding import write_binding

    write_binding(binding)

    print("AIR v0.3-draft-2 verdict-side dry-run")
    print(f"  ledger     {binding and 'https://api.babyblueviper.com/ledger/62'}")
    print(f"  event_id   {event['id']}")
    print(f"  obtain     {json.dumps(obtain_meta, sort_keys=True)}")
    print(f"  sha256     {authorization_sha256(event)}")
    print(f"  authority  {binding['authority_ref']}")
    print()
    print("Binding (issuer_signed):")
    print(json.dumps(binding, indent=2))
    print()

    report = run_procedure(binding, blob, obtain_meta)
    print("§2.7 verification procedure")
    for step in report["steps"]:
        _print_step(step)
        print()
    print(f"structural_ok (steps 1–5): {report['structural_ok']}")
    if report["shape_errors"]:
        print(f"shape_errors: {report['shape_errors']}")
    print()

    flip = fixture_flip(binding, blob)
    print(flip["name"])
    print(f"  identical bundle + accepting policy : {flip['identical_bundle']}")
    print(f"  tampered bundle  + accepting policy : {flip['tampered_bundle']}")
    print(f"  demonstrated                        : {json.dumps(flip['demonstrated'])}")
    all_three = all(flip["demonstrated"].values())
    print(f"  all three states shown              : {all_three}")

    # Persist the report next to the fixtures so the README can cite it.
    (FIXTURES / "last_dryrun.json").write_text(
        json.dumps({"procedure": report, "fixture_flip": flip}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if report["structural_ok"] and all_three else 1


if __name__ == "__main__":
    raise SystemExit(main())
