"""NotificationSender: alert-config gating, embed-vs-plain-text, mention
scoping (section 36), and marking a channel invalid rather than retrying
forever when Discord says it's gone (section 23)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import discord
import pytest

from database.repositories.alert_configs import AlertConfigurationRepository
from database.repositories.channels import NotificationChannelRepository
from events.models import EventType, NormalizedEvent
from notifications.sender import NotificationSender
from tests.unit.fakes import FakeDatabase


def _fake_http_exception(cls, status: int = 404, reason: str = "Not Found") -> discord.HTTPException:
    response = type("_FakeResponse", (), {"status": status, "reason": reason})()
    return cls(response, "")


class FakeDiscordChannel:
    def __init__(self, channel_id: int, *, raise_on_send: Optional[BaseException] = None) -> None:
        self.id = channel_id
        self.raise_on_send = raise_on_send
        self.sent: List[Dict[str, Any]] = []

    async def send(self, *, content=None, embed=None, allowed_mentions=None, suppress_embeds=False):
        if self.raise_on_send:
            raise self.raise_on_send
        self.sent.append(
            {"content": content, "embed": embed, "allowed_mentions": allowed_mentions, "suppress_embeds": suppress_embeds}
        )


class FakeBot:
    def __init__(self) -> None:
        self._cached: Dict[int, FakeDiscordChannel] = {}
        self._fetchable: Dict[int, FakeDiscordChannel] = {}

    def cache(self, channel: FakeDiscordChannel) -> None:
        self._cached[channel.id] = channel

    def make_fetch_only(self, channel: FakeDiscordChannel) -> None:
        """Simulates a channel not in the gateway cache, requiring fetch_channel()."""
        self._fetchable[channel.id] = channel

    def get_channel(self, channel_id: int):
        return self._cached.get(channel_id)

    async def fetch_channel(self, channel_id: int):
        if channel_id in self._fetchable:
            return self._fetchable[channel_id]
        raise _fake_http_exception(discord.NotFound)


class Harness:
    def __init__(self) -> None:
        self.db = FakeDatabase()
        self.alert_repo = AlertConfigurationRepository(self.db)  # type: ignore[arg-type]
        self.channel_repo = NotificationChannelRepository(self.db)  # type: ignore[arg-type]
        self.bot = FakeBot()
        self.sender = NotificationSender(self.bot, self.alert_repo, self.channel_repo)  # type: ignore[arg-type]

    async def add_channel(self, guild_id: int, account_id: str, discord_channel_id: int) -> FakeDiscordChannel:
        row = await self.channel_repo.get_or_create(guild_id, discord_channel_id)
        await self.channel_repo.link_account(guild_id, account_id, row["id"])
        channel = FakeDiscordChannel(discord_channel_id)
        self.bot.cache(channel)
        return channel


def _event(**overrides) -> NormalizedEvent:
    fields = dict(
        guild_id=1,
        account_id="acc-1",
        platform="youtube",
        platform_account_id="UCabc",
        account_username="Example",
        event_type=EventType.VIDEO_PUBLISHED,
        platform_event_id="vid-1",
        title="A video",
        url="https://youtube.com/watch?v=vid-1",
    )
    fields.update(overrides)
    return NormalizedEvent(**fields)


@pytest.fixture
def harness() -> Harness:
    return Harness()


async def test_sends_an_embed_when_no_config_exists_yet(harness: Harness) -> None:
    channel = await harness.add_channel(1, "acc-1", 555)

    await harness.sender.handle(_event())

    assert len(channel.sent) == 1
    assert channel.sent[0]["embed"] is not None
    assert channel.sent[0]["content"] is None


async def test_disabled_event_type_sends_nothing(harness: Harness) -> None:
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    # Flip it off directly in the fake DB (no /alerts command exists yet).
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["enabled"] = False

    await harness.sender.handle(_event())

    assert channel.sent == []


async def test_embed_disabled_sends_plain_text_instead(harness: Harness) -> None:
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["embed_enabled"] = False

    await harness.sender.handle(_event())

    assert channel.sent[0]["embed"] is None
    assert "A video" in channel.sent[0]["content"]


async def test_mention_role_is_included_and_scoped_to_that_role_only(harness: Harness) -> None:
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["mention_role_id"] = 999

    await harness.sender.handle(_event())

    sent = channel.sent[0]
    assert "<@&999>" in sent["content"]
    allowed = sent["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.users is False


# ── custom_message (section 35) ────────────────────────────────────────


async def test_custom_message_replaces_the_default_content(harness: Harness) -> None:
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["custom_message"] = (
        "Hey @everyone, {creator} just posted a new post! Go check it out!\n{url}"
    )

    await harness.sender.handle(_event())

    sent = channel.sent[0]
    assert sent["content"] == (
        "Hey @everyone, Example just posted a new post! Go check it out!\n"
        "https://youtube.com/watch?v=vid-1"
    )


async def test_custom_message_never_gets_a_manually_built_embed(harness: Harness) -> None:
    """A custom message's template typically already includes {url} as
    plain text, which Discord auto-previews on its own — a hand-built
    embed on top of that would just duplicate it, so custom messages never
    get one regardless of embed_enabled (section 35 revision)."""
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["custom_message"] = "Check this out!\n{url}"
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["embed_enabled"] = True

    await harness.sender.handle(_event())

    sent = channel.sent[0]
    assert sent["content"] == "Check this out!\nhttps://youtube.com/watch?v=vid-1"
    assert sent["embed"] is None
    assert sent["suppress_embeds"] is False  # embed_enabled=True -> allow Discord's own link preview


async def test_custom_message_with_embed_disabled_suppresses_the_native_link_preview(harness: Harness) -> None:
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["custom_message"] = "Check this out!\n{url}"
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["embed_enabled"] = False

    await harness.sender.handle(_event())

    sent = channel.sent[0]
    assert sent["embed"] is None
    assert sent["suppress_embeds"] is True


async def test_custom_messages_literal_everyone_actually_allows_the_mention(harness: Harness) -> None:
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["custom_message"] = "Hey @everyone!"

    await harness.sender.handle(_event())

    assert channel.sent[0]["allowed_mentions"].everyone is True


async def test_custom_message_without_everyone_does_not_allow_the_mention(harness: Harness) -> None:
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["custom_message"] = "New post from {creator}"

    await harness.sender.handle(_event())

    assert channel.sent[0]["allowed_mentions"].everyone is False


async def test_custom_message_title_cannot_inject_a_real_everyone_mention(harness: Harness) -> None:
    """A malicious/weird video title containing literal "@everyone" text
    must not be able to trigger a real mention just by being substituted
    into the template — only the admin's own typed text can do that."""
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["custom_message"] = "New post: {title}"

    await harness.sender.handle(_event(title="please @everyone watch this"))

    sent = channel.sent[0]
    assert "@everyone" not in sent["content"]
    assert sent["allowed_mentions"].everyone is False


