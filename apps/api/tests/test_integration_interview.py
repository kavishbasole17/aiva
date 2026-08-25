import base64
import io
import os
import uuid
import wave

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.main import create_app

pytestmark = pytest.mark.skipif(
    os.environ.get("AIVA_INTEGRATION") != "1",
    reason="integration compose stack not running (set AIVA_INTEGRATION=1)",
)

PASSWORD = "long-enough-password-123"


@pytest.fixture
async def http() -> httpx.AsyncClient:
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def _setup_requisition_with_resume(http: httpx.AsyncClient) -> tuple[dict[str, str], str]:
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"iv-admin-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Interview Org {suffix}",
            "admin_email": admin_email,
            "admin_password": PASSWORD,
        },
    )
    assert org.status_code == 201, org.text
    login = await http.post("/auth/login", json={"email": admin_email, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    organization_id = org.json()["organization_id"]

    dept = await http.post(
        f"/orgs/{organization_id}/departments", json={"name": "Eng"}, headers=headers
    )
    req = await http.post(
        f"/departments/{dept.json()['id']}/requisitions",
        json={"title": "Backend Engineer", "department_id": dept.json()["id"]},
        headers=headers,
    )
    rid = req.json()["id"]

    jd = await http.post(
        f"/requisitions/{rid}/job-description",
        json={
            "title": "Backend Engineer",
            "raw_text": "Build services in python and postgresql with kubernetes.",
            "required_skills": ["python", "postgresql", "kubernetes"],
            "preferred_skills": ["redis"],
            "min_years_experience": 3,
        },
        headers=headers,
    )
    assert jd.status_code == 201, jd.text

    pdf = _minimal_pdf()
    upload = await http.post(
        f"/requisitions/{rid}/resumes",
        files={"file": ("resume.pdf", pdf, "application/pdf")},
        data={},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    return headers, rid


def _minimal_pdf() -> bytes:
    lines = [
        "Jane Candidate",
        "jane.candidate@example.test",
        "+1 555 010 2030",
        "Skills: python, postgresql, docker, sql",
        "8 years of experience across backend teams.",
    ]
    content = (
        "BT /F1 12 Tf 40 750 Td 14 TL\n"
        + "\n".join(f"({line.replace('(', '') .replace(')', '')}) Tj T*" for line in lines)
        + "\nET"
    )
    stream = content.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF"
    ).encode()
    return bytes(out)


def _wav_audio(seconds: float = 1.0, rate: int = 8000) -> str:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        for index in range(int(seconds * rate)):
            handle.writeframes(int(300 * (index % 11)).to_bytes(2, "little"))
    return base64.b64encode(buffer.getvalue()).decode("ascii")


async def test_interview_full_lifecycle_gates_and_loop(http: httpx.AsyncClient) -> None:
    headers, rid = await _setup_requisition_with_resume(http)

    slot_gen = await http.post(
        f"/requisitions/{rid}/slots/generate",
        json={
            "date_from": "2026-09-01",
            "date_to": "2026-09-02",
            "timezone_name": "UTC",
            "local_start": "10:00",
            "local_end": "12:00",
            "duration_minutes": 45,
            "buffer_minutes": 0,
        },
        headers=headers,
    )
    assert slot_gen.status_code == 201, slot_gen.text
    slots = (await http.get(f"/requisitions/{rid}/slots", headers=headers)).json()["slots"]
    assert slots, "expected generated slots"

    booked = await http.post(
        f"/slots/{slots[0]['id']}/book",
        json={"candidate_email": "jane.candidate@example.test"},
        headers=headers,
    )
    assert booked.status_code == 200, booked.text

    created = await http.post(
        f"/slots/{slots[0]['id']}/interview-session",
        json={},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    token = body["token"]
    session_id = body["id"]
    assert len(token) >= 32
    assert body["topic_count"] >= 1

    # Unknown tokens 404; booking an unbooked slot is rejected earlier.
    missing = await http.get(f"/public/interview-sessions/{uuid.uuid4().hex}")
    assert missing.status_code == 404

    state = await http.get(f"/public/interview-sessions/{token}")
    assert state.status_code == 200
    snapshot = state.json()
    assert snapshot["status"] == "pending_consent"
    assert snapshot["consent"]["required"] is True
    consent_version = snapshot["consent"]["version"]

    # Fail-closed gates before consent.
    early_start = await http.post(f"/public/interview-sessions/{token}/start")
    assert early_start.status_code == 409
    early_precheck = await http.post(
        f"/public/interview-sessions/{token}/precheck",
        json={
            "suite_version": snapshot["precheck"]["suite_version"],
            "devices": [{"kind": "camera", "status": "ok"}],
            "connection": "good",
            "bandwidth_kbps": 1000,
        },
    )
    assert early_precheck.status_code == 409

    # Stale consent version is rejected even when granted.
    stale = await http.post(
        f"/public/interview-sessions/{token}/consent",
        json={"accepted_version": "1999.01-v1", "granted": True},
    )
    assert stale.status_code == 400

    granted = await http.post(
        f"/public/interview-sessions/{token}/consent",
        json={"accepted_version": consent_version, "granted": True},
    )
    assert granted.status_code == 200, granted.text
    assert granted.json()["status"] == "consent_granted"

    # Failing pre-check must not unlock the start gate.
    failed_precheck = await http.post(
        f"/public/interview-sessions/{token}/precheck",
        json={
            "suite_version": snapshot["precheck"]["suite_version"],
            "devices": [
                {"kind": "camera", "status": "ok"},
                {"kind": "microphone", "status": "failed"},
                {"kind": "speaker", "status": "ok"},
            ],
            "connection": "good",
            "bandwidth_kbps": 1000,
        },
    )
    assert failed_precheck.status_code == 200
    assert failed_precheck.json()["passed"] is False
    assert any("microphone" in failure for failure in failed_precheck.json()["failures"])

    blocked = await http.post(f"/public/interview-sessions/{token}/start")
    assert blocked.status_code == 409

    passing_report = {
        "suite_version": snapshot["precheck"]["suite_version"],
        "devices": [
            {"kind": "camera", "status": "ok"},
            {"kind": "microphone", "status": "ok"},
            {"kind": "speaker", "status": "ok"},
        ],
        "connection": "good",
        "bandwidth_kbps": 1500,
        "browser": "pytest-agent",
    }
    passed = await http.post(f"/public/interview-sessions/{token}/precheck", json=passing_report)
    assert passed.status_code == 200
    assert passed.json()["passed"] is True

    started = await http.post(f"/public/interview-sessions/{token}/start")
    assert started.status_code == 200, started.text
    started_body = started.json()
    assert started_body["status"] == "active"
    question = started_body["question"]
    assert question["text"]
    assert question["tts_text"]
    total_topics = int(started_body["progress_total"])

    # TTS proxy returns deterministic WAV audio for the spoken question.
    spoken = await http.post(
        f"/public/interview-sessions/{token}/tts",
        json={"text": question["tts_text"]},
    )
    assert spoken.status_code == 200, spoken.text
    assert spoken.json()["format"] == "wav"

    # Drive turns until the engine closes the loop; audio path exercised once.
    completed = False
    for turn_index in range(total_topics * 3):
        if turn_index == 0:
            answer_payload = {"audio_b64": _wav_audio()}
        else:
            answer_payload = {"answer_text": "led designed shipped owned everything end to end"}
        answered = await http.post(f"/public/interview-sessions/{token}/turns", json=answer_payload)
        assert answered.status_code == 200, answered.text
        turn_body = answered.json()
        if turn_index == 0:
            assert turn_body["stt"] is not None
            assert turn_body["stt"]["model_id"].startswith("aiva-mock")
            assert turn_body["transcript"]["text"]
        if turn_body["completed"]:
            assert turn_body["next"]["kind"] == "closing"
            completed = True
            break
        assert turn_body["status"] == "active"
        assert turn_body["next"]["text"]
    assert completed, "engine must close within budget"

    final_state = (await http.get(f"/public/interview-sessions/{token}")).json()
    assert final_state["status"] == "completed"
    assert final_state["open_question"] is None

    # Terminal session rejects further mutations.
    after = await http.post(
        f"/public/interview-sessions/{token}/turns", json={"answer_text": "late"}
    )
    assert after.status_code == 409

    detail = await http.get(f"/interview-sessions/{session_id}", headers=headers)
    assert detail.status_code == 200
    turns = detail.json()["turns"]
    assert turns[-1]["kind"] == "closing"
    first_answer = next(t for t in turns if t["sequence"] == 0)
    assert first_answer["answer_text"], "STT transcript persisted on first turn"
    assert first_answer["stt_model_id"]
    consents = detail.json()["consents"]
    assert consents and consents[0]["granted"] is True

    listed = await http.get(f"/requisitions/{rid}/interview-sessions", headers=headers)
    assert listed.status_code == 200
    summaries = listed.json()["sessions"]
    assert any(s["id"] == session_id for s in summaries)


async def test_consent_denied_is_terminal(http: httpx.AsyncClient) -> None:
    headers, rid = await _setup_requisition_with_resume(http)
    slot_gen = await http.post(
        f"/requisitions/{rid}/slots/generate",
        json={
            "date_from": "2026-09-01",
            "date_to": "2026-09-02",
            "timezone_name": "UTC",
            "local_start": "10:00",
            "local_end": "12:00",
            "duration_minutes": 45,
            "buffer_minutes": 0,
        },
        headers=headers,
    )
    assert slot_gen.status_code == 201, slot_gen.text
    slots = (await http.get(f"/requisitions/{rid}/slots", headers=headers)).json()["slots"]
    assert len(slots) >= 2, "expected at least two generated slots"
    await http.post(
        f"/slots/{slots[1]['id']}/book",
        json={"candidate_email": "decliner@example.test"},
        headers=headers,
    )
    created = await http.post(
        f"/slots/{slots[1]['id']}/interview-session", json={}, headers=headers
    )
    token = created.json()["token"]
    state = await http.get(f"/public/interview-sessions/{token}")
    version = state.json()["consent"]["version"]

    denied = await http.post(
        f"/public/interview-sessions/{token}/consent",
        json={"accepted_version": version, "granted": False},
    )
    assert denied.status_code == 200
    assert denied.json()["status"] == "declined"

    precheck_after = await http.post(
        f"/public/interview-sessions/{token}/precheck",
        json={
            "suite_version": state.json()["precheck"]["suite_version"],
            "devices": [
                {"kind": "camera", "status": "ok"},
                {"kind": "microphone", "status": "ok"},
                {"kind": "speaker", "status": "ok"},
            ],
            "connection": "good",
            "bandwidth_kbps": 900,
        },
    )
    assert precheck_after.status_code == 409
