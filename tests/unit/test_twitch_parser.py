"""Pure parsing logic — no HTTP, no adapter state. Fixture JSON shapes
mirror the real Twitch Helix API response shapes documented at
dev.twitch.tv/docs/api/reference."""

from __future__ import annotations

from platforms.twitch import parser


# ── parse_identifier ────────────────────────────────────────────────────


def test_parse_identifier_lowercases_a_bare_login() -> None:
    assert parser.parse_identifier("SomeStreamer") == "somestreamer"


def test_parse_identifier_strips_a_leading_at_sign() -> None:
    assert parser.parse_identifier("@SomeStreamer") == "somestreamer"


def test_parse_identifier_parses_a_channel_url() -> None:
    assert parser.parse_identifier("https://www.twitch.tv/SomeStreamer") == "somestreamer"


def test_parse_identifier_parses_a_bare_domain_url() -> None:
    assert parser.parse_identifier("https://twitch.tv/somestreamer") == "somestreamer"


def test_parse_identifier_strips_trailing_path_and_query_from_url() -> None:
    assert parser.parse_identifier("https://www.twitch.tv/somestreamer/videos?filter=all") == "somestreamer"


def test_parse_identifier_strips_surrounding_whitespace() -> None:
    assert parser.parse_identifier("  somestreamer  ") == "somestreamer"


# ── user_to_account_ref ──────────────────────────────────────────────────


def test_user_to_account_ref_prefers_display_name() -> None:
    user = {"id": "12345", "login": "somestreamer", "display_name": "SomeStreamer"}
    ref = parser.user_to_account_ref(user)
    assert ref.platform == "twitch"
    assert ref.platform_account_id == "12345"
    assert ref.username == "SomeStreamer"


def test_user_to_account_ref_falls_back_to_login_without_display_name() -> None:
    user = {"id": "12345", "login": "somestreamer"}
    ref = parser.user_to_account_ref(user)
    assert ref.username == "somestreamer"


# ── stream_to_live_status ─────────────────────────────────────────────────


def _stream(**overrides) -> dict:
    stream = {
        "id": "stream-1",
        "user_login": "somestreamer",
        "title": "Playing games",
        "game_name": "Just Chatting",
        "viewer_count": "1234",
        "started_at": "2026-09-15T10:00:00Z",
        "thumbnail_url": "https://static-cdn.jtvnw.net/previews-ttv/live_user_somestreamer-{width}x{height}.jpg",
    }
    stream.update(overrides)
    return stream


def test_stream_to_live_status_is_always_live() -> None:
    status = parser.stream_to_live_status(_stream())
    assert status.is_live is True
    assert status.stream_id == "stream-1"


def test_stream_to_live_status_maps_category_and_title() -> None:
    status = parser.stream_to_live_status(_stream())
    assert status.title == "Playing games"
    assert status.category == "Just Chatting"


def test_stream_to_live_status_parses_viewer_count_from_string() -> None:
    status = parser.stream_to_live_status(_stream(viewer_count="42"))
    assert status.viewer_count == 42


def test_stream_to_live_status_parses_started_at() -> None:
    status = parser.stream_to_live_status(_stream())
    assert status.started_at is not None


def test_stream_to_live_status_builds_the_channel_url_from_user_login() -> None:
    status = parser.stream_to_live_status(_stream(user_login="somestreamer"))
    assert status.url == "https://twitch.tv/somestreamer"


def test_stream_to_live_status_substitutes_thumbnail_dimensions() -> None:
    status = parser.stream_to_live_status(_stream())
    assert "{width}" not in status.thumbnail_url
    assert "{height}" not in status.thumbnail_url
    assert "1280" in status.thumbnail_url


def test_stream_to_live_status_handles_missing_game_name() -> None:
    status = parser.stream_to_live_status(_stream(game_name=""))
    assert status.category is None
