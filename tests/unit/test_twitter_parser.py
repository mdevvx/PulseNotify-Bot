"""Pure parsing logic — no HTTP, no adapter state. Fixture JSON shapes
mirror the real X API v2 response shapes documented at docs.x.com."""

from __future__ import annotations

from events.models import EventType
from platforms.base import AccountRef
from platforms.twitter import parser


# ── parse_identifier ────────────────────────────────────────────────────


def test_parse_identifier_strips_a_leading_at_sign() -> None:
    assert parser.parse_identifier("@SomeUser") == "SomeUser"


def test_parse_identifier_leaves_a_bare_handle_alone() -> None:
    assert parser.parse_identifier("SomeUser") == "SomeUser"


def test_parse_identifier_parses_an_x_dot_com_url() -> None:
    assert parser.parse_identifier("https://x.com/SomeUser") == "SomeUser"


def test_parse_identifier_parses_a_legacy_twitter_dot_com_url() -> None:
    assert parser.parse_identifier("https://twitter.com/SomeUser") == "SomeUser"


def test_parse_identifier_strips_trailing_path_and_query_from_url() -> None:
    assert parser.parse_identifier("https://x.com/SomeUser/status/123?s=20") == "SomeUser"


def test_parse_identifier_strips_surrounding_whitespace() -> None:
    assert parser.parse_identifier("  SomeUser  ") == "SomeUser"


# ── user_to_account_ref ──────────────────────────────────────────────────


def test_user_to_account_ref_prefers_display_name() -> None:
    user = {"id": "123", "username": "someuser", "name": "Some User"}
    ref = parser.user_to_account_ref(user)
    assert ref.platform == "twitter"
    assert ref.platform_account_id == "123"
    assert ref.username == "Some User"


def test_user_to_account_ref_falls_back_to_handle_without_a_name() -> None:
    user = {"id": "123", "username": "someuser"}
    ref = parser.user_to_account_ref(user)
    assert ref.username == "someuser"


# ── normalize_tweet ─────────────────────────────────────────────────────

_ACCOUNT = AccountRef(platform="twitter", platform_account_id="123", username="Some User")


def test_normalize_tweet_produces_post_created() -> None:
    tweet = {"id": "999", "text": "hello world", "created_at": "2026-09-15T12:00:00.000Z"}
    event = parser.normalize_tweet(_ACCOUNT, tweet)
    assert event.event_type == EventType.POST_CREATED
    assert event.platform_event_id == "999"
    assert event.description == "hello world"


def test_normalize_tweet_builds_the_handle_less_permalink() -> None:
    tweet = {"id": "999", "text": "hello world"}
    event = parser.normalize_tweet(_ACCOUNT, tweet)
    assert event.url == "https://x.com/i/web/status/999"


def test_normalize_tweet_parses_created_at() -> None:
    tweet = {"id": "999", "text": "hi", "created_at": "2026-09-15T12:00:00.000Z"}
    event = parser.normalize_tweet(_ACCOUNT, tweet)
    assert event.published_at is not None


def test_normalize_tweet_handles_missing_created_at() -> None:
    tweet = {"id": "999", "text": "hi"}
    event = parser.normalize_tweet(_ACCOUNT, tweet)
    assert event.published_at is None
