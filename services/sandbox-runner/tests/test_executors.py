import asyncio
import os

from app.executors import ExecutionResult, Executor, SandboxError, UidPool, build_executor

# Privilege-dropping only takes effect when the caller is real root
# (executors._drop_privileges no-ops otherwise), so on a non-root test host
# the uid/gid passed through are cosmetic — using the test process's own is
# the only choice that keeps os.chown from raising.
UID = os.getuid()
GID = os.getgid()


async def _run(
    executor: Executor, source: str, stdin: str = "", timeout_seconds: float = 5
) -> ExecutionResult:
    return await executor.run(source, stdin, timeout_seconds, UID, GID)


async def test_python_hello_world() -> None:
    result = await _run(build_executor("python"), "print('hello')")
    assert result.stdout.strip() == "hello"
    assert result.exit_code == 0
    assert not result.timed_out


async def test_python_reads_stdin() -> None:
    source = "import sys\nprint(sys.stdin.read().strip().upper())\n"
    result = await _run(build_executor("python"), source, stdin="hi there")
    assert result.stdout.strip() == "HI THERE"


async def test_python_stderr_and_nonzero_exit() -> None:
    result = await _run(build_executor("python"), "raise SystemExit(3)")
    assert result.exit_code == 3


async def test_javascript_hello_world() -> None:
    result = await _run(build_executor("javascript"), "console.log('hi from node')")
    assert result.stdout.strip() == "hi from node"
    assert result.exit_code == 0


async def test_unsupported_language_raises() -> None:
    try:
        build_executor("ruby")
    except SandboxError:
        pass
    else:
        raise AssertionError("expected SandboxError")


async def test_timeout_kills_infinite_loop() -> None:
    source = "while True:\n    pass\n"
    result = await _run(build_executor("python"), source, timeout_seconds=1)
    assert result.timed_out is True
    assert result.exit_code is None
    # generous ceiling: the kill must land well before it would ever reach
    # the CPU-seconds backstop, not merely before the test framework times out
    assert result.duration_ms < 4000


async def test_memory_limit_prevents_unbounded_allocation() -> None:
    source = "x = bytearray(2 * 1024 * 1024 * 1024)\nprint('should not get here')\n"
    result = await _run(build_executor("python"), source)
    assert "should not get here" not in result.stdout
    assert result.exit_code != 0


async def test_network_is_isolated() -> None:
    source = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(2)\n"
        "try:\n"
        "    s.connect(('8.8.8.8', 53))\n"
        "    print('CONNECTED')\n"
        "except OSError as exc:\n"
        "    print(f'BLOCKED: {exc}')\n"
    )
    result = await _run(build_executor("python"), source)
    assert "CONNECTED" not in result.stdout
    assert "BLOCKED" in result.stdout


async def test_output_is_truncated_past_cap() -> None:
    result = await _run(build_executor("python"), "print('a' * 200000)")
    assert result.truncated is True
    assert len(result.stdout) <= 65_536


async def test_unbounded_output_is_capped_while_draining_not_after() -> None:
    """A genuinely infinite print loop must not be buffered wholesale before
    truncation (that's exactly the memory-exhaustion DoS this executor is
    supposed to prevent) -- it must be capped incrementally while still
    being read to EOF, so the child is never blocked writing to a full pipe
    and instead runs to its own wall-clock timeout as normal."""
    result = await _run(
        build_executor("python"),
        "while True:\n    print('x' * 8192)\n",
        timeout_seconds=2,
    )
    assert result.timed_out is True
    assert result.truncated is True
    assert len(result.stdout) <= 65_536


async def test_pid_namespace_hides_other_processes() -> None:
    """A run in its own PID namespace should see itself as pid 1, with no
    sibling processes visible — confirms --pid --fork is actually landing,
    which is what stops one run from enumerating/signalling another's
    process via /proc (ADR-020)."""
    result = await _run(build_executor("python"), "import os\nprint(os.getpid())\n")
    assert result.stdout.strip() == "1"


async def test_uid_pool_never_hands_out_the_same_uid_twice_concurrently() -> None:
    pool = UidPool(start_uid=7000, size=2, gid=7000)
    first = await pool.acquire()
    second = await pool.acquire()
    assert {first, second} == {7000, 7001}

    # Pool is exhausted: a third acquire must block, not silently reuse one.
    third_task = asyncio.ensure_future(pool.acquire())
    await asyncio.sleep(0.05)
    assert not third_task.done()

    pool.release(first)
    third = await asyncio.wait_for(third_task, timeout=1)
    assert third == first
