"""Section 8: don't repeat a live notification while still live, and don't
lose track of live state across a restart (i.e. it's persisted, not
in-memory-only)."""

from __future__ import annotations

import pytest

from database.repositories.live_states import LiveStateRepository
from tests.unit.fakes import FakeDatabase


@pytest.fixture
def repo() -> LiveStateRepository:
    return LiveStateRepository(FakeDatabase())  # type: ignore[arg-type]


async def test_get_returns_none_for_unknown_account(repo: LiveStateRepository) -> None:
    assert await repo.get("acc-1") is None


async def test_set_live_then_get_reflects_is_live(repo: LiveStateRepository) -> None:
    await repo.set_live(guild_id=1, account_id="acc-1", stream_id="stream-1", started_at=None)

    row = await repo.get("acc-1")
    assert row is not None
    assert row["is_live"] is True
    assert row["current_stream_id"] == "stream-1"
    assert row["ended_at"] is None


async def test_set_offline_after_live_clears_is_live_and_sets_ended_at(repo: LiveStateRepository) -> None:
    await repo.set_live(guild_id=1, account_id="acc-1", stream_id="stream-1", started_at=None)
    await repo.set_offline(guild_id=1, account_id="acc-1")

    row = await repo.get("acc-1")
    assert row is not None
    assert row["is_live"] is False
    assert row["ended_at"] is not None


async def test_touch_checked_does_not_change_is_live(repo: LiveStateRepository) -> None:
    await repo.set_live(guild_id=1, account_id="acc-1", stream_id="stream-1", started_at=None)
    await repo.touch_checked(guild_id=1, account_id="acc-1")

    row = await repo.get("acc-1")
    assert row is not None
    assert row["is_live"] is True


async def test_two_accounts_have_independent_live_state(repo: LiveStateRepository) -> None:
    await repo.set_live(guild_id=1, account_id="acc-1", stream_id="s1", started_at=None)

    assert (await repo.get("acc-1"))["is_live"] is True  # type: ignore[index]
    assert await repo.get("acc-2") is None
