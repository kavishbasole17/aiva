"""Runs untrusted candidate code with layered, honestly-scoped isolation.

This is process-level isolation, not a container/VM boundary: a distinct,
one-per-concurrent-run unprivileged OS account drawn from `UidPool` (never
the service's own account, and never shared with another live run — see
ADR-019 and ADR-020), POSIX resource limits (CPU seconds, address space,
process count, open files, output size), isolated network *and* PID
namespaces (no route to the host/internet, and no visibility into any
other run's processes via /proc), an ephemeral per-run temp directory, and
a hard wall-clock timeout that kills the whole process group. That is a
real, defensible boundary for a live-interview coding exercise, but it is
still a single Linux kernel shared with the host — a kernel exploit
escapes it. A hardened runtime (gVisor/Firecracker/nsjail+seccomp) is the
honest answer for production-grade multi-tenant execution and is deferred
to M12 deployment hardening (same "mock now, hardened at deployment"
precedent as the AI gateway's STT/TTS backends) — the executor interface
below does not change when that lands.

Every result carries enough attribution (duration, truncation, timeout) for
the caller to persist a faithful execution record, same provenance
discipline as the rest of the platform (constraint 8.1).
"""

import asyncio
import os
import resource
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

SUPPORTED_LANGUAGES = ("python", "javascript")


class SandboxError(ValueError):
    """Raised for out-of-policy requests (bad language, oversized source)."""


class SandboxUnavailableError(RuntimeError):
    """Raised when a required isolation primitive is missing on this host.

    Fails closed: code execution is refused rather than silently run with a
    weaker isolation boundary than the caller was promised.
    """


class UidPool:
    """A fixed set of dedicated sandbox uids, checked out one-per-run.

    Two runs executing concurrently must never share a uid: filesystem DAC
    checks (and, without a separate PID namespace, /proc visibility and
    signal delivery) are uid-based, not run-based, so a shared uid would let
    one candidate's code read or kill another's mid-execution (ADR-020).
    Acquiring blocks — rather than falling back to a shared uid — when every
    slot is checked out, so the safety property holds even under load
    instead of degrading silently.
    """

    def __init__(self, start_uid: int, size: int, gid: int) -> None:
        if size < 1:
            raise ValueError("UidPool size must be at least 1")
        self.gid = gid
        self._available: asyncio.Queue[int] = asyncio.Queue()
        for offset in range(size):
            self._available.put_nowait(start_uid + offset)

    async def acquire(self) -> int:
        return await self._available.get()

    def release(self, uid: int) -> None:
        self._available.put_nowait(uid)


class ExecutionResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    truncated: bool
    duration_ms: int = Field(ge=0)
    language: str


def _truncate(data: bytes, limit: int) -> tuple[str, bool]:
    text = data.decode("utf-8", errors="replace")
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _drop_privileges(uid: int, gid: int) -> None:
    """Setuid-drop into the dedicated sandbox account, if we can.

    Only real root can setuid/setgid to another account. The Docker image
    runs this service as root specifically so this succeeds (ADR-019); a
    non-root dev run (e.g. bare `uvicorn` on a workstation) has nothing to
    drop from and silently continues as its own already-unprivileged user —
    every other isolation layer (rlimits, network namespace, ephemeral cwd)
    still applies.
    """
    if os.geteuid() != 0:
        return
    os.setgroups([])
    os.setresgid(gid, gid, gid)
    os.setresuid(uid, uid, uid)


