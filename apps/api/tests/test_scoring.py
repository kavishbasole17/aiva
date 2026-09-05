import pytest

from app.scoring import (
    DIMENSION_NAMES,
    DimensionInput,
    WeightProfile,
    assign_verdict,
    compute_total_score,
    run_fingerprint,
    technical_dimension_from_checks,
    validate_profile,
)


def _profile(**overrides: int) -> WeightProfile:
    return WeightProfile(name="default", version=1, weights=dict(DEFAULT_WEIGHTS_SAFE), **overrides)


DEFAULT_WEIGHTS_SAFE = {
    "technical": 30,
    "experience": 20,
    "domain": 15,
    "education": 10,
    "certifications": 10,
    "soft_skills": 10,
    "stability": 5,
}


def _dimensions(technical: int = 80, experience: int = 60) -> list[DimensionInput]:
    return [
        DimensionInput("technical", technical, ("match_checks",), "checks"),
        DimensionInput("experience", experience, ("gateway:v1",), "llm"),
        *[
            DimensionInput(name, 50, ("gateway:v1",), "llm")
            for name in sorted(DIMENSION_NAMES - {"technical", "experience"})
        ],
    ]


def test_validate_profile_rejects_unknown_and_missing() -> None:
    bad = dict(DEFAULT_WEIGHTS_SAFE, blockchain=10)
    with pytest.raises(ValueError, match="Unknown dimensions"):
        validate_profile(bad)
    incomplete = {k: v for k, v in DEFAULT_WEIGHTS_SAFE.items() if k != "stability"}
    with pytest.raises(ValueError, match="Missing dimensions"):
        validate_profile(incomplete)
    with pytest.raises(ValueError, match="non-negative"):
        validate_profile(dict(DEFAULT_WEIGHTS_SAFE, technical=-1))
    with pytest.raises(ValueError, match="one weight must be positive"):
        validate_profile({name: 0 for name in DEFAULT_WEIGHTS_SAFE})
    validate_profile(DEFAULT_WEIGHTS_SAFE)


def test_weights_normalize_to_one() -> None:
    profile = _profile()
    assert abs(sum(profile.normalized().values()) - 1.0) < 1e-9


def test_total_score_matches_hand_calculation() -> None:
    profile = _profile()
    dimensions = [
        DimensionInput("technical", 100, (), ""),
        DimensionInput("experience", 0, (), ""),
        DimensionInput("domain", 100, (), ""),
        DimensionInput("education", 0, (), ""),
        DimensionInput("certifications", 0, (), ""),
        DimensionInput("soft_skills", 0, (), ""),
        DimensionInput("stability", 0, (), ""),
    ]
    expected = round((100 * 30 + 100 * 15) / 100)
    assert compute_total_score(dimensions, profile) == expected
    assert expected == 45


def test_missing_dimension_is_error_not_silent() -> None:
    with pytest.raises(ValueError, match="All weighted dimensions"):
        compute_total_score([DimensionInput("technical", 90, (), "")], _profile())


def test_verdict_bands() -> None:
    profile = _profile()
    assert assign_verdict(29, profile) == "auto_reject"
    assert assign_verdict(30, profile) == "hold"
    assert assign_verdict(49, profile) == "hold"
    assert assign_verdict(50, profile) == "shortlist"
    assert assign_verdict(84, profile) == "shortlist"
    assert assign_verdict(85, profile) == "highly_recommended"


def test_run_fingerprint_deterministic_across_ten_iterations() -> None:
    checks = [
        {
            "check": "required_skill:python",
            "passed": True,
            "detail": "found",
            "evidence_field_names": ["skill"],
        }
    ]
    dimensions = _dimensions()
    profile = _profile()

    fingerprints = {
        run_fingerprint(f"hash-{i % 2}", checks, dimensions, profile) for i in range(10)
    }
    assert len(fingerprints) == 2

    same_input = {run_fingerprint("hash-0", checks, dimensions, profile) for _ in range(10)}
    assert len(same_input) == 1

    perturbed = [
        DimensionInput(
            d.dimension,
            d.score + (1 if d.dimension == "technical" else 0),
            d.evidence_refs,
            d.rationale,
        )
        for d in dimensions
    ]
    assert run_fingerprint("hash-0", checks, perturbed, profile) != next(iter(same_input))


def test_technical_dimension_from_ratio() -> None:
    dimension = technical_dimension_from_checks(0.75)
    assert dimension.score == 75
    assert dimension.dimension == "technical"
