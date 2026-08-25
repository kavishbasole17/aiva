"""Adaptive interview loop engine — pure logic, no I/O.

Builds a deterministic question plan from objective signals already computed
by earlier milestones (match checks from ``matching.py``, extracted resume
claims) and drives the live conversation through it. Adaptivity is explicit
and auditable rather than left to model whim:

- an answer covering enough of a topic's expected points advances,
- a thin answer spends that topic's single scripted probe budget first,
- after the final topic the loop closes and stops generating turns.

The LLM's role stays where M3 put it (qualitative judgement with citations);
the loop itself — what to ask next, when to follow up, when to stop — is
plain code so any transcript can be replayed to the same outcome.

``tts_text`` on every decision is exactly what the speech layer should read
aloud, keeping the STT/TTS contract symmetric.
"""

import hashlib
from enum import StrEnum

from pydantic import BaseModel, Field

ANSWER_COVERAGE_THRESHOLD = 0.5
MAX_PROBES_PER_TOPIC = 1


class TurnKind(StrEnum):
    QUESTION = "question"
    PROBE = "probe"
    CLOSING = "closing"


class Topic(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1)
    tts_text: str = Field(min_length=1)
    expected_points: list[str] = Field(default_factory=list)
    probe_prompt: str = Field(default="", max_length=500)
    basis: str = Field(default="", max_length=64)


class InterviewPlan(BaseModel):
    requisition_id: str = Field(min_length=1)
    topics: list[Topic] = Field(min_length=1)
    plan_fingerprint: str = Field(min_length=64, max_length=64)


class EngineDecision(BaseModel):
    kind: TurnKind
    topic_id: str | None
    prompt: str
    tts_text: str
    topic_index: int
    progress_total: int = Field(ge=1)
    probes_used: int = Field(ge=0)


def _fingerprint(requisition_id: str, topics: list[Topic]) -> str:
    canonical = repr([(t.id, t.prompt, t.probe_prompt, tuple(t.expected_points)) for t in topics])
    return hashlib.sha256(f"{requisition_id}:{canonical}".encode()).hexdigest()


def build_plan(
    requisition_id: str,
    role_title: str,
    required_skills: list[str],
    missing_skills: list[str],
    min_years_experience: int,
    stated_years: int | None,
) -> InterviewPlan:
    """Deterministic plan seeded by objective gaps between JD and resume."""
    del role_title  # reserved for prompt phrasing variants; keeps call sites stable
    topics: list[Topic] = []

    probed_skills = missing_skills[:3]
    if probed_skills:
        listing = ", ".join(probed_skills)
        topics.append(
            Topic(
                id="required_gap",
                prompt=(
                    f"The role requires hands-on experience with {listing}. "
                    "Walk me through your exposure to each of them."
                ),
                tts_text=(
                    "Let's start technical. This role requires hands-on experience "
                    f"with {listing}. Please walk me through your exposure to each."
                ),
                expected_points=[skill.lower() for skill in probed_skills],
                probe_prompt=(
                    "Could you go deeper on which parts you built yourself versus "
                    "only worked alongside?"
                ),
                basis="match_checks",
            )
        )

    verified_skills = [s for s in required_skills if s not in missing_skills][:2]
    if verified_skills:
        listing = ", ".join(verified_skills)
        topics.append(
            Topic(
                id="strength_probe",
                prompt=(
                    f"Your background shows {listing}. Describe the project where "
                    "you used them most heavily and the outcome."
                ),
                tts_text=(
                    f"I can see {listing} on your resume. Describe the project where you "
                    "used them most heavily, and how it turned out."
                ),
                expected_points=[skill.lower() for skill in verified_skills],
                probe_prompt="What was your specific contribution measured against the team's?",
                basis="resume_claims",
            )
        )

    if min_years_experience > 0:
        stated_note = (
            f"You listed about {stated_years} years"
            if stated_years is not None
            else "Your resume shows several years"
        )
        topics.append(
            Topic(
                id="experience_depth",
                prompt=(
                    f"{stated_note} of experience and this role needs at least "
                    f"{min_years_experience}. Tell me about the work you'd count as most senior."
                ),
                tts_text=(
                    f"This position asks for at least {min_years_experience} years of relevant "
                    "experience. Tell me about the work you consider your most senior."
                ),
                expected_points=["led", "owned", "designed", "shipped"],
                probe_prompt="How large was the scope — team size, users, or revenue touched?",
                basis="years_claim",
            )
        )

    topics.append(
        Topic(
            id="candidate_questions",
            prompt=(
                "Finally — what would you want to know about the team or the role? "
                "Anything you'd like to add that we haven't covered."
            ),
            tts_text=(
                "We're nearly done. What would you like to know about the team or the "
                "role, or anything else you'd like to add?"
            ),
            expected_points=[],
            probe_prompt="",
            basis="standard",
        )
    )

    return InterviewPlan(
        requisition_id=requisition_id,
        topics=topics,
        plan_fingerprint=_fingerprint(requisition_id, topics),
    )


