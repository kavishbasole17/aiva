import hashlib
import re
import secrets
from typing import Any

QUESTION_TYPES = frozenset(
    {"multiple_choice", "yes_no", "rating", "long_text", "short_text", "file_upload"}
)

TOKEN_BYTES = 32


def generate_invite_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(TOKEN_BYTES)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, digest


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


QUESTION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_questions(questions: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, question in enumerate(questions):
        label = f"question[{index}]"
        question_id = question.get("id")
        valid_id = isinstance(question_id, str) and bool(QUESTION_ID_RE.match(question_id))
        if not valid_id:
            errors.append(f"{label}: id must match {QUESTION_ID_RE.pattern}")
        elif question_id in seen_ids:
            errors.append(f"{label}: duplicate id {question_id}")
            seen_ids.add(str(question_id))
        else:
            seen_ids.add(str(question_id))
        if not isinstance(question.get("prompt"), str) or not question["prompt"].strip():
            errors.append(f"{label}: prompt required")
        if question.get("type") not in QUESTION_TYPES:
            errors.append(f"{label}: type must be one of {sorted(QUESTION_TYPES)}")
        if (
            question["type"] == "multiple_choice"
            if isinstance(question.get("type"), str)
            else False
        ):
            options = question.get("options")
            if not isinstance(options, list) or len(options) < 2:
                errors.append(f"{label}: multiple_choice requires >=2 options")
    return errors


def missing_required_answers(
    questions: list[dict[str, Any]],
    answers: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    for question in questions:
        if not question.get("required"):
            continue
        question_id = str(question.get("id"))
        value = answers.get(question_id)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(question_id)
    return missing
