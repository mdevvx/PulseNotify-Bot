"""AlertConfigurationRepository: default per-event-type toggles seeded when
an account is added (section 7's "Live Ended: OFF" example)."""

from __future__ import annotations

import pytest

from database.repositories.alert_configs import AlertConfigurationRepository
from events.models import EventType
from tests.unit.fakes import FakeDatabase


@pytest.fixture
def repo() -> AlertConfigurationRepository:
    return AlertConfigurationRepository(FakeDatabase())  # type: ignore[arg-type]


async def test_seed_defaults_creates_one_row_per_event_type(repo: AlertConfigurationRepository) -> None:
    event_types = [e.value for e in EventType]
    await repo.seed_defaults(1, "acc-1", event_types)

    for event_type in event_types:
        row = await repo.get("acc-1", event_type)
        assert row is not None


async def test_seed_defaults_disables_stream_ended_by_default(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["stream_ended", "video_published"])

    stream_ended = await repo.get("acc-1", "stream_ended")
    video_published = await repo.get("acc-1", "video_published")

    assert stream_ended is not None and stream_ended["enabled"] is False
    assert video_published is not None and video_published["enabled"] is True


async def test_seed_defaults_is_idempotent(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published"])
    await repo.seed_defaults(1, "acc-1", ["video_published"])  # must not raise

    row = await repo.get("acc-1", "video_published")
    assert row is not None


async def test_get_returns_none_for_unconfigured_event_type(repo: AlertConfigurationRepository) -> None:
    assert await repo.get("acc-1", "video_published") is None


async def test_list_for_account_returns_every_configured_event_type(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published", "stream_started"])

    rows = await repo.list_for_account("acc-1")

    assert {r["event_type"] for r in rows} == {"video_published", "stream_started"}


async def test_set_custom_message_applies_to_all_event_types_by_default(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published", "stream_started"])

    updated = await repo.set_custom_message("acc-1", "Hey @everyone, {creator} posted!")

    assert updated == 2
    video = await repo.get("acc-1", "video_published")
    stream = await repo.get("acc-1", "stream_started")
    assert video is not None and video["custom_message"] == "Hey @everyone, {creator} posted!"
    assert stream is not None and stream["custom_message"] == "Hey @everyone, {creator} posted!"


async def test_set_custom_message_can_target_one_event_type_only(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published", "stream_started"])

    updated = await repo.set_custom_message("acc-1", "Live now!", event_type="stream_started")

    assert updated == 1
    video = await repo.get("acc-1", "video_published")
    stream = await repo.get("acc-1", "stream_started")
    assert video is not None and video["custom_message"] is None
    assert stream is not None and stream["custom_message"] == "Live now!"


async def test_set_custom_message_none_clears_it(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published"])
    await repo.set_custom_message("acc-1", "some message")

    await repo.set_custom_message("acc-1", None)

    row = await repo.get("acc-1", "video_published")
    assert row is not None and row["custom_message"] is None


async def test_set_custom_message_for_unknown_account_updates_nothing(repo: AlertConfigurationRepository) -> None:
    updated = await repo.set_custom_message("no-such-account", "hello")
    assert updated == 0


async def test_set_mention_role_applies_to_all_event_types_by_default(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published", "stream_started"])

    updated = await repo.set_mention_role("acc-1", 999)

    assert updated == 2
    video = await repo.get("acc-1", "video_published")
    stream = await repo.get("acc-1", "stream_started")
    assert video is not None and video["mention_role_id"] == 999
    assert stream is not None and stream["mention_role_id"] == 999


async def test_set_mention_role_can_target_one_event_type_only(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published", "stream_started"])

    updated = await repo.set_mention_role("acc-1", 999, event_type="stream_started")

    assert updated == 1
    video = await repo.get("acc-1", "video_published")
    stream = await repo.get("acc-1", "stream_started")
    assert video is not None and video["mention_role_id"] is None
    assert stream is not None and stream["mention_role_id"] == 999


async def test_set_mention_role_none_clears_it(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published"])
    await repo.set_mention_role("acc-1", 999)

    await repo.set_mention_role("acc-1", None)

    row = await repo.get("acc-1", "video_published")
    assert row is not None and row["mention_role_id"] is None


async def test_set_mention_role_for_unknown_account_updates_nothing(repo: AlertConfigurationRepository) -> None:
    updated = await repo.set_mention_role("no-such-account", 999)
    assert updated == 0


async def test_set_alert_toggle_updates_enabled_only(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published"])

    updated = await repo.set_alert_toggle("acc-1", "video_published", enabled=False)

    assert updated == 1
    row = await repo.get("acc-1", "video_published")
    assert row is not None
    assert row["enabled"] is False
    assert row["embed_enabled"] is True  # untouched


async def test_set_alert_toggle_updates_embed_enabled_only() -> None:
    repo = AlertConfigurationRepository(FakeDatabase())  # type: ignore[arg-type]
    await repo.seed_defaults(1, "acc-1", ["video_published"])

    updated = await repo.set_alert_toggle("acc-1", "video_published", embed_enabled=False)

    assert updated == 1
    row = await repo.get("acc-1", "video_published")
    assert row is not None
    assert row["enabled"] is True  # untouched
    assert row["embed_enabled"] is False


async def test_set_alert_toggle_updates_both_at_once(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published"])

    updated = await repo.set_alert_toggle("acc-1", "video_published", enabled=False, embed_enabled=False)

    assert updated == 1
    row = await repo.get("acc-1", "video_published")
    assert row is not None
    assert row["enabled"] is False
    assert row["embed_enabled"] is False


async def test_set_alert_toggle_only_targets_the_given_event_type(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published", "stream_started"])

    await repo.set_alert_toggle("acc-1", "video_published", enabled=False)

    stream = await repo.get("acc-1", "stream_started")
    assert stream is not None and stream["enabled"] is True


async def test_set_alert_toggle_with_nothing_to_change_updates_nothing(repo: AlertConfigurationRepository) -> None:
    await repo.seed_defaults(1, "acc-1", ["video_published"])

    updated = await repo.set_alert_toggle("acc-1", "video_published")

    assert updated == 0


async def test_set_alert_toggle_for_unknown_account_updates_nothing(repo: AlertConfigurationRepository) -> None:
    updated = await repo.set_alert_toggle("no-such-account", "video_published", enabled=False)
    assert updated == 0
