"""Section 22: retry transient failures with backoff, never retry permanent ones."""

from __future__ import annotations

import pytest

from monitoring.retry import RetryPolicy
from utils.errors import PermanentPlatformError, RateLimitedError, TransientPlatformError


@pytest.fixture
def fast_policy() -> RetryPolicy:
    return RetryPolicy(max_attempts=4, base_delay=0.001, max_delay=0.01, jitter_fraction=0.0)


async def test_succeeds_on_first_try_without_retrying(fast_policy: RetryPolicy) -> None:
    calls = 0

    async def _func():
        nonlocal calls
        calls += 1
        return "ok"

    result = await fast_policy.run(_func)

    assert result == "ok"
    assert calls == 1


async def test_retries_transient_failures_then_succeeds(fast_policy: RetryPolicy) -> None:
    calls = 0

    async def _func():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TransientPlatformError("temporary")
        return "ok"

    result = await fast_policy.run(_func)

    assert result == "ok"
    assert calls == 3


async def test_gives_up_after_max_attempts(fast_policy: RetryPolicy) -> None:
    calls = 0

    async def _func():
        nonlocal calls
        calls += 1
        raise TransientPlatformError("always fails")

    with pytest.raises(TransientPlatformError):
        await fast_policy.run(_func)

    assert calls == fast_policy.max_attempts


async def test_permanent_error_is_never_retried(fast_policy: RetryPolicy) -> None:
    calls = 0

    async def _func():
        nonlocal calls
        calls += 1
        raise PermanentPlatformError("account not found")

    with pytest.raises(PermanentPlatformError):
        await fast_policy.run(_func)

    assert calls == 1


async def test_rate_limited_error_is_never_retried_here_either(fast_policy: RetryPolicy) -> None:
    """A generic short backoff would just hit the same limit again — the
    worker handles the real wait via PlatformHealthTracker instead."""
    calls = 0

    async def _func():
        nonlocal calls
        calls += 1
        raise RateLimitedError("429", retry_after=120.0)

    with pytest.raises(RateLimitedError):
        await fast_policy.run(_func)

    assert calls == 1
