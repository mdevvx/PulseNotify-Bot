"""Pure parsing logic — no HTTP, no adapter state. Fixture JSON shapes
mirror the real YouTube Data API v3 response shapes documented at
developers.google.com/youtube/v3/docs."""

from __future__ import annotations

from events.models import EventType
from platforms.base import AccountRef
from platforms.youtube import parser


# ── parse_identifier ────────────────────────────────────────────────────


def test_parse_identifier_accepts_a_raw_channel_id() -> None:
    kind, value = parser.parse_identifier("UCX6OQ3DkcsbYNE6H8uQQuVA")
    assert (kind, value) == ("id", "UCX6OQ3DkcsbYNE6H8uQQuVA")


def test_parse_identifier_accepts_a_handle_with_at_sign() -> None:
    assert parser.parse_identifier("@SomeCreator") == ("handle", "@SomeCreator")


def test_parse_identifier_adds_at_sign_to_a_bare_handle() -> None:
    assert parser.parse_identifier("SomeCreator") == ("handle", "@SomeCreator")


def test_parse_identifier_parses_a_channel_url() -> None:
    kind, value = parser.parse_identifier("https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA")
    assert (kind, value) == ("id", "UCX6OQ3DkcsbYNE6H8uQQuVA")


def test_parse_identifier_parses_a_handle_url() -> None:
    assert parser.parse_identifier("https://www.youtube.com/@SomeCreator") == ("handle", "@SomeCreator")


def test_parse_identifier_parses_a_legacy_username_url() -> None:
    assert parser.parse_identifier("https://youtube.com/user/OldStyleName") == ("username", "OldStyleName")


def test_parse_identifier_parses_a_legacy_custom_url_as_a_handle() -> None:
    assert parser.parse_identifier("https://www.youtube.com/c/SomeCreator") == ("handle", "@SomeCreator")


def test_parse_identifier_strips_query_string_from_url() -> None:
    assert parser.parse_identifier("https://www.youtube.com/@SomeCreator?sub_confirmation=1") == (
        "handle",
        "@SomeCreator",
    )


# ── normalize_video ──────────────────────────────────────────────────────

_ACCOUNT = AccountRef(platform="youtube", platform_account_id="UCabc", username="example")


def _video(duration: str = "PT10M0S", **overrides) -> dict:
    video = {
        "id": "vid123",
        "snippet": {
            "title": "A video",
            "description": "desc",
            "channelTitle": "Example",
            "publishedAt": "2026-09-15T12:00:00Z",
            "thumbnails": {"high": {"url": "https://example.com/high.jpg"}},
        },
        "contentDetails": {"duration": duration},
    }
    video.update(overrides)
    return video


def test_normalize_video_produces_video_published_for_a_long_video() -> None:
    event = parser.normalize_video(_ACCOUNT, _video(duration="PT10M0S"))
    assert event.event_type == EventType.VIDEO_PUBLISHED
    assert event.platform_event_id == "vid123"
    assert event.url == "https://www.youtube.com/watch?v=vid123"


def test_normalize_video_flags_a_short_video_as_short_published() -> None:
    event = parser.normalize_video(_ACCOUNT, _video(duration="PT45S"))
    assert event.event_type == EventType.SHORT_PUBLISHED
    assert event.metadata["is_short_heuristic"] is True


def test_normalize_video_boundary_at_exactly_60_seconds_is_a_short() -> None:
    event = parser.normalize_video(_ACCOUNT, _video(duration="PT1M0S"))
    assert event.event_type == EventType.SHORT_PUBLISHED


def test_normalize_video_61_seconds_is_not_a_short() -> None:
    event = parser.normalize_video(_ACCOUNT, _video(duration="PT1M1S"))
    assert event.event_type == EventType.VIDEO_PUBLISHED


def test_normalize_video_picks_the_highest_available_thumbnail() -> None:
    video = _video()
    video["snippet"]["thumbnails"] = {
        "default": {"url": "d"},
        "medium": {"url": "m"},
        "maxres": {"url": "best"},
    }
    event = parser.normalize_video(_ACCOUNT, video)
    assert event.thumbnail_url == "best"


def test_normalize_video_missing_duration_defaults_to_regular_video() -> None:
    video = _video()
    del video["contentDetails"]["duration"]
    event = parser.normalize_video(_ACCOUNT, video)
    assert event.event_type == EventType.VIDEO_PUBLISHED
    assert event.metadata["duration_seconds"] is None


# ── video_to_live_status ──────────────────────────────────────────────────


def test_video_to_live_status_detects_currently_live() -> None:
    video = {
        "id": "vid-live",
        "snippet": {"liveBroadcastContent": "live", "title": "Live now", "thumbnails": {}},
        "liveStreamingDetails": {"actualStartTime": "2026-09-15T10:00:00Z", "concurrentViewers": "1234"},
    }
    status = parser.video_to_live_status(video)
    assert status.is_live is True
    assert status.viewer_count == 1234
    assert status.started_at is not None


def test_video_to_live_status_upcoming_is_not_live() -> None:
    video = {"id": "vid-upcoming", "snippet": {"liveBroadcastContent": "upcoming"}, "liveStreamingDetails": {}}
    status = parser.video_to_live_status(video)
    assert status.is_live is False


def test_video_to_live_status_none_is_not_live() -> None:
    video = {"id": "vid-plain", "snippet": {"liveBroadcastContent": "none"}, "liveStreamingDetails": {}}
    status = parser.video_to_live_status(video)
    assert status.is_live is False


def test_video_to_live_status_handles_missing_viewer_count() -> None:
    video = {"id": "vid-live", "snippet": {"liveBroadcastContent": "live"}, "liveStreamingDetails": {}}
    status = parser.video_to_live_status(video)
    assert status.viewer_count is None


def test_video_to_live_status_builds_the_watch_url() -> None:
    video = {"id": "vid-live", "snippet": {"liveBroadcastContent": "live"}, "liveStreamingDetails": {}}
    status = parser.video_to_live_status(video)
    assert status.url == "https://www.youtube.com/watch?v=vid-live"


# ── duration parsing ──────────────────────────────────────────────────────


def test_duration_parses_hours_minutes_seconds() -> None:
    assert parser._parse_iso8601_duration("PT1H2M3S") == 3723


def test_duration_parses_seconds_only() -> None:
    assert parser._parse_iso8601_duration("PT45S") == 45


def test_duration_parses_minutes_only() -> None:
    assert parser._parse_iso8601_duration("PT5M") == 300


def test_duration_returns_none_for_missing_value() -> None:
    assert parser._parse_iso8601_duration(None) is None


def test_duration_returns_none_for_unparseable_value() -> None:
    assert parser._parse_iso8601_duration("garbage") is None


# ── uploads playlist / account ref ────────────────────────────────────────


def test_uploads_playlist_id_extracts_the_nested_field() -> None:
    channel = {"contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}}}
    assert parser.uploads_playlist_id(channel) == "UUabc"


def test_uploads_playlist_id_returns_none_when_absent() -> None:
    assert parser.uploads_playlist_id({"contentDetails": {}}) is None


def test_channel_to_account_ref_prefers_custom_url_then_title() -> None:
    channel = {"id": "UCabc", "snippet": {"customUrl": "@handle", "title": "Display Name"}}
    ref = parser.channel_to_account_ref(channel)
    assert ref.username == "@handle"

    channel_no_custom_url = {"id": "UCabc", "snippet": {"title": "Display Name"}}
    ref2 = parser.channel_to_account_ref(channel_no_custom_url)
    assert ref2.username == "Display Name"
