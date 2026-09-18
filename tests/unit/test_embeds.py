"""Plain-text notification builders — pure functions, no Discord API or DB
needed. There's no build_embed() here on purpose — see notifications/embeds.py's
module docstring for why every notification relies on Discord's own
link-unfurling instead of a hand-built embed."""

from __future__ import annotations

from events.models import EventType, NormalizedEvent
from notifications.embeds import build_plain_text


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
