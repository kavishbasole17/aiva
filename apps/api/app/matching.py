"""Deterministic matching checks — computed in code, never by the LLM.

These are objective, candidate-stated facts: skill presence (lexical), stated
years of experience vs. requirement, boolean must-haves. Results feed scoring
as evidence-linked dimension inputs.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol


class FieldLike(Protocol):
    field_name: str
    value: str


@dataclass(frozen=True)
class JobRequirements:
    required_skills: frozenset[str]
    preferred_skills: frozenset[str]
    min_years_experience: int


@dataclass(frozen=True)
class MatchCheck:
    check: str
    passed: bool
    detail: str
    evidence_field_names: tuple[str, ...]


def skills_present(fields: Sequence[FieldLike]) -> set[str]:
    return {f.value.lower() for f in fields if f.field_name == "skill"}


def stated_years(fields: Sequence[FieldLike]) -> int | None:
    claims = [int(f.value) for f in fields if f.field_name == "years_experience_claimed"]
    return max(claims) if claims else None


def run_match_checks(
    fields: Sequence[FieldLike],
    requirements: JobRequirements,
) -> list[MatchCheck]:
    checks: list[MatchCheck] = []
    present = skills_present(fields)

    for skill in sorted(requirements.required_skills):
        normalized = skill.lower()
        checks.append(
            MatchCheck(
                check=f"required_skill:{normalized}",
                passed=normalized in present,
                detail=f"{'found' if normalized in present else 'not found'} in resume",
                evidence_field_names=("skill",) if normalized in present else (),
            )
        )

    preferred_hits = sorted(present & requirements.preferred_skills)
    coverage = f"{len(preferred_hits)}/{len(requirements.preferred_skills)} preferred skills"
    suffix = f": {', '.join(preferred_hits)}" if preferred_hits else ""
    checks.append(
        MatchCheck(
            check="preferred_skills_coverage",
            passed=bool(preferred_hits),
            detail=f"{coverage} matched{suffix}",
            evidence_field_names=("skill",),
        )
    )

    claimed = stated_years(fields)
    checks.append(
        MatchCheck(
            check="min_years_experience",
            passed=claimed is not None and claimed >= requirements.min_years_experience,
            detail=(
                f"stated {claimed} years vs. required {requirements.min_years_experience}"
                if claimed is not None
                else "no explicit years-of-experience statement found"
            ),
            evidence_field_names=("years_experience_claimed",),
        )
    )
    return checks


def match_ratio(checks: list[MatchCheck]) -> float:
    if not checks:
        return 0.0
    return sum(1 for c in checks if c.passed) / len(checks)


def to_payload(checks: list[MatchCheck]) -> list[dict[str, Any]]:
    return [
        {
            "check": c.check,
            "passed": c.passed,
            "detail": c.detail,
            "evidence_field_names": list(c.evidence_field_names),
        }
        for c in checks
    ]