def _apply_rlimits(
    cpu_seconds: int,
    memory_bytes: int,
    max_processes: int,
    max_files: int,
    rlimit_as_bytes: int,
) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    # RLIMIT_AS bounds total virtual address space, not heap usage -- a
    # runtime can need to mmap far more of that than it ever actually uses
    # (V8/Node reserves substantially more virtual memory than its
    # `--max-old-space-size` heap cap at startup, before running a single
    # line of candidate code). Capping RLIMIT_AS at the heap-size value
    # (memory_bytes) rather than the deliberately larger rlimit_as_bytes
    # was a real, previously-shipped bug here: V8's startup mmap calls hit
    # ENOMEM and Node hung until the wall-clock timeout on every single
    # execution, 100% reproducible, confirmed by testing 128MB (the old,
    # wrong value) against 768MB (the intended one) directly.
    resource.setrlimit(resource.RLIMIT_AS, (rlimit_as_bytes, rlimit_as_bytes))
    resource.setrlimit(resource.RLIMIT_NPROC, (max_processes, max_processes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (max_files, max_files))
    resource.setrlimit(resource.RLIMIT_FSIZE, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


#: Cached result of _verify_isolation_available(): None = not checked yet,
#: True = confirmed working, False = confirmed broken. A module-level cache
#: because the environment's capability set cannot change between requests
#: within one running process, and probing costs a real subprocess spawn.
_isolation_verified: bool | None = None


def _verify_isolation_available(unshare: str) -> None:
    """Actually exercise unshare, not just check the binary exists.

    `unshare --map-root-user --net --pid --fork` can be present yet still
    fail at run time — no real CAP_SYS_ADMIN and no permission to create an
    unprivileged user namespace either (seen in practice under some Docker
    Desktop / non-default container security-opt configurations) — in which
    case unshare itself exits non-zero with "Operation not permitted"
    *before ever exec'ing the candidate's code*. Without this check, that
    failure was indistinguishable from the caller's perspective from the
    candidate's own code exiting with status 1: same exit code, no isolation
    breach (unshare failing means nothing ran unisolated), but a materially
    wrong and misleading result — "your code failed" when the sandbox
    itself is the thing that's broken. Checked once and cached rather than
    per-request: the environment doesn't change between requests, and this
    spawns a real subprocess.
    """
    global _isolation_verified
    if _isolation_verified is True:
        return
    if _isolation_verified is False:
        raise SandboxUnavailableError(
            "unshare cannot create isolated namespaces in this environment; "
            "refusing to run code without network/PID isolation rather than "
            "silently misreport an infrastructure failure as a candidate code failure"
        )
    probe = subprocess.run(  # noqa: S603 - fixed argv, never shell-interpreted
        [unshare, "--map-root-user", "--net", "--pid", "--fork", "--", "true"],
        capture_output=True,
        timeout=5,
    )
    if probe.returncode != 0:
        _isolation_verified = False
        detail = probe.stderr.decode("utf-8", errors="replace").strip()
        raise SandboxUnavailableError(
            "unshare is present but failed to create isolated namespaces "
            f"(likely missing CAP_SYS_ADMIN, or blocked by seccomp/AppArmor): {detail}"
        )
    _isolation_verified = True


def _isolation_prefix() -> list[str]:
    """Wrap the command in a fresh network *and* PID namespace.

    `--map-root-user` implies an unprivileged user namespace, which is what
    lets a non-root caller create the other namespaces at all (no real
    CAP_SYS_ADMIN needed) — the resulting "root" identity is local to that
    throwaway namespace only and grants nothing on the host. `--net` starts
    with just loopback: no interface is bridged in, so there is no route
    out, not even to other containers on the compose network. `--pid
    --fork` puts the process in its own PID namespace, so even though the
    *uid* isolation is what stops another run's code from reading its
    files (`UidPool`), this independently stops it from enumerating,
    reading `/proc/<pid>/*` for, or signalling another run's process at
    all — standard Linux PID-namespace visibility rules mean a sibling
    namespace's tasks simply don't appear.
    """
    unshare = shutil.which("unshare")
    if unshare is None:
        raise SandboxUnavailableError(
            "unshare (util-linux) is not available; refusing to run code "
            "without network/PID isolation rather than degrade silently"
        )
    _verify_isolation_available(unshare)
    return [unshare, "--map-root-user", "--net", "--pid", "--fork", "--"]


class Executor(ABC):
    @property
    @abstractmethod
    def language(self) -> str: ...

    @abstractmethod
    async def run(
        self, source: str, stdin: str, timeout_seconds: float, uid: int, gid: int
    ) -> ExecutionResult: ...


class _SubprocessExecutor(Executor):
    """Shared sandboxing mechanics; subclasses supply the interpreter argv."""

    def __init__(
        self,
        language: str,
        filename: str,
        argv_for: Callable[[Path], list[str]],
        settings_memory_mb: int,
        settings_rlimit_as_mb: int | None = None,
    ) -> None:
        self._language = language
        self._filename = filename
        self._argv_for = argv_for
        self._memory_bytes = settings_memory_mb * 1024 * 1024
        self._rlimit_as_bytes = (settings_rlimit_as_mb or settings_memory_mb) * 1024 * 1024

    @property
    def language(self) -> str:
        return self._language

    async def run(
        self, source: str, stdin: str, timeout_seconds: float, uid: int, gid: int
    ) -> ExecutionResult:
        from app.settings import get_settings

        settings = get_settings()
        return await asyncio.to_thread(
            self._run_sync,
            source,
            stdin,
            timeout_seconds,
            uid,
            gid,
            settings.max_processes,
            settings.max_open_files,
            settings.max_output_bytes,
        )

    def _run_sync(
        self,
        source: str,
        stdin: str,
        timeout_seconds: float,
        sandbox_uid: int,
        sandbox_gid: int,
        max_processes: int,
        max_open_files: int,
        max_output_bytes: int,
    ) -> ExecutionResult:
        run_id = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix=f"aiva-sandbox-{run_id}-") as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            source_path = tmpdir / self._filename
            source_path.write_text(source, encoding="utf-8")
            try:
                os.chown(tmpdir, sandbox_uid, sandbox_gid)
                os.chown(source_path, sandbox_uid, sandbox_gid)
            except PermissionError:
                pass  # not root (dev fallback); nothing to chown to
            os.chmod(tmpdir, 0o700)

            argv = [*_isolation_prefix(), *self._argv_for(source_path)]
            cpu_seconds = max(1, int(timeout_seconds) + 2)

            def preexec() -> None:
                _drop_privileges(sandbox_uid, sandbox_gid)
                _apply_rlimits(
                    cpu_seconds,
                    self._memory_bytes,
                    max_processes,
                    max_open_files,
                    self._rlimit_as_bytes,
                )

            started = time.monotonic()
            process = subprocess.Popen(  # noqa: S603 - argv is built from a fixed allowlist, never shell-interpreted
                argv,
                cwd=tmpdir,
                # /usr/local/bin first: the official python:3.11-slim base image
                # (this service's own Dockerfile) installs python3 there, not
                # /usr/bin -- a bare "python3" in argv_for would silently fail to
                # resolve without it. Still a fixed, minimal allowlist, not the
                # caller's real PATH.
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(tmpdir)},
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=preexec,
                start_new_session=True,
            )
            timed_out = False
            try:
                stdout_bytes, stderr_bytes = process.communicate(
                    input=stdin.encode("utf-8"), timeout=timeout_seconds
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                stdout_bytes, stderr_bytes = process.communicate()
            duration_ms = int((time.monotonic() - started) * 1000)

            stdout, out_truncated = _truncate(stdout_bytes, max_output_bytes)
            stderr, err_truncated = _truncate(stderr_bytes, max_output_bytes)
            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=process.returncode if not timed_out else None,
                timed_out=timed_out,
                truncated=out_truncated or err_truncated,
                duration_ms=duration_ms,
                language=self._language,
            )


def build_executor(language: str) -> Executor:
    from app.settings import get_settings

    settings = get_settings()
    if language == "python":
        return _SubprocessExecutor(
            language="python",
            filename="main.py",
            argv_for=lambda path: ["python3", "-I", "-S", str(path)],
            settings_memory_mb=settings.memory_limit_mb,
        )
    if language == "javascript":
        return _SubprocessExecutor(
            language="javascript",
            filename="main.js",
            argv_for=lambda path: [
                "node",
                f"--max-old-space-size={settings.node_memory_limit_mb}",
                str(path),
            ],
            settings_memory_mb=settings.node_memory_limit_mb,
            settings_rlimit_as_mb=settings.node_rlimit_as_mb,
        )
    raise SandboxError(f"Unsupported language: {language!r}. Supported: {SUPPORTED_LANGUAGES}")


__all__ = [
    "SUPPORTED_LANGUAGES",
    "ExecutionResult",
    "Executor",
    "SandboxError",
    "SandboxUnavailableError",
    "build_executor",
]
