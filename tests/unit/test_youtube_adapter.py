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


async def test_fetch_updates_excludes_livestreams_from_new_video_results() -> None:
    """A stream going live (or one that already ended) shows up in the
    uploads playlist exactly like a regular upload — must never be
    reported as a 'new video' (that's get_live_status()'s job), or it
    fires the wrong notification template. Regression test for a real
    production bug: a livestream was announced as 'New Video' instead of
    'Live Started'."""
    client = FakeYouTubeClient()
    client.uploads = [_playlist_item("live-1"), _playlist_item("vid-1")]
    live_video = {
        "id": "live-1",
        "snippet": {"title": "live-1", "liveBroadcastContent": "live"},
        "contentDetails": {},
        "liveStreamingDetails": {"actualStartTime": "2026-09-15T10:00:00Z"},
    }
    client.videos_by_id = {"live-1": live_video, "vid-1": _video("vid-1")}
    adapter = _make_adapter(client)

    result = await adapter.fetch_updates(_ACCOUNT, cursor="vid-0")

    assert {v["id"] for v in result.items} == {"vid-1"}
    assert result.next_cursor == "live-1"  # cursor still advances past the excluded item


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


def test_min_poll_interval_spreads_the_live_search_budget_across_the_day() -> None:
    """Regression test: MonitoringManager used to schedule any LIVE_STATUS
    adapter at a flat 60s cadence. For YouTube that burned the whole day's
    100-unit-per-call search budget in the first few minutes (8000/100 = 80
    calls at one every 60s is spent inside 80 minutes), then went dark for
    the rest of the day instead of spreading checks out — see
    platforms/base.py's min_poll_interval_seconds docstring. 8000 units /
    100 per call = 80 calls/day = one every 1080s."""
    client = FakeYouTubeClient()
    adapter = _make_adapter(client)

    assert adapter.min_poll_interval_seconds == 1080.0


def test_min_poll_interval_follows_a_smaller_configured_budget() -> None:
    client = FakeYouTubeClient()
    adapter = _make_adapter(client, live_search_daily_budget_units=200)

    # 200 / 100 = 2 calls/day = one every 43200s.
    assert adapter.min_poll_interval_seconds == 43200.0
