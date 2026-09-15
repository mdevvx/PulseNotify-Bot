"""NotificationChannelRepository: routing accounts to Discord channels,
and section 23's "mark invalid rather than retry forever" behavior."""

from __future__ import annotations

import pytest

from database.repositories.channels import NotificationChannelRepository
from tests.unit.fakes import FakeDatabase


@pytest.fixture
def repo() -> NotificationChannelRepository:
    return NotificationChannelRepository(FakeDatabase())  # type: ignore[arg-type]


async def test_get_or_create_creates_a_new_row(repo: NotificationChannelRepository) -> None:
    row = await repo.get_or_create(1, 555, name="#alerts")

    assert row["guild_id"] == 1
    assert row["channel_id"] == 555
    assert row["is_valid"] is True


async def test_get_or_create_reuses_an_existing_valid_row(repo: NotificationChannelRepository) -> None:
    first = await repo.get_or_create(1, 555, name="#alerts")
    second = await repo.get_or_create(1, 555, name="#alerts")

    assert first["id"] == second["id"]


async def test_get_or_create_revalidates_a_previously_invalid_channel(repo: NotificationChannelRepository) -> None:
    row = await repo.get_or_create(1, 555, name="#alerts")
    await repo.mark_invalid(row["id"])

    revived = await repo.get_or_create(1, 555, name="#alerts")

    assert revived["id"] == row["id"]
    assert revived["is_valid"] is True


async def test_different_guilds_can_register_the_same_discord_channel_id_independently(
    repo: NotificationChannelRepository,
) -> None:
    row_a = await repo.get_or_create(1, 555)
    row_b = await repo.get_or_create(2, 555)

    assert row_a["id"] != row_b["id"]


async def test_list_valid_for_account_returns_only_linked_and_valid_channels(
    repo: NotificationChannelRepository,
) -> None:
    channel_a = await repo.get_or_create(1, 111)
    channel_b = await repo.get_or_create(1, 222)
    await repo.link_account(1, "acc-1", channel_a["id"])
    await repo.link_account(1, "acc-1", channel_b["id"])
    await repo.mark_invalid(channel_b["id"])

    channels = await repo.list_valid_for_account("acc-1")

    assert [c["id"] for c in channels] == [channel_a["id"]]


async def test_list_valid_for_account_with_no_links_returns_empty(repo: NotificationChannelRepository) -> None:
    assert await repo.list_valid_for_account("acc-with-no-channels") == []


async def test_link_account_is_idempotent(repo: NotificationChannelRepository) -> None:
    channel = await repo.get_or_create(1, 111)

    await repo.link_account(1, "acc-1", channel["id"])
    await repo.link_account(1, "acc-1", channel["id"])  # must not raise

    channels = await repo.list_valid_for_account("acc-1")
    assert len(channels) == 1


async def test_one_channel_can_be_linked_to_multiple_accounts(repo: NotificationChannelRepository) -> None:
    channel = await repo.get_or_create(1, 111)

    await repo.link_account(1, "acc-1", channel["id"])
    await repo.link_account(1, "acc-2", channel["id"])

    assert len(await repo.list_valid_for_account("acc-1")) == 1
    assert len(await repo.list_valid_for_account("acc-2")) == 1


async def test_new_channel_has_no_webhook_url_by_default(repo: NotificationChannelRepository) -> None:
    row = await repo.get_or_create(1, 555)
    assert row["webhook_url"] is None


async def test_set_webhook_url_persists_it(repo: NotificationChannelRepository) -> None:
    row = await repo.get_or_create(1, 555)

    await repo.set_webhook_url(row["id"], "https://discord.com/api/webhooks/555/token")

    updated = await repo.get_by_discord_channel(1, 555)
    assert updated is not None
    assert updated["webhook_url"] == "https://discord.com/api/webhooks/555/token"


async def test_set_webhook_url_none_clears_it(repo: NotificationChannelRepository) -> None:
    row = await repo.get_or_create(1, 555)
    await repo.set_webhook_url(row["id"], "https://discord.com/api/webhooks/555/token")

    await repo.set_webhook_url(row["id"], None)

    updated = await repo.get_by_discord_channel(1, 555)
    assert updated is not None
    assert updated["webhook_url"] is None
