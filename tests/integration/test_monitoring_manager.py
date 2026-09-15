"""Full-stack check that MonitoringManager, PlatformScheduler, AccountWorker
and EventProcessor actually work together, not just individually: register
a fake adapter, let a real (tiny-interval) background scheduler loop run
against a fake database, and confirm a detected event reaches a sink
exactly once. Everything below the Supabase client boundary is real; only
the DB itself and the platform API are faked, per the project's testing
rules against live external services.
"""

from __future__ import annotations

import asyncio

import pytest

from config.settings import Settings
from monitoring.manager import MonitoringManager
from tests.unit.fakes import FakeDatabase
from tests.unit.test_worker import FakeAdapter, _seed_account


@pytest.fixture
def fast_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")
    monkeypatch.setenv("MONITORING_CONTENT_POLL_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("MONITORING_LIVE_POLL_INTERVAL_SECONDS", "0.05")
    return Settings(_env_file=None)  # type: ignore[call-arg]


async def test_a_new_video_flows_from_scheduler_to_sink_exactly_once(fast_settings: Settings) -> None:
    db = FakeDatabase()
    _seed_account(db, "acc-1")
    adapter = FakeAdapter()
    adapter.pending_items = [{"id": "vid-1", "title": "Hello"}]

    delivered = []

    async def sink(event):
        delivered.append(event)

    manager = MonitoringManager(db, fast_settings, notification_sink=sink)  # type: ignore[arg-type]
    manager.register_adapter(adapter)
    await manager.start()
    try:
        await asyncio.sleep(0.2)
    finally:
        await manager.stop()

    assert len(delivered) == 1
    assert delivered[0].platform_event_id == "vid-1"
    assert manager.registered_platforms == {"fake": 1}


async def test_the_same_item_returned_by_the_api_twice_is_not_redelivered(fast_settings: Settings) -> None:
    """Section 10: dedup must hold even when the platform API itself returns
    a duplicate (cursor overlap, clock skew, a retried request, ...), not
    just when the worker doesn't re-fetch."""
    db = FakeDatabase()
    _seed_account(db, "acc-1")
    adapter = FakeAdapter()

    delivered = []

    async def sink(event):
        delivered.append(event)

    manager = MonitoringManager(db, fast_settings, notification_sink=sink)  # type: ignore[arg-type]
    manager.register_adapter(adapter)

    await manager.start()
    try:
        adapter.pending_items = [{"id": "vid-1", "title": "Hello"}]
        await asyncio.sleep(0.2)  # first cycle delivers it
        adapter.pending_items = [{"id": "vid-1", "title": "Hello"}]  # API hands back the same item again
        await asyncio.sleep(0.2)
    finally:
        await manager.stop()

    assert len(delivered) == 1
