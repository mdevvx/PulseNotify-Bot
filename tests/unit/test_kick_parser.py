"""Pure parsing logic — no HTTP, no adapter state. Fixture JSON shapes
mirror the real Kick Public API response shapes documented at
docs.kick.com/apis/channels."""

from __future__ import annotations

from platforms.kick import parser


# ── parse_identifier ────────────────────────────────────────────────────


def test_parse_identifier_lowercases_a_bare_slug() -> None:
    assert parser.parse_identifier("SomeStreamer") == "somestreamer"


def test_parse_identifier_strips_a_leading_at_sign() -> None:
    assert parser.parse_identifier("@SomeStreamer") == "somestreamer"


def test_parse_identifier_parses_a_channel_url() -> None:
    assert parser.parse_identifier("https://www.kick.com/SomeStreamer") == "somestreamer"


def test_parse_identifier_parses_a_bare_domain_url() -> None:
    assert parser.parse_identifier("https://kick.com/somestreamer") == "somestreamer"


def test_parse_identifier_strips_trailing_path_and_query_from_url() -> None:
    assert parser.parse_identifier("https://kick.com/somestreamer/videos?filter=all") == "somestreamer"


def test_parse_identifier_strips_surrounding_whitespace() -> None:
    assert parser.parse_identifier("  somestreamer  ") == "somestreamer"


# ── channel_to_account_ref ────────────────────────────────────────────────


def test_channel_to_account_ref_uses_the_stable_numeric_id() -> None:
    channel = {"broadcaster_user_id": 12345, "slug": "somestreamer"}
    ref = parser.channel_to_account_ref(channel)
    assert ref.platform == "kick"
    assert ref.platform_account_id == "12345"
    assert ref.username == "somestreamer"


def test_channel_to_account_ref_falls_back_to_id_without_a_slug() -> None:
    channel = {"broadcaster_user_id": 12345, "slug": ""}
    ref = parser.channel_to_account_ref(channel)
    assert ref.username == "12345"


# ── channel_to_live_status ─────────────────────────────────────────────────


def _channel(**overrides) -> dict:
    channel = {
        "broadcaster_user_id": 12345,
        "slug": "somestreamer",
        "stream_title": "Playing games",
        "category": {"id": 1, "name": "Just Chatting"},
        "stream": {
            "is_live": True,
            "viewer_count": 1234,
            "start_time": "2026-09-15T10:00:00Z",
            "url": "https://kick.com/somestreamer",
            "thumbnail": "https://example.com/thumb.jpg",
        },
    }
    channel.update(overrides)
    return channel


def test_channel_to_live_status_detects_live() -> None:
    status = parser.channel_to_live_status(_channel())
    assert status.is_live is True
    assert status.stream_id is None  # Kick exposes no per-session stream ID


def test_channel_to_live_status_offline_when_stream_missing() -> None:
    status = parser.channel_to_live_status(_channel(stream=None))
    assert status.is_live is False


def test_channel_to_live_status_offline_when_is_live_false() -> None:
    status = parser.channel_to_live_status(_channel(stream={"is_live": False}))
    assert status.is_live is False


def test_channel_to_live_status_maps_category_and_title() -> None:
    status = parser.channel_to_live_status(_channel())
    assert status.title == "Playing games"
    assert status.category == "Just Chatting"


def test_channel_to_live_status_parses_viewer_count() -> None:
    status = parser.channel_to_live_status(_channel())
    assert status.viewer_count == 1234


def test_channel_to_live_status_parses_started_at() -> None:
    status = parser.channel_to_live_status(_channel())
    assert status.started_at is not None


def test_channel_to_live_status_uses_the_streams_own_url() -> None:
    status = parser.channel_to_live_status(_channel())
    assert status.url == "https://kick.com/somestreamer"


def test_channel_to_live_status_builds_url_from_slug_if_stream_url_missing() -> None:
    channel = _channel()
    channel["stream"] = {**channel["stream"], "url": None}
    status = parser.channel_to_live_status(channel)
    assert status.url == "https://kick.com/somestreamer"


def test_channel_to_live_status_handles_missing_category() -> None:
    status = parser.channel_to_live_status(_channel(category=None))
    assert status.category is None
