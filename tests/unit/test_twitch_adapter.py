"""TwitchAdapter's own logic — resolving an identifier to an AccountRef and
mapping get_live_status onto TwitchClient, driven through a fake
TwitchClient (not real HTTP; that's covered separately in
test_twitch_client.py)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from platforms.base import AccountRef
from platforms.twitch.adapter import TwitchAdapter
from utils.errors import PermanentPlatformError

_ACCOUNT = AccountRef(platform="twitch", platform_account_id="12345", username="SomeStreamer")


class FakeTwitchClient:
    def __init__(self) -> None:
        self.user: Optional[Dict[str, Any]] = {"id": "12345", "login": "somestreamer", "display_name": "SomeStreamer"}
        self.stream: Optional[Dict[str, Any]] = None
        self.get_user_calls = 0
        self.get_stream_calls = 0

    async def get_user(self, *, login=None, user_id=None):
        self.get_user_calls += 1
        return self.user

    async def get_stream(self, user_id: str):
        self.get_stream_calls += 1
        return self.stream

    async def aclose(self) -> None:
        pass


async def test_validate_account_resolves_a_login_to_an_account_ref() -> None:
    client = FakeTwitchClient()
    adapter = TwitchAdapter(client)  # type: ignore[arg-type]

    ref = await adapter.validate_account("SomeStreamer")

    assert ref.platform == "twitch"
    assert ref.platform_account_id == "12345"
    assert ref.username == "SomeStreamer"


async def test_validate_account_raises_permanent_error_when_not_found() -> None:
    client = FakeTwitchClient()
    client.user = None
    adapter = TwitchAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(PermanentPlatformError):
        await adapter.validate_account("nonexistent")


async def test_get_live_status_returns_offline_when_no_active_stream() -> None:
    client = FakeTwitchClient()
    client.stream = None
    adapter = TwitchAdapter(client)  # type: ignore[arg-type]

    status = await adapter.get_live_status(_ACCOUNT)

    assert status is not None
    assert status.is_live is False


async def test_get_live_status_returns_live_status_for_an_active_stream() -> None:
    client = FakeTwitchClient()
    client.stream = {
        "id": "stream-1",
        "user_login": "somestreamer",
        "title": "Playing games",
        "game_name": "Just Chatting",
        "viewer_count": "42",
        "started_at": "2026-09-15T10:00:00Z",
        "thumbnail_url": "https://example.com/{width}x{height}.jpg",
    }
    adapter = TwitchAdapter(client)  # type: ignore[arg-type]

    status = await adapter.get_live_status(_ACCOUNT)

    assert status is not None
    assert status.is_live is True
    assert status.viewer_count == 42
    assert status.url == "https://twitch.tv/somestreamer"


async def test_get_live_status_queries_by_the_stable_platform_account_id() -> None:
    """Must use the numeric ID (stable across renames), not the username."""
    client = FakeTwitchClient()
    seen_user_id = None

    async def get_stream(user_id: str):
        nonlocal seen_user_id
        seen_user_id = user_id
        return None

    client.get_stream = get_stream  # type: ignore[assignment]
    adapter = TwitchAdapter(client)  # type: ignore[arg-type]

    await adapter.get_live_status(_ACCOUNT)

    assert seen_user_id == "12345"


async def test_fetch_updates_is_never_expected_to_be_called() -> None:
    """TwitchAdapter declares no content capability, so the worker never
    calls this — asserting it raises documents that contract."""
    client = FakeTwitchClient()
    adapter = TwitchAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError):
        await adapter.fetch_updates(_ACCOUNT, cursor=None)


async def test_normalize_event_is_never_expected_to_be_called() -> None:
    client = FakeTwitchClient()
    adapter = TwitchAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError):
        adapter.normalize_event(_ACCOUNT, {})
