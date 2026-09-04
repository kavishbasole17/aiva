"""Response models form the stable gateway contract.

Every judgement AIVA stores must carry the evidence and versioning fields below,
so a score can always be traced to its source (constraint 8.1).
"""

from typing import Literal

from pydantic import BaseModel, Field


class JudgementBase(BaseModel):
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    cited_span_ids: list[str] = Field(min_length=1)


class DimensionScore(JudgementBase):
    dimension: str = Field(min_length=1)
    score: int = Field(ge=0, le=100)


class ResumeFieldExtraction(BaseModel):
    field_name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class FaqAnswer(JudgementBase):
    answer: str = Field(min_length=1)


class EvaluationSummary(JudgementBase):
    narrative: str = Field(min_length=1)
    strengths: list[str] = Field(min_length=1)
    concerns: list[str] = Field(min_length=1)


class QuestionnaireEvaluation(JudgementBase):
    """AI evaluation of a candidate's questionnaire answers -- was blocked on
    a real AI model being deployed (Milestone 6's own scope note), unblocked
    by ADR-024's switch to the Anthropic API."""

    overall_score: int = Field(ge=0, le=100)
    recommendation: Literal["proceed", "hold", "reject"]
    inconsistencies: list[str] = Field(default_factory=list)
    missing_critical_info: list[str] = Field(default_factory=list)


RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "DimensionScore": DimensionScore,
    "ResumeFieldExtraction": ResumeFieldExtraction,
    "FaqAnswer": FaqAnswer,
    "EvaluationSummary": EvaluationSummary,
    "QuestionnaireEvaluation": QuestionnaireEvaluation,
}


def get_response_model(name: str) -> type[BaseModel]:
    try:
        return RESPONSE_MODELS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown response model: {name}") from exc
