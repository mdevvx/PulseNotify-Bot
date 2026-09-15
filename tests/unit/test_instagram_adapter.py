"""InstagramAdapter's own logic — the cursor/baseline behavior for
fetch_updates (mirrors YouTubeAdapter's/TwitterAdapter's), plus the
by-username (not by-ID) re-query on every poll that Business Discovery
requires. Driven through a fake InstagramClient (not real HTTP; that's
covered separately in test_instagram_client.py)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from platforms.base import AccountRef
from platforms.instagram.adapter import InstagramAdapter
from utils.errors import PermanentPlatformError

_ACCOUNT = AccountRef(platform="instagram", platform_account_id="17841400", username="somecreator")


def _media(media_id: str) -> Dict[str, Any]:
    return {"id": media_id, "caption": f"post {media_id}"}


class FakeInstagramClient:
    def __init__(self) -> None:
        self.discovery: Optional[Dict[str, Any]] = {"id": "17841400", "username": "somecreator", "media": []}
        self.seen_usernames: List[str] = []

    async def get_business_discovery(self, username: str):
        self.seen_usernames.append(username)
        return self.discovery

    async def aclose(self) -> None:
        pass


async def test_validate_account_resolves_a_username_to_an_account_ref() -> None:
    client = FakeInstagramClient()
    adapter = InstagramAdapter(client)  # type: ignore[arg-type]

    ref = await adapter.validate_account("@SomeCreator")

    assert ref.platform == "instagram"
    assert ref.platform_account_id == "17841400"
    assert ref.username == "somecreator"


async def test_validate_account_raises_permanent_error_when_not_found() -> None:
    client = FakeInstagramClient()
    client.discovery = None
    adapter = InstagramAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(PermanentPlatformError):
        await adapter.validate_account("nonexistent")


async def test_fetch_updates_queries_by_username_not_by_id() -> None:
    """Business Discovery has no by-ID lookup — every poll must re-supply
    the account's username, not its stable platform_account_id."""
    client = FakeInstagramClient()
    adapter = InstagramAdapter(client)  # type: ignore[arg-type]

    await adapter.fetch_updates(_ACCOUNT, cursor=None)

    assert client.seen_usernames == ["somecreator"]


async def test_first_poll_establishes_a_baseline_without_emitting_events() -> None:
    client = FakeInstagramClient()
    client.discovery = {"id": "1", "username": "somecreator", "media": [_media("3"), _media("2"), _media("1")]}
    adapter = InstagramAdapter(client)  # type: ignore[arg-type]

    result = await adapter.fetch_updates(_ACCOUNT, cursor=None)

    assert result.items == []
    assert result.next_cursor == "3"


async def test_subsequent_poll_returns_only_items_newer_than_the_cursor() -> None:
    client = FakeInstagramClient()
    client.discovery = {"id": "1", "username": "somecreator", "media": [_media("3"), _media("2"), _media("1")]}
    adapter = InstagramAdapter(client)  # type: ignore[arg-type]

    result = await adapter.fetch_updates(_ACCOUNT, cursor="1")

    assert {m["id"] for m in result.items} == {"2", "3"}
    assert result.next_cursor == "3"


async def test_no_new_media_returns_empty_and_keeps_the_cursor() -> None:
    client = FakeInstagramClient()
    client.discovery = {"id": "1", "username": "somecreator", "media": [_media("1")]}
    adapter = InstagramAdapter(client)  # type: ignore[arg-type]

    result = await adapter.fetch_updates(_ACCOUNT, cursor="1")

    assert result.items == []
    assert result.next_cursor == "1"


async def test_fetch_updates_raises_permanent_error_when_account_no_longer_resolves() -> None:
    """E.g. the target renamed their handle, was deleted, or stopped being
    a professional account — a real, documented limitation of
    username-only lookup, not a transient glitch."""
    client = FakeInstagramClient()
    client.discovery = None
    adapter = InstagramAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(PermanentPlatformError):
        await adapter.fetch_updates(_ACCOUNT, cursor="1")


async def test_get_live_status_is_never_expected_to_be_called() -> None:
    client = FakeInstagramClient()
    adapter = InstagramAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError):
        await adapter.get_live_status(_ACCOUNT)
