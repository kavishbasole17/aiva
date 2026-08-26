import pytest

from app.evaluation_engine import (
    VERDICT_AUTO_REJECT,
    VERDICT_HIGHLY_RECOMMENDED,
    VERDICT_HOLD,
    VERDICT_SHORTLIST,
    ComponentScore,
    assign_verdict,
    compute_overall,
)


def test_assign_verdict_bands() -> None:
    assert assign_verdict(0) == VERDICT_AUTO_REJECT
    assert assign_verdict(29) == VERDICT_AUTO_REJECT
    assert assign_verdict(30) == VERDICT_HOLD
    assert assign_verdict(49) == VERDICT_HOLD
    assert assign_verdict(50) == VERDICT_SHORTLIST
    assert assign_verdict(84) == VERDICT_SHORTLIST
    assert assign_verdict(85) == VERDICT_HIGHLY_RECOMMENDED
    assert assign_verdict(100) == VERDICT_HIGHLY_RECOMMENDED


def test_compute_overall_all_components_equal_scores_returns_that_score() -> None:
    components = [
        ComponentScore("resume", 70, ""),
        ComponentScore("questionnaire", 70, ""),
        ComponentScore("interview", 70, ""),
        ComponentScore("coding", 70, ""),
    ]
    overall, verdict = compute_overall(components)
    assert overall == 70
    assert verdict == VERDICT_SHORTLIST


def test_compute_overall_renormalizes_over_missing_components() -> None:
    # Only resume (weight 40) and interview (weight 30) present: 70/70 share.
    components = [ComponentScore("resume", 100, ""), ComponentScore("interview", 0, "")]
    overall, _ = compute_overall(components)
    # weighted: (100*40 + 0*30) / 70 = 57.14... -> round to 57
    assert overall == 57


def test_compute_overall_requires_at_least_one_recognized_component() -> None:
    with pytest.raises(ValueError):
        compute_overall([ComponentScore("unknown", 100, "")])


def test_compute_overall_is_deterministic() -> None:
    components = [ComponentScore("resume", 82, ""), ComponentScore("coding", 40, "")]
    first = compute_overall(components)
    second = compute_overall(components)
    assert first == second