def _coverage(answer: str, expected_points: list[str]) -> float:
    if not expected_points:
        return 1.0
    lowered = answer.lower()
    hits = sum(1 for point in expected_points if point in lowered)
    return hits / len(expected_points)


def _question_for(plan: InterviewPlan, index: int) -> EngineDecision:
    topic = plan.topics[index]
    return EngineDecision(
        kind=TurnKind.QUESTION,
        topic_id=topic.id,
        prompt=topic.prompt,
        tts_text=topic.tts_text,
        topic_index=index,
        progress_total=len(plan.topics),
        probes_used=0,
    )


def _closing(plan: InterviewPlan) -> EngineDecision:
    return EngineDecision(
        kind=TurnKind.CLOSING,
        topic_id=None,
        prompt=(
            "Thank you — that completes the structured portion of your interview. "
            "You may close the window now."
        ),
        tts_text=(
            "Thank you, that completes the structured portion of your interview. "
            "You can close the window now."
        ),
        topic_index=-1,
        progress_total=len(plan.topics),
        probes_used=0,
    )


def decide(
    plan: InterviewPlan,
    asked: list[tuple[str, str]],
    current_answer: str,
) -> EngineDecision:
    """Score the just-given answer for the open question, then pick the next turn.

    ``asked`` is the ordered [(turn_kind, topic_id)] history of questions and
    probes already emitted. The result is a pure function of the plan, that
    history, and the current answer — replaying the same transcript always
    produces the same sequence.
    """
    if not asked:
        return _question_for(plan, 0)

    last_kind, last_topic_id = asked[-1]
    index = next((i for i, t in enumerate(plan.topics) if t.id == last_topic_id), None)
    if index is None:
        return _closing(plan)
    if last_kind == TurnKind.PROBE.value:
        nxt = index + 1
        return _closing(plan) if nxt >= len(plan.topics) else _question_for(plan, nxt)

    topic = plan.topics[index]
    probes_so_far = sum(
        1 for kind, tid in asked if kind == TurnKind.PROBE.value and tid == topic.id
    )
    covered_enough = _coverage(current_answer, topic.expected_points) >= ANSWER_COVERAGE_THRESHOLD
    if not covered_enough and probes_so_far < MAX_PROBES_PER_TOPIC and topic.probe_prompt:
        return EngineDecision(
            kind=TurnKind.PROBE,
            topic_id=topic.id,
            prompt=topic.probe_prompt,
            tts_text=topic.probe_prompt,
            topic_index=index,
            progress_total=len(plan.topics),
            probes_used=probes_so_far + 1,
        )

    nxt = index + 1
    return _closing(plan) if nxt >= len(plan.topics) else _question_for(plan, nxt)


__all__ = [
    "ANSWER_COVERAGE_THRESHOLD",
    "EngineDecision",
    "InterviewPlan",
    "MAX_PROBES_PER_TOPIC",
    "Topic",
    "TurnKind",
    "build_plan",
    "decide",
]
