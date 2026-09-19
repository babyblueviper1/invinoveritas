"""Self-contained tests for the portable invinoveritas verifier. No network, no deps — `python -m pytest`
or just `python test_verify_proof.py`. Uses a vendored real proof (sample_proof.json) so the keystone
property — offline verification of a genuine proof — is provable anywhere this repo is cloned."""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import invinoveritas_verify as V  # noqa: E402

SAMPLE = json.load(open(os.path.join(os.path.dirname(__file__), "sample_proof.json")))


def test_real_proof_verifies_offline():
    r = V.verify_proof(SAMPLE)
    assert r["valid"] is True, r
    assert all(r["checks"].values()), r["checks"]
    assert r["issued_by_invinoveritas"] is True


def test_content_tamper_fails():
    ev = copy.deepcopy(SAMPLE)
    ev["content"] = ev["content"][:-2] + "XY"
    r = V.verify_proof(ev)
    assert r["valid"] is False
    assert r["checks"]["id_integrity"] is False   # recomputed id no longer matches the claimed id


def test_sig_tamper_fails():
    ev = copy.deepcopy(SAMPLE)
    s = ev["sig"]
    ev["sig"] = s[:-2] + ("00" if s[-2:] != "00" else "11")
    r = V.verify_proof(ev)
    assert r["valid"] is False
    assert r["checks"]["signature_valid"] is False


def test_foreign_key_not_ours():
    ev = copy.deepcopy(SAMPLE)
    p = ev["pubkey"]
    ev["pubkey"] = p[:-2] + ("00" if p[-2:] != "00" else "11")
    r = V.verify_proof(ev)
    assert r["valid"] is False
    assert r["checks"]["issued_by_invinoveritas"] is False


def test_malformed_never_raises():
    for bad in [None, {}, {"id": "x"}, {"content": "x" * 70000}, 42, "string"]:
        r = V.verify_proof(bad)
        assert r["valid"] is False  # returns a verdict, never raises


def test_event_id_recompute_matches():
    assert V.nostr_event_id(SAMPLE).lower() == str(SAMPLE["id"]).lower()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
