#!/usr/bin/env python3
"""Basic concurrent load test against a running AIVA API (M12 scope).

Stdlib-only (urllib + concurrent.futures) so it runs anywhere with Python
3.11+, no project venv or dependency install required.

Measures raw serving capacity of the API process itself. Note this
deliberately targets an instance with AIVA_ENVIRONMENT=test (rate limiting
disabled, see app/rate_limit.py) -- the whole point of the rate limiter
(ADR-025) is to cap exactly this kind of traffic in a real deployment, so
running this against a `development`/production-configured instance mostly
measures how fast it returns 429, not the API's real throughput. Both
numbers are worth knowing; this script reports the raw-capacity one and
notes the distinction rather than conflating them.

Usage:
    AIVA_ENVIRONMENT=test docker compose up -d
    python3 scripts/load_test.py [--base-url http://localhost:18000] \
        [--concurrency 20] [--requests 500]

What it does NOT do, disclosed rather than implied: simulate realistic
production traffic mix or ramp-up patterns, test sustained load over
minutes/hours, or exercise the AI-gateway/sandbox-runner paths (those have
their own, much higher, real latency from calling out to Claude / running
candidate code -- mixing them into one percentile distribution with
millisecond-scale CRUD reads would be misleading, not more thorough).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field


@dataclass
class RequestResult:
    endpoint: str
    status: int | None
    duration_ms: float
    error: str | None = None


@dataclass
class EndpointStats:
    durations_ms: list[float] = field(default_factory=list)
    statuses: list[int | None] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _request(
    method: str, url: str, body: dict[str, object] | None, headers: dict[str, str]
) -> tuple[int, dict[str, object]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read()
        parsed = json.loads(raw) if raw else {}
        return response.status, parsed


def setup(base_url: str) -> tuple[str, str, str]:
    """Registers a throwaway org/department/requisition, returns (token, org_id, requisition_id)."""
    suffix = uuid.uuid4().hex[:8]
    email = f"loadtest-{suffix}@example.test"
    password = "load-test-password-123"

    status, body = _request(
        "POST",
        f"{base_url}/auth/register-org",
        {
            "organization_name": f"Load Test Org {suffix}",
            "admin_email": email,
            "admin_password": password,
        },
        {},
    )
    if status != 201:
        raise RuntimeError(f"register-org failed: {status} {body}")
    org_id = str(body["organization_id"])

    status, body = _request(
        "POST", f"{base_url}/auth/login", {"email": email, "password": password}, {}
    )
    if status != 200:
        raise RuntimeError(f"login failed: {status} {body}")
    token = str(body["access_token"])
    headers = {"Authorization": f"Bearer {token}"}

    status, body = _request(
        "POST", f"{base_url}/orgs/{org_id}/departments", {"name": "Load Test"}, headers
    )
    if status != 201:
        raise RuntimeError(f"create department failed: {status} {body}")
    dept_id = str(body["id"])

    status, body = _request(
        "POST",
        f"{base_url}/departments/{dept_id}/requisitions",
        {"title": "Load Test Role", "department_id": dept_id},
        headers,
    )
    if status != 201:
        raise RuntimeError(f"create requisition failed: {status} {body}")
    requisition_id = str(body["id"])

    return token, org_id, requisition_id


def worker(base_url: str, token: str, org_id: str, requisition_id: str) -> list[RequestResult]:
    headers = {"Authorization": f"Bearer {token}"}
    endpoints: list[tuple[str, str, str]] = [
        ("GET", f"{base_url}/healthz", "healthz"),
        ("GET", f"{base_url}/orgs/{org_id}/requisitions", "list_requisitions"),
        (
            "GET",
            f"{base_url}/requisitions/{requisition_id}/candidates",
            "list_candidates",
        ),
        ("GET", f"{base_url}/me", "me"),
    ]
    results: list[RequestResult] = []
    for method, url, label in endpoints:
        started = time.monotonic()
        try:
            status, _body = _request(method, url, None, headers)
            results.append(
                RequestResult(label, status, (time.monotonic() - started) * 1000)
            )
        except urllib.error.HTTPError as exc:
            results.append(
                RequestResult(label, exc.code, (time.monotonic() - started) * 1000, str(exc))
            )
        except Exception as exc:  # noqa: BLE001 - report every failure mode, don't filter
            results.append(
                RequestResult(label, None, (time.monotonic() - started) * 1000, str(exc))
            )
    return results


def percentile(data: list[float], pct: float) -> float:
    if not data:
        return 0.0
    ordered = sorted(data)
    index = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:18000")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--requests", type=int, default=500, help="total worker rounds")
    args = parser.parse_args()

    print(f"Setting up load-test org against {args.base_url} ...")
    token, org_id, requisition_id = setup(args.base_url)
    print(f"Ready: org={org_id} requisition={requisition_id}")
    print(
        f"Running {args.requests} rounds at concurrency={args.concurrency} "
        f"(4 requests/round -> {args.requests * 4} total requests) ...\n"
    )

    stats: dict[str, EndpointStats] = {}
    overall_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(worker, args.base_url, token, org_id, requisition_id)
            for _ in range(args.requests)
        ]
        for future in as_completed(futures):
            for result in future.result():
                bucket = stats.setdefault(result.endpoint, EndpointStats())
                bucket.durations_ms.append(result.duration_ms)
                bucket.statuses.append(result.status)
                if result.error:
                    bucket.errors.append(result.error)

    wall_seconds = time.monotonic() - overall_start
    total_requests = sum(len(s.durations_ms) for s in stats.values())

    print(f"{'endpoint':<20} {'count':>7} {'errors':>7} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'max ms':>8}")
    for label, bucket in sorted(stats.items()):
        error_count = sum(1 for s in bucket.statuses if s is None or s >= 400)
        print(
            f"{label:<20} {len(bucket.durations_ms):>7} {error_count:>7} "
            f"{percentile(bucket.durations_ms, 0.50):>8.1f} "
            f"{percentile(bucket.durations_ms, 0.95):>8.1f} "
            f"{percentile(bucket.durations_ms, 0.99):>8.1f} "
            f"{max(bucket.durations_ms):>8.1f}"
        )
        if bucket.errors:
            sample = bucket.errors[0]
            print(f"  sample error: {sample[:200]}")

    print(
        f"\n{total_requests} requests in {wall_seconds:.2f}s "
        f"({total_requests / wall_seconds:.1f} req/s, concurrency={args.concurrency})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
