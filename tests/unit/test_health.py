"""PlatformHealthTracker: the in-memory half of the API usage manager
(batched request counting, and the is_rate_limited() gate the scheduler
checks before every poll cycle)."""

from __future__ import annotations

import asyncio

import pytest

from database.repositories.platform_health import PlatformHealthRepository
from monitoring.health import PlatformHealthTracker
from tests.unit.fakes import FakeDatabase


@pytest.fixture
def tracker() -> PlatformHealthTracker:
    db = FakeDatabase()
    return PlatformHealthTracker("youtube", PlatformHealthRepository(db), degrade_after=3, error_after=8)  # type: ignore[arg-type]


async def test_not_rate_limited_before_any_failure(tracker: PlatformHealthTracker) -> None:
    assert tracker.is_rate_limited() is False


async def test_record_rate_limited_sets_is_rate_limited(tracker: PlatformHealthTracker) -> None:
    await tracker.record_rate_limited(60.0)

    assert tracker.is_rate_limited() is True


async def test_is_rate_limited_clears_after_retry_after_elapses(tracker: PlatformHealthTracker) -> None:
    await tracker.record_rate_limited(0.05)
    assert tracker.is_rate_limited() is True

    await asyncio.sleep(0.08)

    assert tracker.is_rate_limited() is False


async def test_record_request_is_batched_until_flush(tracker: PlatformHealthTracker) -> None:
    tracker.record_request()
    tracker.record_request()
    tracker.record_request()

    row = await tracker._repo.get("youtube")  # type: ignore[attr-defined]
    assert row is None  # nothing written yet

    await tracker.flush()

    row = await tracker._repo.get("youtube")  # type: ignore[attr-defined]
    assert row is not None
    assert row["requests_today"] == 3


async def test_flush_with_nothing_pending_does_not_create_a_row(tracker: PlatformHealthTracker) -> None:
    await tracker.flush()

    row = await tracker._repo.get("youtube")  # type: ignore[attr-defined]
    assert row is None


async def test_record_success_and_failure_delegate_to_the_repository(tracker: PlatformHealthTracker) -> None:
    await tracker.record_failure("boom")
    row = await tracker._repo.get("youtube")  # type: ignore[attr-defined]
    assert row is not None and row["consecutive_failures"] == 1

    await tracker.record_success()
    row = await tracker._repo.get("youtube")  # type: ignore[attr-defined]
    assert row is not None and row["consecutive_failures"] == 0
