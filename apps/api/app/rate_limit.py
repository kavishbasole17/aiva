"""Redis-backed fixed-window rate limiting for brute-force-sensitive endpoints.

M12 pen-test finding: `/auth/login` had no limit at all on failed attempts --
argon2 hashing slows a single guess down but does not make credential
stuffing or a targeted password-guessing attack impossible. This is
deliberately a simple fixed-window failure counter (INCR + EXPIRE-once), not
a sliding-window or token-bucket algorithm: exact precision at the window
boundary isn't the goal, making unlimited guessing impossible is. It counts
only *failures*, not every attempt, so a legitimate user is never penalized
by their own successful logins.
"""

from redis.asyncio import Redis


async def record_failure(redis: Redis, key: str, window_seconds: int) -> int:
    count: int = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    return count


async def failure_count(redis: Redis, key: str) -> int:
    value = await redis.get(key)
    return int(value) if value else 0


async def clear_failures(redis: Redis, key: str) -> None:
    await redis.delete(key)


__all__ = ["clear_failures", "failure_count", "record_failure"]
