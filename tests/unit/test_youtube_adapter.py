"""YouTubeAdapter's own logic: the cursor/baseline behavior for
fetch_updates, caching the uploads playlist ID, and the live-search daily
budget gate — driven through a fake YouTubeClient (not real HTTP; that's
covered separately in test_youtube_client.py)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from platforms.base import AccountRef
from platforms.youtube.adapter import YouTubeAdapter

_ACCOUNT = AccountRef(platform="youtube", platform_account_id="UCabc", username="example")

_CHANNEL = {
    "id": "UCabc",
    "snippet": {"title": "Example", "customUrl": "@example"},
    "contentDetails": {"relatedPlaylists": {"uploads": "UUabc"}},
}


def _playlist_item(video_id: str) -> Dict[str, Any]:
    return {"snippet": {"resourceId": {"videoId": video_id}, "publishedAt": "2026-09-15T00:00:00Z"}}


def _video(video_id: str, duration: str = "PT10M0S") -> Dict[str, Any]:
    return {
        "id": video_id,
        "snippet": {"title": video_id, "thumbnails": {}},
        "contentDetails": {"duration": duration},
    }


class FakeYouTubeClient:
    def __init__(self) -> None:
        self.channel: Optional[Dict[str, Any]] = _CHANNEL
        self.uploads: List[Dict[str, Any]] = []
        self.videos_by_id: Dict[str, Dict[str, Any]] = {}
        self.live_search_results: List[Dict[str, Any]] = []
        self.get_channel_calls = 0
        self.list_uploads_calls = 0
        self.search_live_calls = 0

    async def get_channel(self, *, channel_id=None, handle=None, username=None):
        self.get_channel_calls += 1
        return self.channel

    async def list_uploads(self, uploads_playlist_id: str, *, max_results: int = 10):
        self.list_uploads_calls += 1
        return self.uploads[:max_results]

    async def get_videos(self, video_ids: List[str]):
        return [self.videos_by_id[vid] for vid in video_ids if vid in self.videos_by_id]

    async def search_live(self, channel_id: str):
        self.search_live_calls += 1
        return self.live_search_results


def _make_adapter(client: FakeYouTubeClient, **kwargs) -> YouTubeAdapter:
    defaults = {"daily_quota_units": 10_000, "live_search_daily_budget_units": 8_000}
    defaults.update(kwargs)
    return YouTubeAdapter(client, **defaults)  # type: ignore[arg-type]


async def test_first_poll_establishes_a_baseline_without_emitting_events() -> None:
    client = FakeYouTubeClient()
    client.uploads = [_playlist_item("vid-3"), _playlist_item("vid-2"), _playlist_item("vid-1")]
    adapter = _make_adapter(client)

    result = await adapter.fetch_updates(_ACCOUNT, cursor=None)

    assert result.items == []
    assert result.next_cursor == "vid-3"


async def test_subsequent_poll_returns_only_items_newer_than_the_cursor() -> None:
    client = FakeYouTubeClient()
    client.uploads = [_playlist_item("vid-3"), _playlist_item("vid-2"), _playlist_item("vid-1")]
    client.videos_by_id = {"vid-3": _video("vid-3"), "vid-2": _video("vid-2")}
    adapter = _make_adapter(client)

    result = await adapter.fetch_updates(_ACCOUNT, cursor="vid-1")

    assert {v["id"] for v in result.items} == {"vid-2", "vid-3"}
    assert result.next_cursor == "vid-3"


async def test_no_new_items_returns_empty_and_keeps_the_cursor_fresh() -> None:
    client = FakeYouTubeClient()
    client.uploads = [_playlist_item("vid-1")]
    adapter = _make_adapter(client)

    result = await adapter.fetch_updates(_ACCOUNT, cursor="vid-1")

    assert result.items == []
    assert result.next_cursor == "vid-1"


async def test_missing_channel_raises_permanent_error() -> None:
    from utils.errors import PermanentPlatformError

    client = FakeYouTubeClient()
    client.channel = None
    adapter = _make_adapter(client)

    with pytest.raises(PermanentPlatformError):
        await adapter.fetch_updates(_ACCOUNT, cursor=None)


async def test_uploads_playlist_id_is_cached_after_the_first_lookup() -> None:
    client = FakeYouTubeClient()
    client.uploads = [_playlist_item("vid-1")]
    adapter = _make_adapter(client)

    await adapter.fetch_updates(_ACCOUNT, cursor=None)
    await adapter.fetch_updates(_ACCOUNT, cursor="vid-1")
    await adapter.fetch_updates(_ACCOUNT, cursor="vid-1")

    assert client.get_channel_calls == 1  # not once per poll


async def test_live_search_returns_offline_when_nothing_is_live() -> None:
    client = FakeYouTubeClient()
    client.live_search_results = []
    adapter = _make_adapter(client)

    status = await adapter.get_live_status(_ACCOUNT)

    assert status is not None
    assert status.is_live is False


async def test_live_search_returns_live_status_for_an_active_broadcast() -> None:
    client = FakeYouTubeClient()
    client.live_search_results = [{"id": {"videoId": "live-1"}}]
    client.videos_by_id = {
        "live-1": {
            "id": "live-1",
            "snippet": {"liveBroadcastContent": "live", "title": "Live now"},
            "liveStreamingDetails": {"concurrentViewers": "42"},
        }
    }
    adapter = _make_adapter(client)

    status = await adapter.get_live_status(_ACCOUNT)

    assert status is not None
    assert status.is_live is True
    assert status.viewer_count == 42


async def test_live_search_is_skipped_once_the_daily_budget_is_exhausted() -> None:
    # 200 units of budget = exactly 2 search.list calls (100 units each).
    client = FakeYouTubeClient()
    adapter = _make_adapter(client, live_search_daily_budget_units=200)

    await adapter.get_live_status(_ACCOUNT)
    await adapter.get_live_status(_ACCOUNT)
    third = await adapter.get_live_status(_ACCOUNT)

    assert third is None  # skipped, not an error
    assert client.search_live_calls == 2
