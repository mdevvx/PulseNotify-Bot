"""Builds Discord embeds (and a plain-text fallback for when embeds are
disabled) from a NormalizedEvent, matching the mockups in section 11.

Pure functions — no Discord API calls, no DB access — so they're testable
against a plain NormalizedEvent without any bot/network setup.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

import discord

from config import constants
from events.models import EventType, NormalizedEvent

_MAX_DESCRIPTION_LENGTH = 300


def build_embed(event: NormalizedEvent) -> discord.Embed:
    builder = _EMBED_BUILDERS.get(event.event_type, _build_generic)
    return builder(event)


def build_plain_text(event: NormalizedEvent) -> str:
    """Used instead of build_embed() when the account's alert config has
    embeds disabled (section 35's "Embed enabled/disabled" option)."""
    builder = _TEXT_BUILDERS.get(event.event_type, _text_generic)
    return builder(event)


def _build_video(event: NormalizedEvent) -> discord.Embed:
    embed = discord.Embed(
        title="🆕 New Video",
        description=_truncate(event.title),
        url=event.url,
        color=discord.Color(constants.COLOR_INFO),
        timestamp=event.published_at,
    )
    embed.set_author(name=event.account_username)
    if event.thumbnail_url:
        embed.set_image(url=event.thumbnail_url)
    embed.set_footer(text=event.platform.title())
    return embed


def _build_short(event: NormalizedEvent) -> discord.Embed:
    embed = _build_video(event)
    embed.title = "🆕 New Short"
    return embed


def _build_post(event: NormalizedEvent) -> discord.Embed:
    embed = discord.Embed(
        title="🆕 New Post",
        description=_truncate(event.description or event.title),
        url=event.url,
        color=discord.Color(constants.COLOR_INFO),
        timestamp=event.published_at,
    )
    embed.set_author(name=event.account_username)
    if event.thumbnail_url:
        embed.set_thumbnail(url=event.thumbnail_url)
    embed.set_footer(text=event.platform.title())
    return embed


def _build_stream_started(event: NormalizedEvent) -> discord.Embed:
    embed = discord.Embed(
        title="🔴 LIVE NOW",
        description=f"**{event.account_username}** is now live!\n\n{_truncate(event.title)}".strip(),
        url=event.url,
        color=discord.Color(constants.COLOR_LIVE),
        timestamp=event.started_at,
    )
    category = event.metadata.get("category")
    viewers = event.metadata.get("viewer_count")
    if category:
        embed.add_field(name="🎮 Category", value=str(category), inline=True)
    if viewers is not None:
        embed.add_field(name="👥 Viewers", value=f"{viewers:,}", inline=True)
    if event.thumbnail_url:
        embed.set_image(url=event.thumbnail_url)
    embed.set_footer(text=event.platform.title())
    return embed


def _build_stream_ended(event: NormalizedEvent) -> discord.Embed:
    return discord.Embed(
        title="⚫ Stream Ended",
        description=f"**{event.account_username}**'s stream has ended.",
        color=discord.Color(constants.COLOR_INFO),
    )


def _build_generic(event: NormalizedEvent) -> discord.Embed:
    embed = discord.Embed(
        title="🆕 New Update",
        description=_truncate(event.title or event.description),
        url=event.url,
        color=discord.Color(constants.COLOR_INFO),
    )
    embed.set_author(name=event.account_username)
    embed.set_footer(text=event.platform.title())
    return embed


def _text_video(event: NormalizedEvent) -> str:
    return _join(f"🆕 **{event.account_username}** published a new video: {event.title or ''}".strip(), event.url)


def _text_short(event: NormalizedEvent) -> str:
    return _join(f"🆕 **{event.account_username}** published a new Short: {event.title or ''}".strip(), event.url)


def _text_post(event: NormalizedEvent) -> str:
    return _join(f"🆕 **{event.account_username}** posted: {event.title or event.description or ''}".strip(), event.url)


def _text_stream_started(event: NormalizedEvent) -> str:
    return _join(f"🔴 **{event.account_username}** is now live! {event.title or ''}".strip(), event.url)


def _text_stream_ended(event: NormalizedEvent) -> str:
    return f"⚫ **{event.account_username}**'s stream has ended."


def _text_generic(event: NormalizedEvent) -> str:
    return _join(f"🆕 **{event.account_username}** has an update: {event.title or ''}".strip(), event.url)


def _join(text: str, url: Optional[str]) -> str:
    return f"{text}\n{url}" if url else text


def _truncate(text: Optional[str]) -> str:
    if not text:
        return ""
    if len(text) <= _MAX_DESCRIPTION_LENGTH:
        return text
    return text[: _MAX_DESCRIPTION_LENGTH - 1].rstrip() + "…"


_EMBED_BUILDERS: Dict[EventType, Callable[[NormalizedEvent], discord.Embed]] = {
    EventType.VIDEO_PUBLISHED: _build_video,
    EventType.SHORT_PUBLISHED: _build_short,
    EventType.POST_CREATED: _build_post,
    EventType.STREAM_STARTED: _build_stream_started,
    EventType.STREAM_ENDED: _build_stream_ended,
}

_TEXT_BUILDERS: Dict[EventType, Callable[[NormalizedEvent], str]] = {
    EventType.VIDEO_PUBLISHED: _text_video,
    EventType.SHORT_PUBLISHED: _text_short,
    EventType.POST_CREATED: _text_post,
    EventType.STREAM_STARTED: _text_stream_started,
    EventType.STREAM_ENDED: _text_stream_ended,
}
