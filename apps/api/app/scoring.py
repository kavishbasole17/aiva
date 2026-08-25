"""Versioned weight-profile scoring.

Deterministic: identical dimension inputs + profile produce byte-identical runs.
The LLM never performs arithmetic or threshold comparisons; it only produces
qualitative dimension judgements, each of which must cite evidence.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

DEFAULT_WEIGHTS = {
    "technical": 30,
    "experience": 20,
    "domain": 15,
    "education": 10,
    "certifications": 10,
    "soft_skills": 10,
    "stability": 5,
}

DIMENSION_NAMES = frozenset(DEFAULT_WEIGHTS.keys())

VERDICT_AUTO_REJECT = "auto_reject"
VERDICT_HOLD = "hold"
VERDICT_SHORTLIST = "shortlist"
VERDICT_HIGHLY_RECOMMENDED = "highly_recommended"


@dataclass(frozen=True)
class WeightProfile:
    name: str
    version: int
    weights: dict[str, int]
    auto_reject_below: int = 30
    hold_below: int = 50
    highly_recommended_at: int = 85

    def normalized(self) -> dict[str, float]:
        total = sum(self.weights.values())
        if total <= 0:
            raise ValueError("Weight sum must be positive")
        return {name: weight / total for name, weight in self.weights.items()}

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "name": self.name,
                "version": self.version,
                "weights": dict(sorted(self.weights.items())),
                "auto_reject_below": self.auto_reject_below,
                "hold_below": self.hold_below,
                "highly_recommended_at": self.highly_recommended_at,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class DimensionInput:
    """One judged dimension. `score` comes from the gateway (LLM judgement with
    cited evidence) or from deterministic match ratios; never from arithmetic
    performed here on other scores."""

    dimension: str
    score: int
    evidence_refs: tuple[str, ...]
    rationale: str


def validate_profile(weights: dict[str, int]) -> None:
    unknown = set(weights) - DIMENSION_NAMES
    if unknown:
        raise ValueError(f"Unknown dimensions: {sorted(unknown)}")
    missing = DIMENSION_NAMES - set(weights)
    if missing:
        raise ValueError(f"Missing dimensions: {sorted(missing)}")
    for name, weight in weights.items():
        if not isinstance(weight, int) or weight < 0:
            raise ValueError(f"Weight for {name} must be a non-negative integer")


def compute_total_score(dimensions: list[DimensionInput], profile: WeightProfile) -> int:
    normalized = profile.normalized()
    by_name = {d.dimension: d for d in dimensions}
    total = 0.0
    covered = 0.0
    for name, share in normalized.items():
        dimension = by_name.get(name)
        if dimension is None:
            continue
        total += dimension.score * share
        covered += share
    if covered < 0.999:
        raise ValueError("All weighted dimensions must be provided")
    return round(total)


def assign_verdict(total: int, profile: WeightProfile) -> str:
    if total < profile.auto_reject_below:
        return VERDICT_AUTO_REJECT
    if total < profile.hold_below:
        return VERDICT_HOLD
    if total >= profile.highly_recommended_at:
        return VERDICT_HIGHLY_RECOMMENDED
    return VERDICT_SHORTLIST


def run_fingerprint(
    resume_hash: str,
    requirements_payload: list[dict[str, Any]],
    dimensions: list[DimensionInput],
    profile: WeightProfile,
) -> str:
    canonical = json.dumps(
        {
            "resume_hash": resume_hash,
            "checks": requirements_payload,
            "dimensions": [
                {"dimension": d.dimension, "score": d.score, "evidence": list(d.evidence_refs)}
                for d in sorted(dimensions, key=lambda d: d.dimension)
            ],
            "profile": profile.fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def technical_dimension_from_checks(match_ratio_value: float) -> DimensionInput:
    score = round(match_ratio_value * 100)
    return DimensionInput(
        dimension="technical",
        score=score,
        evidence_refs=("match_checks",),
        rationale=f"{round(match_ratio_value * 100)}% of deterministic requirement checks passed",
    )
