"""Unit tests for MonitoringManager.register_adapter()'s poll-interval
selection — see platforms/base.py's min_poll_interval_seconds docstring for
why a LIVE_STATUS adapter can't always use the generic per-capability
interval from Settings.
"""

from __future__ import annotations

import pytest

from config.settings import Settings
from monitoring.manager import MonitoringManager
from tests.unit.fakes import FakeDatabase
from tests.unit.test_worker import FakeAdapter


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "test-key")
    monkeypatch.setenv("MONITORING_LIVE_POLL_INTERVAL_SECONDS", "60")
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_live_status_adapter_uses_the_generic_live_interval_by_default(settings: Settings) -> None:
    manager = MonitoringManager(FakeDatabase(), settings)  # type: ignore[arg-type]
    manager.register_adapter(FakeAdapter())

    assert manager._schedulers["fake"]._poll_interval == 60


def test_an_adapter_with_a_slower_min_poll_interval_overrides_the_generic_one(settings: Settings) -> None:
    """Regression test: a LIVE_STATUS adapter whose live check is
    quota-limited (e.g. YouTube's 100-unit search.list against an 80
    calls/day budget) must not be scheduled at the generic 60s LIVE_STATUS
    cadence — that would burn its whole day's budget in the first few
    minutes instead of spreading it out."""
    adapter = FakeAdapter()
    adapter.min_poll_interval_seconds = 1080.0

    manager = MonitoringManager(FakeDatabase(), settings)  # type: ignore[arg-type]
    manager.register_adapter(adapter)

    assert manager._schedulers["fake"]._poll_interval == 1080.0


def test_min_poll_interval_never_shortens_an_already_slower_generic_interval(settings: Settings) -> None:
    adapter = FakeAdapter()
    adapter.min_poll_interval_seconds = 10.0  # shorter than the 60s generic interval

    manager = MonitoringManager(FakeDatabase(), settings)  # type: ignore[arg-type]
    manager.register_adapter(adapter)

    assert manager._schedulers["fake"]._poll_interval == 60
