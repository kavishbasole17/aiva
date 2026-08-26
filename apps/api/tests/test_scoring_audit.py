from app.scoring_audit import (
    ScoringRunFacts,
    audit_missing_citations,
    audit_narrow_score_bands,
    audit_verdict_drift,
)


def _run(resume_id: str, profile_id: str, score: int, verdict: str, dims=None) -> ScoringRunFacts:
    return ScoringRunFacts(
        resume_id=resume_id,
        weight_profile_id=profile_id,
        total_score=score,
        verdict=verdict,
        run_fingerprint="f" * 64,
        dimensions_payload=dims or [{"dimension": "technical", "evidence_refs": ["span-1"]}],
        created_at="2026-01-01T00:00:00Z",
    )


def test_verdict_drift_detected_for_same_resume_and_profile() -> None:
    runs = [_run("r1", "p1", 80, "shortlist"), _run("r1", "p1", 20, "auto_reject")]
    findings = audit_verdict_drift(runs)
    assert len(findings) == 1
    assert findings[0].kind == "verdict_drift"


def test_no_drift_when_verdict_consistent() -> None:
    runs = [_run("r1", "p1", 80, "shortlist"), _run("r1", "p1", 82, "shortlist")]
    assert audit_verdict_drift(runs) == []


def test_no_drift_across_different_profiles() -> None:
    runs = [_run("r1", "p1", 80, "shortlist"), _run("r1", "p2", 20, "auto_reject")]
    assert audit_verdict_drift(runs) == []


def test_missing_citation_flagged() -> None:
    runs = [
        _run("r1", "p1", 80, "shortlist", dims=[{"dimension": "technical", "evidence_refs": []}])
    ]
    findings = audit_missing_citations(runs)
    assert len(findings) == 1
    assert findings[0].kind == "missing_citation"


def test_present_citation_not_flagged() -> None:
    runs = [_run("r1", "p1", 80, "shortlist")]
    assert audit_missing_citations(runs) == []


def test_narrow_score_band_flagged() -> None:
    runs = [_run(f"r{i}", "p1", 50, "hold") for i in range(6)]
    findings = audit_narrow_score_bands(runs)
    assert len(findings) == 1
    assert findings[0].kind == "narrow_score_band"


def test_wide_score_band_not_flagged() -> None:
    scores = [10, 30, 50, 70, 90, 20]
    runs = [_run(f"r{i}", "p1", s, "hold") for i, s in enumerate(scores)]
    assert audit_narrow_score_bands(runs) == []


def test_narrow_band_ignored_below_minimum_run_count() -> None:
    runs = [_run(f"r{i}", "p1", 50, "hold") for i in range(3)]
    assert audit_narrow_score_bands(runs) == []