async def test_custom_message_mention_placeholder_uses_the_configured_role(harness: Harness) -> None:
    channel = await harness.add_channel(1, "acc-1", 555)
    await harness.alert_repo.seed_defaults(1, "acc-1", ["video_published"])
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["custom_message"] = "{mention} new post!"
    harness.db.tables["pulsenotify_alert_configurations"].rows[0]["mention_role_id"] = 999999999999999999

    await harness.sender.handle(_event())

    sent = channel.sent[0]
    assert "<@&999999999999999999>" in sent["content"]
    assert sent["allowed_mentions"].roles == [discord.Object(id=999999999999999999)]


async def test_no_channels_configured_sends_nothing_and_does_not_raise(harness: Harness) -> None:
    await harness.sender.handle(_event())  # no add_channel() call at all


async def test_sends_to_every_linked_channel(harness: Harness) -> None:
    channel_a = await harness.add_channel(1, "acc-1", 111)
    channel_b = await harness.add_channel(1, "acc-1", 222)

    await harness.sender.handle(_event())

    assert len(channel_a.sent) == 1
    assert len(channel_b.sent) == 1


async def test_forbidden_on_send_marks_the_channel_invalid(harness: Harness) -> None:
    row = await harness.channel_repo.get_or_create(1, 555)
    await harness.channel_repo.link_account(1, "acc-1", row["id"])
    channel = FakeDiscordChannel(555, raise_on_send=_fake_http_exception(discord.Forbidden, status=403))
    harness.bot.cache(channel)

    await harness.sender.handle(_event())  # must not raise

    updated = await harness.channel_repo.get_by_discord_channel(1, 555)
    assert updated is not None
    assert updated["is_valid"] is False


async def test_not_found_on_send_marks_the_channel_invalid(harness: Harness) -> None:
    row = await harness.channel_repo.get_or_create(1, 555)
    await harness.channel_repo.link_account(1, "acc-1", row["id"])
    channel = FakeDiscordChannel(555, raise_on_send=_fake_http_exception(discord.NotFound, status=404))
    harness.bot.cache(channel)

    await harness.sender.handle(_event())  # must not raise

    updated = await harness.channel_repo.get_by_discord_channel(1, 555)
    assert updated is not None
    assert updated["is_valid"] is False


async def test_generic_http_exception_on_send_does_not_mark_invalid(harness: Harness) -> None:
    row = await harness.channel_repo.get_or_create(1, 555)
    await harness.channel_repo.link_account(1, "acc-1", row["id"])
    channel = FakeDiscordChannel(555, raise_on_send=_fake_http_exception(discord.HTTPException, status=500))
    harness.bot.cache(channel)

    await harness.sender.handle(_event())  # must not raise

    updated = await harness.channel_repo.get_by_discord_channel(1, 555)
    assert updated is not None
    assert updated["is_valid"] is True  # a transient server error isn't "gone"


async def test_channel_not_in_cache_falls_back_to_fetch(harness: Harness) -> None:
    row = await harness.channel_repo.get_or_create(1, 555)
    await harness.channel_repo.link_account(1, "acc-1", row["id"])
    channel = FakeDiscordChannel(555)
    harness.bot.make_fetch_only(channel)  # not cached — forces fetch_channel()

    await harness.sender.handle(_event())

    assert len(channel.sent) == 1


async def test_channel_that_cannot_be_fetched_is_marked_invalid(harness: Harness) -> None:
    row = await harness.channel_repo.get_or_create(1, 555)
    await harness.channel_repo.link_account(1, "acc-1", row["id"])
    # Neither cached nor fetchable -> FakeBot.fetch_channel raises NotFound.

    await harness.sender.handle(_event())  # must not raise

    updated = await harness.channel_repo.get_by_discord_channel(1, 555)
    assert updated is not None
    assert updated["is_valid"] is False
