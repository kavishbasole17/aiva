from app.precheck import (
    PRECHECK_SUITE_VERSION,
    DeviceCheck,
    PreCheckReport,
    evaluate_precheck,
)


def _report(**overrides: object) -> PreCheckReport:
    base: dict[str, object] = {
        "suite_version": PRECHECK_SUITE_VERSION,
        "devices": [
            {"kind": "camera", "status": "ok"},
            {"kind": "microphone", "status": "ok"},
            {"kind": "speaker", "status": "ok"},
        ],
        "connection": "good",
        "bandwidth_kbps": 1200,
        "browser": "test-browser",
    }
    base.update(overrides)
    return PreCheckReport.model_validate(base)


def test_passing_report_passes() -> None:
    result = evaluate_precheck(_report())
    assert result.passed
    assert result.failures == []


def test_missing_device_fails() -> None:
    result = evaluate_precheck(_report(devices=[{"kind": "camera", "status": "ok"}]))
    assert not result.passed
    assert any("microphone" in f for f in result.failures)
    assert any("speaker" in f for f in result.failures)


def test_degraded_camera_fails_closed() -> None:
    report = _report(
        devices=[
            {"kind": "camera", "status": "degraded"},
            {"kind": "microphone", "status": "ok"},
            {"kind": "speaker", "status": "ok"},
        ]
    )
    result = evaluate_precheck(report)
    assert not result.passed
    assert any("camera" in f for f in result.failures)


def test_unknown_status_rejected() -> None:
    report = _report(
        devices=[
            {"kind": "camera", "status": "excellent"},
            {"kind": "microphone", "status": "ok"},
            {"kind": "speaker", "status": "ok"},
        ]
    )
    result = evaluate_precheck(report)
    assert not result.passed
    assert any("invalid status" in f for f in result.failures)


def test_stale_suite_version_rejected_before_anything_else() -> None:
    result = evaluate_precheck(
        _report(suite_version="2020.01", devices=[{"kind": "camera", "status": "failed"}])
    )
    assert not result.passed
    assert len(result.failures) == 1
    assert "suite_version" in result.failures[0]


def test_poor_connection_fails_even_with_good_devices() -> None:
    result = evaluate_precheck(_report(connection="poor"))
    assert not result.passed
    assert any("connection" in f for f in result.failures)


def test_low_bandwidth_fails() -> None:
    result = evaluate_precheck(_report(bandwidth_kbps=120))
    assert not result.passed
    assert any("bandwidth" in f for f in result.failures)


def test_unknown_connection_fails_closed() -> None:
    result = evaluate_precheck(_report(connection="unknown"))
    assert not result.passed
    assert any("unknown" in f for f in result.failures)


def test_extra_devices_do_not_hurt_and_evaluation_is_pure() -> None:
    report = _report(
        devices=[
            {"kind": "camera", "status": "ok"},
            {"kind": "microphone", "status": "ok"},
            {"kind": "speaker", "status": "ok"},
            DeviceCheck(kind="headphones", status="missing"),
        ]
    )
    first = evaluate_precheck(report)
    second = evaluate_precheck(report)
    assert first.passed
    assert first.model_dump() == second.model_dump()
