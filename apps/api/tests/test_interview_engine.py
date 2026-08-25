from app.interview_engine import (
    TurnKind,
    build_plan,
    decide,
)

PLAN = build_plan(
    requisition_id="req-1",
    role_title="Backend Engineer",
    required_skills=["python", "postgres", "kubernetes"],
    missing_skills=["kubernetes"],
    min_years_experience=3,
    stated_years=5,
)


def test_plan_is_deterministic_and_seeded_by_gaps() -> None:
    again = build_plan(
        requisition_id="req-1",
        role_title="Backend Engineer",
        required_skills=["python", "postgres", "kubernetes"],
        missing_skills=["kubernetes"],
        min_years_experience=3,
        stated_years=5,
    )
    assert again.model_dump() == PLAN.model_dump()
    assert len(again.plan_fingerprint) == 64
    topic_ids = [t.id for t in again.topics]
    assert "required_gap" in topic_ids
    assert "strength_probe" in topic_ids
    assert "experience_depth" in topic_ids
    assert topic_ids[-1] == "candidate_questions"


def test_first_turn_is_opening_question() -> None:
    decision = decide(PLAN, [], "")
    assert decision.kind == TurnKind.QUESTION
    assert decision.topic_index == 0
    assert decision.tts_text


def test_thick_answer_advances_thin_answer_probes() -> None:
    thick = "I led our kubernetes migration myself and designed the cluster layout."
    advance = decide(PLAN, [("question", "required_gap")], thick)
    assert advance.kind == TurnKind.QUESTION
    assert advance.topic_index == 1

    thin = "I have used it a bit here and there recently maybe."
    probe = decide(PLAN, [("question", "required_gap")], thin)
    assert probe.kind == TurnKind.PROBE
    assert probe.topic_id == "required_gap"
    assert probe.probes_used == 1

    after_probe = decide(PLAN, [("question", "required_gap"), ("probe", "required_gap")], thin)
    assert after_probe.kind == TurnKind.QUESTION
    assert after_probe.topic_index == 1


def test_single_point_topic_advances_only_when_point_is_covered() -> None:
    gap_topic = next(t for t in PLAN.topics if t.id == "required_gap")
    assert len(gap_topic.expected_points) == 1
    covering = f"I ran {gap_topic.expected_points[0]} in production myself."
    assert decide(PLAN, [("question", "required_gap")], covering).kind == TurnKind.QUESTION
    assert decide(PLAN, [("question", "required_gap")], "nothing relevant here").kind == (
        TurnKind.PROBE
    )


def test_loop_closes_after_final_topic() -> None:
    asked: list[tuple[str, str]] = []
    answer = ""
    closing_seen = False
    for _ in range(20):
        decision = decide(PLAN, asked, answer)
        if decision.kind == TurnKind.CLOSING:
            closing_seen = True
            break
        asked.append((decision.kind.value, decision.topic_id or ""))
        answer = (
            "led owned designed shipped everything thoroughly"
            if (decision.topic_id == "experience_depth")
            else f"covering {decision.topic_id} with detail"
        )
        if decision.topic_id:
            topic = next(t for t in PLAN.topics if t.id == decision.topic_id)
            answer += " " + " ".join(topic.expected_points)
    assert closing_seen, "loop must terminate"


def test_replay_yields_identical_sequence() -> None:
    def replay() -> list[str]:
        asked: list[tuple[str, str]] = []
        sequence: list[str] = []
        answer = ""
        for _ in range(20):
            decision = decide(PLAN, asked, answer)
            sequence.append(f"{decision.kind.value}:{decision.topic_id}")
            if decision.kind == TurnKind.CLOSING:
                break
            asked.append((decision.kind.value, decision.topic_id or ""))
            answer = "thin but honest attempt at an answer"
        return sequence

    assert replay() == replay()


def test_unknown_topic_id_closes_safe() -> None:
    decision = decide(PLAN, [("question", "bogus-topic")], "anything")
    assert decision.kind == TurnKind.CLOSING


def test_topics_without_expected_points_always_advance() -> None:
    decision = decide(PLAN, [("question", "candidate_questions")], "just a question please")
    assert decision.kind == TurnKind.QUESTION or decision.kind == TurnKind.CLOSING
