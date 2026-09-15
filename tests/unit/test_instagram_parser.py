"""Pure parsing logic — no HTTP, no adapter state. Fixture JSON shapes
mirror the real Instagram Graph API business_discovery response shapes."""

from __future__ import annotations

from events.models import EventType
from platforms.base import AccountRef
from platforms.instagram import parser


# ── parse_identifier ────────────────────────────────────────────────────


def test_parse_identifier_lowercases_a_bare_username() -> None:
    assert parser.parse_identifier("SomeCreator") == "somecreator"


def test_parse_identifier_strips_a_leading_at_sign() -> None:
    assert parser.parse_identifier("@SomeCreator") == "somecreator"


def test_parse_identifier_parses_a_profile_url() -> None:
    assert parser.parse_identifier("https://www.instagram.com/SomeCreator") == "somecreator"


def test_parse_identifier_strips_trailing_path_and_query_from_url() -> None:
    assert parser.parse_identifier("https://instagram.com/somecreator/reels/?hl=en") == "somecreator"


def test_parse_identifier_strips_surrounding_whitespace() -> None:
    assert parser.parse_identifier("  somecreator  ") == "somecreator"


# ── discovery_to_account_ref ──────────────────────────────────────────────


def test_discovery_to_account_ref_uses_username_not_display_name() -> None:
    discovery = {"id": "17841400", "username": "somecreator", "name": "Some Creator Inc."}
    ref = parser.discovery_to_account_ref(discovery)
    assert ref.platform == "instagram"
    assert ref.platform_account_id == "17841400"
    assert ref.username == "somecreator"


def test_discovery_to_account_ref_falls_back_to_id_without_username() -> None:
    discovery = {"id": "17841400"}
    ref = parser.discovery_to_account_ref(discovery)
    assert ref.username == "17841400"


# ── normalize_media ─────────────────────────────────────────────────────

_ACCOUNT = AccountRef(platform="instagram", platform_account_id="17841400", username="somecreator")


def _media(**overrides) -> dict:
    media = {
        "id": "18000000000000000",
        "caption": "A great post",
        "timestamp": "2026-09-15T12:00:00+0000",
        "media_type": "IMAGE",
        "media_url": "https://example.com/media.jpg",
        "permalink": "https://www.instagram.com/p/abc123/",
    }
    media.update(overrides)
    return media


def test_normalize_media_produces_post_created() -> None:
    event = parser.normalize_media(_ACCOUNT, _media())
    assert event.event_type == EventType.POST_CREATED
    assert event.platform_event_id == "18000000000000000"
    assert event.url == "https://www.instagram.com/p/abc123/"


def test_normalize_media_carries_the_caption_as_description() -> None:
    event = parser.normalize_media(_ACCOUNT, _media(caption="hello"))
    assert event.description == "hello"


def test_normalize_media_records_media_type_in_metadata() -> None:
    event = parser.normalize_media(_ACCOUNT, _media(media_type="VIDEO"))
    assert event.metadata["media_type"] == "VIDEO"


def test_normalize_media_parses_the_timestamp() -> None:
    event = parser.normalize_media(_ACCOUNT, _media())
    assert event.published_at is not None


def test_normalize_media_handles_missing_timestamp() -> None:
    media = _media()
    del media["timestamp"]
    event = parser.normalize_media(_ACCOUNT, media)
    assert event.published_at is None
