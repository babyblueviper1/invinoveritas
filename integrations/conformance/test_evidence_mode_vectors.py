"""Cross-party conformance: run an INDEPENDENT producer's evidence-mode vectors through OUR referee
classifier and assert we reach the same verdict. The vectors were authored by giskard09 (argentum-core)
in rpelevin's producer_record/referee_record shape (autogen#7353), vendored under fixtures/vendored/.

This is the referee role exercised across parties: the producer says what it intended, our referee
re-derives what it can prove, and the cross_check + displayed claim must match the vector's declared
outcome. It is also a regression guard — a future change to classify_evidence_mode that broke the
contract-aware semantics would fail here.

Scenario inputs per vector are derived from the vector's own description (key present/absent, external
evidence present/absent); see the inline notes. Run: python3 -m pytest test_evidence_mode_vectors.py
"""
import json
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "adapters"))
from live_check import classify_evidence_mode  # noqa: E402

VECTORS = (Path(__file__).resolve().parent / "fixtures" / "vendored"
           / "giskard09-evidence-mode-disclosure-ref-v1.json")

# (declared_hint, derived_mode, key_recomputed, external_evidence, base_claim) per vector id — the scenario
# each vector describes. The referee, absent an external fetch, derives embedded_fixture; key_recomputed is
# whether ANY key recomputes for fallback (NEG-2 has a verifiable embedded key, NEG-1 has none).
SCENARIO = {
    "mode-hint-matches-referee":          ("embedded_fixture", "embedded_fixture", True,  False, "admission_multisig_recomputable"),
    "hint-embedded-fixture-key-absent":   ("embedded_fixture", "embedded_fixture", False, False, "admission_multisig_recomputable"),
    "hint-pinned-registry-no-resolution-evidence": ("pinned_registry", "embedded_fixture", True, False, "admission_multisig_recomputable"),
}


def _vectors():
    data = json.loads(VECTORS.read_text())
    return {v["id"]: v for v in data["vectors"]}


@pytest.mark.parametrize("vid", list(SCENARIO))
def test_referee_reproduces_vector(vid):
    v = _vectors()[vid]
    r = classify_evidence_mode(*SCENARIO[vid])
    # cross_check must match the producer/referee separation the vector declares
    assert r["cross_check"] == v["cross_check"], f"{vid}: cross_check {r['cross_check']} != {v['cross_check']}"
    # the board displays the strongest claim that survives recomputation
    assert r["claim_level"] == v["board_result"]["displayed_claim_level"], \
        f"{vid}: claim {r['claim_level']} != {v['board_result']['displayed_claim_level']}"
    # on a contradiction the referee-derived mode is the *_unverifiable form
    assert r["evidence_mode"] == v["referee_record"]["evidence_mode"], \
        f"{vid}: evidence_mode {r['evidence_mode']} != {v['referee_record']['evidence_mode']}"


def test_all_three_present():
    assert set(_vectors()) >= set(SCENARIO), "vendored vector set changed — re-check the scenario mapping"
