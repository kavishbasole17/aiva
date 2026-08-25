from app.questionnaire_service import (
    generate_invite_token,
    hash_token,
    missing_required_answers,
    validate_questions,
)

QUESTIONS = [
    {"id": "auth", "type": "yes_no", "prompt": "Authorized to work?", "required": True},
    {"id": "notice", "type": "short_text", "prompt": "Notice period?", "required": True},
    {"id": "portfolio", "type": "long_text", "prompt": "Describe a project", "required": False},
]


def test_token_roundtrip_and_uniqueness() -> None:
    raw_a, digest_a = generate_invite_token()
    raw_b, digest_b = generate_invite_token()
    assert raw_a != raw_b
    assert digest_a == hash_token(raw_a)
    assert digest_b == hash_token(raw_b)
    assert digest_a != digest_b
    assert len(digest_a) == 64


def test_validate_questions_catches_errors() -> None:
    errors = validate_questions(
        [
            {"id": "ok", "type": "yes_no", "prompt": "Fine?"},
            {"id": "", "type": "rating", "prompt": ""},
            {"id": "dup", "type": "rating", "prompt": "A"},
            {"id": "dup", "type": "rating", "prompt": "B"},
            {"id": "mc", "type": "multiple_choice", "prompt": "Pick", "options": ["one"]},
        ]
    )
    joined = "\n".join(errors)
    assert "duplicate id dup" in joined
    assert "prompt required" in joined
    assert ">=2 options" in joined
    assert any("question[1]" in error for error in errors)


def test_validate_questions_accepts_valid() -> None:
    assert validate_questions(QUESTIONS) == []


def test_missing_required_answers() -> None:
    missing = missing_required_answers(QUESTIONS, {"auth": "yes"})
    assert missing == ["notice"]
    assert missing_required_answers(QUESTIONS, {"auth": "yes", "notice": "  "}) == ["notice"]
    assert missing_required_answers(QUESTIONS, {"auth": "yes", "notice": "30 days"}) == []
