"""KickAdapter's own logic — resolving an identifier to an AccountRef and
mapping get_live_status onto KickClient, driven through a fake KickClient
(not real HTTP; that's covered separately in test_kick_client.py)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from platforms.base import AccountRef
from platforms.kick.adapter import KickAdapter
from utils.errors import PermanentPlatformError

_ACCOUNT = AccountRef(platform="kick", platform_account_id="12345", username="somestreamer")


class FakeKickClient:
    def __init__(self) -> None:
        self.channel_by_slug: Optional[Dict[str, Any]] = {"broadcaster_user_id": 12345, "slug": "somestreamer"}
        self.channel_by_id: Optional[Dict[str, Any]] = None

    async def get_channel_by_slug(self, slug: str):
        return self.channel_by_slug

    async def get_channel_by_id(self, broadcaster_user_id: str):
        return self.channel_by_id

    async def aclose(self) -> None:
        pass


async def test_validate_account_resolves_a_slug_to_an_account_ref() -> None:
    client = FakeKickClient()
    adapter = KickAdapter(client)  # type: ignore[arg-type]

    ref = await adapter.validate_account("SomeStreamer")

    assert ref.platform == "kick"
    assert ref.platform_account_id == "12345"
    assert ref.username == "somestreamer"


async def test_validate_account_raises_permanent_error_when_not_found() -> None:
    client = FakeKickClient()
    client.channel_by_slug = None
    adapter = KickAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(PermanentPlatformError):
        await adapter.validate_account("nonexistent")


async def test_get_live_status_returns_offline_when_channel_not_found() -> None:
    client = FakeKickClient()
    client.channel_by_id = None
    adapter = KickAdapter(client)  # type: ignore[arg-type]

    status = await adapter.get_live_status(_ACCOUNT)

    assert status is not None
    assert status.is_live is False


async def test_get_live_status_returns_live_status_for_an_active_stream() -> None:
    client = FakeKickClient()
    client.channel_by_id = {
        "broadcaster_user_id": 12345,
        "slug": "somestreamer",
        "stream_title": "Playing games",
        "category": {"name": "Just Chatting"},
        "stream": {
            "is_live": True,
            "viewer_count": 42,
            "start_time": "2026-09-15T10:00:00Z",
            "url": "https://kick.com/somestreamer",
        },
    }
    adapter = KickAdapter(client)  # type: ignore[arg-type]

    status = await adapter.get_live_status(_ACCOUNT)

    assert status is not None
    assert status.is_live is True
    assert status.viewer_count == 42
    assert status.url == "https://kick.com/somestreamer"


async def test_get_live_status_queries_by_the_stable_platform_account_id() -> None:
    """Must use the numeric ID (stable across renames), not the slug."""
    client = FakeKickClient()
    seen_id = None

    async def get_channel_by_id(broadcaster_user_id: str):
        nonlocal seen_id
        seen_id = broadcaster_user_id
        return None

    client.get_channel_by_id = get_channel_by_id  # type: ignore[assignment]
    adapter = KickAdapter(client)  # type: ignore[arg-type]

    await adapter.get_live_status(_ACCOUNT)

    assert seen_id == "12345"


async def test_fetch_updates_is_never_expected_to_be_called() -> None:
    client = FakeKickClient()
    adapter = KickAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError):
        await adapter.fetch_updates(_ACCOUNT, cursor=None)


async def test_normalize_event_is_never_expected_to_be_called() -> None:
    client = FakeKickClient()
    adapter = KickAdapter(client)  # type: ignore[arg-type]

    with pytest.raises(NotImplementedError):
        adapter.normalize_event(_ACCOUNT, {})
