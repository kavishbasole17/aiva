"""Deterministic aggregation of resume/questionnaire/interview/coding-task
signals into one evaluation.

Mirrors scoring.py's discipline: arithmetic and threshold comparisons only
ever happen in this module. The gateway-backed narrative
(`evaluation_summary` prompt) only ever explains the verdict already
computed here — it is never allowed to produce a different one, same
"LLM never performs arithmetic" rule scoring.py already established.
"""

from dataclasses import dataclass

VERDICT_AUTO_REJECT = "auto_reject"
VERDICT_HOLD = "hold"
VERDICT_SHORTLIST = "shortlist"
VERDICT_HIGHLY_RECOMMENDED = "highly_recommended"

# Renormalized over whichever components are actually available for a given
# candidate (e.g. no coding task assigned => that weight simply drops out),
# same "normalized shares" approach as scoring.WeightProfile.
DEFAULT_COMPONENT_WEIGHTS: dict[str, int] = {
    "resume": 40,
    "questionnaire": 15,
    "interview": 30,
    "coding": 15,
}

AUTO_REJECT_BELOW = 30
HOLD_BELOW = 50
HIGHLY_RECOMMENDED_AT = 85


@dataclass(frozen=True)
class ComponentScore:
    name: str
    score: int  # 0-100
    detail: str


def assign_verdict(overall: int) -> str:
    if overall < AUTO_REJECT_BELOW:
        return VERDICT_AUTO_REJECT
    if overall < HOLD_BELOW:
        return VERDICT_HOLD
    if overall >= HIGHLY_RECOMMENDED_AT:
        return VERDICT_HIGHLY_RECOMMENDED
    return VERDICT_SHORTLIST


def compute_overall(components: list[ComponentScore]) -> tuple[int, str]:
    """Weighted average over available components only; unrecognized
    component names contribute zero weight rather than erroring, so callers
    can pass forward-compatible extra components without breaking this."""
    weighted_total = 0.0
    total_weight = 0
    for component in components:
        weight = DEFAULT_COMPONENT_WEIGHTS.get(component.name, 0)
        weighted_total += component.score * weight
        total_weight += weight
    if total_weight <= 0:
        raise ValueError("At least one recognized component with positive weight is required")
    overall = round(weighted_total / total_weight)
    return overall, assign_verdict(overall)


__all__ = [
    "AUTO_REJECT_BELOW",
    "DEFAULT_COMPONENT_WEIGHTS",
    "HIGHLY_RECOMMENDED_AT",
    "HOLD_BELOW",
    "VERDICT_AUTO_REJECT",
    "VERDICT_HIGHLY_RECOMMENDED",
    "VERDICT_HOLD",
    "VERDICT_SHORTLIST",
    "ComponentScore",
    "assign_verdict",
    "compute_overall",
]
