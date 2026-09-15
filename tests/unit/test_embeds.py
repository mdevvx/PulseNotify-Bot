"""Embed/plain-text builders — pure functions, no Discord API or DB needed."""

from __future__ import annotations

import discord

from events.models import EventType, NormalizedEvent
from notifications.embeds import build_embed, build_plain_text


def _event(event_type: EventType, **overrides) -> NormalizedEvent:
    fields = dict(
        platform="youtube",
        platform_account_id="UCabc",
        account_username="Example Creator",
        event_type=event_type,
        platform_event_id="vid1",
        title="A great video",
        url="https://youtube.com/watch?v=vid1",
    )
    fields.update(overrides)
    return NormalizedEvent(**fields)


def test_video_published_embed() -> None:
    embed = build_embed(_event(EventType.VIDEO_PUBLISHED))
    assert embed.title == "🆕 New Video"
    assert embed.url == "https://youtube.com/watch?v=vid1"
    assert embed.author.name == "Example Creator"


def test_short_published_embed_has_its_own_title() -> None:
    embed = build_embed(_event(EventType.SHORT_PUBLISHED))
    assert embed.title == "🆕 New Short"


def test_stream_started_embed_includes_category_and_viewers() -> None:
    embed = build_embed(
        _event(EventType.STREAM_STARTED, metadata={"category": "Just Chatting", "viewer_count": 12450})
    )
    assert embed.title == "🔴 LIVE NOW"
    field_map = {f.name: f.value for f in embed.fields}
    assert field_map["🎮 Category"] == "Just Chatting"
    assert field_map["👥 Viewers"] == "12,450"


def test_stream_started_embed_omits_fields_when_data_is_missing() -> None:
    embed = build_embed(_event(EventType.STREAM_STARTED, metadata={}))
    assert embed.fields == []


def test_stream_ended_embed_does_not_need_a_title_or_url() -> None:
    embed = build_embed(_event(EventType.STREAM_ENDED, title=None, url=None))
    assert "ended" in embed.description.lower()


def test_unknown_event_type_falls_back_to_generic_embed() -> None:
    embed = build_embed(_event(EventType.ACCOUNT_UPDATED))
    assert embed.title == "🆕 New Update"


def test_long_description_is_truncated() -> None:
    embed = build_embed(_event(EventType.VIDEO_PUBLISHED, title="x" * 500))
    assert len(embed.description) <= 300
    assert embed.description.endswith("…")


def test_embed_is_a_real_discord_embed_instance() -> None:
    embed = build_embed(_event(EventType.VIDEO_PUBLISHED))
    assert isinstance(embed, discord.Embed)


# ── plain text fallback ────────────────────────────────────────────────────


def test_plain_text_includes_title_and_url() -> None:
    text = build_plain_text(_event(EventType.VIDEO_PUBLISHED))
    assert "A great video" in text
    assert "https://youtube.com/watch?v=vid1" in text


def test_plain_text_stream_started_has_no_trailing_url_when_missing() -> None:
    text = build_plain_text(_event(EventType.STREAM_STARTED, url=None))
    assert text.count("\n") == 0


def test_plain_text_stream_ended_mentions_the_creator() -> None:
    text = build_plain_text(_event(EventType.STREAM_ENDED))
    assert "Example Creator" in text
    assert "ended" in text.lower()
