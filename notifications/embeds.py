"""Builds the plain-text notification body from a NormalizedEvent.

No manually-built discord.Embed is used for these — every event carries a
raw link (except stream-ended), and Discord's own link-unfurling generates
a richer, platform-branded preview from it (e.g. YouTube's real
title/description/thumbnail with its own "YouTube" footer) than a hand-built
embed ever could; see notifications/sender.py's _build_message() for how
`embed_enabled` controls whether that native preview is allowed to render.

Pure functions — no Discord API calls, no DB access — so they're testable
against a plain NormalizedEvent without any bot/network setup.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from events.models import EventType, NormalizedEvent


def build_plain_text(event: NormalizedEvent) -> str:
    builder = _TEXT_BUILDERS.get(event.event_type, _text_generic)
    return builder(event)


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


_TEXT_BUILDERS: Dict[EventType, Callable[[NormalizedEvent], str]] = {
    EventType.VIDEO_PUBLISHED: _text_video,
    EventType.SHORT_PUBLISHED: _text_short,
    EventType.POST_CREATED: _text_post,
    EventType.STREAM_STARTED: _text_stream_started,
    EventType.STREAM_ENDED: _text_stream_ended,
}
