import os
import uuid

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
        + "\n".join(f"({line.replace('(', '').replace(')', '')}) Tj T*" for line in lines)
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


async def _active_session(http: httpx.AsyncClient) -> tuple[dict[str, str], str, str]:
    """Bootstraps org -> requisition -> slot -> booked interview session,
    then drives the candidate side through consent + pre-check + start so it
    lands in ACTIVE. Returns (staff headers, session_id, candidate token).
    """
    suffix = uuid.uuid4().hex[:8]
    admin_email = f"ws-admin-{suffix}@example.test"
    org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Workspace Org {suffix}",
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
            "raw_text": "Build services in python.",
            "required_skills": ["python"],
            "preferred_skills": [],
            "min_years_experience": 1,
        },
        headers=headers,
    )
    assert jd.status_code == 201, jd.text
    upload = await http.post(
        f"/requisitions/{rid}/resumes",
        files={"file": ("resume.pdf", _minimal_pdf(), "application/pdf")},
        data={},
        headers=headers,
    )
    assert upload.status_code == 201, upload.text

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
    booked = await http.post(
        f"/slots/{slots[0]['id']}/book",
        json={"candidate_email": "jane.candidate@example.test"},
        headers=headers,
    )
    assert booked.status_code == 200, booked.text
    created = await http.post(
        f"/slots/{slots[0]['id']}/interview-session", json={}, headers=headers
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    session_id = created.json()["id"]

    state = await http.get(f"/public/interview-sessions/{token}")
    consent_version = state.json()["consent"]["version"]
    granted = await http.post(
        f"/public/interview-sessions/{token}/consent",
        json={"accepted_version": consent_version, "granted": True},
    )
    assert granted.status_code == 200, granted.text
    passing_report = {
        "suite_version": state.json()["precheck"]["suite_version"],
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
    assert passed.status_code == 200 and passed.json()["passed"] is True
    started = await http.post(f"/public/interview-sessions/{token}/start")
    assert started.status_code == 200, started.text

    return headers, session_id, token


async def test_workspace_lifecycle(http: httpx.AsyncClient) -> None:
    headers, session_id, token = await _active_session(http)

    # Staff creates a coding task; its starter code is immediately readable
    # from both sides.
    created = await http.post(
        f"/interview-sessions/{session_id}/coding-tasks",
        json={
            "title": "Two Sum",
            "prompt": "Return indices of the two numbers that add to target.",
            "starter_code": "def two_sum(nums, target):\n    pass\n",
            "language": "python",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    staff_code = await http.get(
        f"/interview-sessions/{session_id}/coding-tasks/{task_id}/code", headers=headers
    )
    assert staff_code.status_code == 200
    assert "two_sum" in staff_code.json()["source"]

    candidate_tasks = await http.get(f"/public/interview-sessions/{token}/coding-tasks")
    assert candidate_tasks.status_code == 200
    assert candidate_tasks.json()["tasks"][0]["id"] == task_id

    # Candidate autosaves an edit; staff can immediately see it (live poll).
    saved = await http.post(
        f"/public/interview-sessions/{token}/coding-tasks/{task_id}/code",
        json={"source": "def two_sum(nums, target):\n    return [0, 1]\n"},
    )
    assert saved.status_code == 201, saved.text
    staff_after_save = await http.get(
        f"/interview-sessions/{session_id}/coding-tasks/{task_id}/code", headers=headers
    )
    assert "[0, 1]" in staff_after_save.json()["source"]

    # Candidate runs code through the sandbox; the execution is persisted
    # and visible to staff.
    run = await http.post(
        f"/public/interview-sessions/{token}/coding-tasks/{task_id}/run",
        json={"source": "print(sum([1, 2, 3]))", "stdin": ""},
    )
    assert run.status_code == 200, run.text
    run_body = run.json()
    assert run_body["stdout"].strip() == "6"
    assert run_body["exit_code"] == 0
    assert run_body["timed_out"] is False

    executions = await http.get(
        f"/interview-sessions/{session_id}/coding-tasks/{task_id}/executions", headers=headers
    )
    assert executions.status_code == 200
    assert executions.json()["executions"][0]["stdout"].strip() == "6"

    # Whiteboard: both sides can draw, both sides see the combined log.
    candidate_stroke = await http.post(
        f"/public/interview-sessions/{token}/whiteboard",
        json={"stroke_payload": {"points": [[0, 0], [1, 1]], "color": "#000", "tool": "pen"}},
    )
    assert candidate_stroke.status_code == 201, candidate_stroke.text
    staff_stroke = await http.post(
        f"/interview-sessions/{session_id}/whiteboard",
        json={"stroke_payload": {"points": [[2, 2]], "color": "#f00", "tool": "pen"}},
        headers=headers,
    )
    assert staff_stroke.status_code == 201, staff_stroke.text
    board = await http.get(f"/public/interview-sessions/{token}/whiteboard")
    authors = {s["author"] for s in board.json()["strokes"]}
    assert authors == {"candidate", "interviewer"}

    # Discussion: both sides can post, both sides read the same thread.
    await http.post(
        f"/public/interview-sessions/{token}/discussion", json={"body": "should I use a hashmap?"}
    )
    await http.post(
        f"/interview-sessions/{session_id}/discussion",
        json={"body": "good instinct, try it"},
        headers=headers,
    )
    thread = await http.get(f"/interview-sessions/{session_id}/discussion", headers=headers)
    bodies = [m["body"] for m in thread.json()["messages"]]
    assert "should I use a hashmap?" in bodies
    assert "good instinct, try it" in bodies

    # Screen share has a stable interface but no backend yet.
    screen_share = await http.post(f"/public/interview-sessions/{token}/screen-share/token")
    assert screen_share.status_code == 501

    # A different org's staff cannot see this session or its workspace.
    other_admin = f"ws-outsider-{uuid.uuid4().hex[:8]}@example.test"
    other_org = await http.post(
        "/auth/register-org",
        json={
            "organization_name": f"Other Org {uuid.uuid4().hex[:8]}",
            "admin_email": other_admin,
            "admin_password": PASSWORD,
        },
    )
    other_login = await http.post("/auth/login", json={"email": other_admin, "password": PASSWORD})
    other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
    assert other_org.status_code == 201
    leaked = await http.get(f"/interview-sessions/{session_id}/coding-tasks", headers=other_headers)
    assert leaked.status_code == 404

    # Ending the interview closes candidate write access to the workspace.
    finished = await http.post(f"/public/interview-sessions/{token}/finish")
    assert finished.status_code == 200
    blocked_save = await http.post(
        f"/public/interview-sessions/{token}/coding-tasks/{task_id}/code",
        json={"source": "print('too late')"},
    )
    assert blocked_save.status_code == 409
    blocked_run = await http.post(
        f"/public/interview-sessions/{token}/coding-tasks/{task_id}/run",
        json={"source": "print('too late')"},
    )
    assert blocked_run.status_code == 409


async def test_unsupported_language_rejected(http: httpx.AsyncClient) -> None:
    headers, session_id, _token = await _active_session(http)
    rejected = await http.post(
        f"/interview-sessions/{session_id}/coding-tasks",
        json={"title": "x", "prompt": "y", "starter_code": "", "language": "cobol"},
        headers=headers,
    )
    assert rejected.status_code == 400
