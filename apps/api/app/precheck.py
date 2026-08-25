"""Device pre-check validation — pure logic, fail-closed.

Before a candidate may enter a live interview, the candidate's browser runs
an equipment self-check (camera, microphone, speaker, connection sample) and
submits the report. Validation here is deliberately strict: any required
device not reported exactly ``ok`` fails the whole report, and reports for an
older suite version are rejected outright so stale clients cannot pass on
outdated criteria. No I/O; fully deterministic.
"""

from pydantic import BaseModel, Field

PRECHECK_SUITE_VERSION = "2026.08"

REQUIRED_DEVICE_KINDS = ("camera", "microphone", "speaker")
ALLOWED_STATUSES = frozenset({"ok", "degraded", "failed", "missing"})
ALLOWED_CONNECTIONS = frozenset({"good", "fair", "poor", "unknown"})

MIN_BANDWIDTH_KBPS = 300


class DeviceCheck(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    status: str = Field(min_length=1, max_length=16)
    label: str = Field(default="", max_length=120)


class PreCheckReport(BaseModel):
    suite_version: str = Field(min_length=1, max_length=32)
    devices: list[DeviceCheck] = Field(min_length=1)
    connection: str = Field(default="unknown", max_length=16)
    bandwidth_kbps: int = Field(default=0, ge=0)
    browser: str = Field(default="unknown", max_length=64)


class PreCheckResult(BaseModel):
    passed: bool
    failures: list[str]
    suite_version: str


def evaluate_precheck(report: PreCheckReport) -> PreCheckResult:
    """Return pass/fail with machine-readable failure reasons.

    Fail-closed rules, in order:
    - wrong suite version → reject (client is stale)
    - unknown device statuses → reject
    - every required device must be present and exactly ``ok``
    - degraded/missing connection info only warns via the report, never passes:
      ``poor`` or sub-minimum bandwidth fails; ``unknown`` fails too since we
      cannot claim the link was ever verified.
    """
    if report.suite_version != PRECHECK_SUITE_VERSION:
        return PreCheckResult(
            passed=False,
            failures=[
                f"suite_version {report.suite_version!r} != supported "
                f"{PRECHECK_SUITE_VERSION!r}; refresh and re-run the check"
            ],
            suite_version=report.suite_version,
        )

    failures: list[str] = []
    by_kind: dict[str, list[str]] = {}
    for index, device in enumerate(report.devices):
        if device.status not in ALLOWED_STATUSES:
            failures.append(f"devices[{index}] ({device.kind}): invalid status {device.status!r}")
            continue
        by_kind.setdefault(device.kind, []).append(device.status)

    for kind in REQUIRED_DEVICE_KINDS:
        statuses = by_kind.get(kind)
        if not statuses:
            failures.append(f"{kind}: required device check missing")
        elif any(status != "ok" for status in statuses):
            failures.append(f"{kind}: not ok ({','.join(statuses)})")

    if report.connection not in ALLOWED_CONNECTIONS:
        failures.append(f"connection: invalid value {report.connection!r}")
    elif report.connection in {"poor", "unknown"}:
        failures.append(f"connection: {report.connection} does not meet minimum")
    elif report.bandwidth_kbps < MIN_BANDWIDTH_KBPS:
        failures.append(
            f"bandwidth: {report.bandwidth_kbps} kbps below minimum {MIN_BANDWIDTH_KBPS} kbps"
        )

    return PreCheckResult(
        passed=not failures,
        failures=failures,
        suite_version=report.suite_version,
    )


__all__ = [
    "ALLOWED_CONNECTIONS",
    "ALLOWED_STATUSES",
    "DeviceCheck",
    "MIN_BANDWIDTH_KBPS",
    "PRECHECK_SUITE_VERSION",
    "PreCheckReport",
    "PreCheckResult",
    "evaluate_precheck",
]
