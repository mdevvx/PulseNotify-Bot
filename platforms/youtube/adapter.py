"""YouTube Data API v3 adapter.

API availability summary (section 46), verified 2026-09-15 against current
Google developer documentation and community reporting — see
[[project-platform-api-policy]] / README.md for the standing policy this
follows:

| Feature                | Supported | Method                                    | Cost/call | Notes |
|-------------------------|-----------|---------------------------------------------|-----------|-------|
| New videos              | Yes       | playlistItems.list on the uploads playlist  | 1 unit    | Reliable, cheap. |
| Shorts                  | Heuristic | contentDetails.duration <= 60s              | (included)| No official "is Short" field exists on the API. False positives possible for short *regular* videos. Documented as a heuristic, not fact. |
| Community posts         | No        | —                                             | —         | No public Data API v3 endpoint exists for the Community tab. Not implemented — there is no honest way to build this right now. |
| Live stream start/end   | Yes       | search.list(eventType=live) + videos.list   | 100 + 1   | search.list is the only documented way to find a live broadcast on a channel this bot doesn't own. There is no cheap alternative without YouTube's PubSubHubbub/WebSub push feed, which needs a public HTTPS callback URL this project doesn't have yet (see README's Monitoring framework section). |
| Upcoming/scheduled streams | No     | —                                             | —         | Not implemented this phase; would double the live-search quota cost for a lower-priority signal. |

Credentials: a plain API key (YOUTUBE_API_KEY) — none of the above needs
OAuth, since it's all public channel/video data.

Quota: 10,000 units/day by default (Settings.youtube_daily_quota_units),
shared across every YouTube account this bot monitors — it's one budget
per Google Cloud project, not per-account or per-guild. The 100-unit live
search dominates that budget, so it's tracked against its own reserved
share (Settings.youtube_live_search_daily_budget_units) rather than the
same pool as the 1-unit calls — see the two RateLimiter instances below.
"""

from __future__ import annotations

import time
from typing import Any, Callable, ClassVar, Dict, FrozenSet, Optional, Set, Tuple

from events.models import NormalizedEvent
from monitoring.rate_limiter import RateLimiter
from platforms.base import AccountRef, Capability, FetchResult, LiveStatus, PlatformAdapter
from platforms.youtube import parser
from platforms.youtube.client import YouTubeClient
from utils.errors import PermanentPlatformError
from utils.logger import get_logger

logger = get_logger(__name__)

_SEARCH_COST = 100
_LIST_COST = 1
_UPLOADS_PAGE_SIZE = 10


class YouTubeAdapter(PlatformAdapter):
    platform: ClassVar[str] = "youtube"
    capabilities: ClassVar[FrozenSet[Capability]] = frozenset(
        {Capability.VIDEOS, Capability.SHORTS, Capability.LIVE_STATUS}
    )

    def __init__(
        self,
        client: YouTubeClient,
        *,
        daily_quota_units: int,
        live_search_daily_budget_units: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._clock = clock
        list_budget = max(daily_quota_units - live_search_daily_budget_units, _LIST_COST)
        self._list_budget = RateLimiter(max_requests=list_budget, period_seconds=86400)
        # Budgeted in quota units (not call count) to match how it's
        # acquired below (try_acquire(cost=_SEARCH_COST)) and how
        # _list_budget already works — mixing the two would silently
        # under- or over-count.
        self._search_budget = RateLimiter(
            max_requests=max(live_search_daily_budget_units, _SEARCH_COST), period_seconds=86400
        )
        # Without this, MonitoringManager would schedule this adapter at
        # its generic 60s LIVE_STATUS interval, which would burn the whole
        # day's search budget in the first few minutes (e.g. 8000/100 = 80
        # calls at one every 60s is spent inside 80 minutes) and then go
        # dark for the rest of the day instead of spreading checks evenly —
        # see platforms/base.py's docstring. Spacing polls one call apart
        # keeps the sliding-window budget spent at a sustainable rate.
        self._search_calls_per_day = max(live_search_daily_budget_units // _SEARCH_COST, 1)
        self.min_poll_interval_seconds = 86400 / self._search_calls_per_day
        # Live-status results are cached per *physical* channel
        # (platform_account_id), not per guild-scoped account row, and the
        # cache window grows with the number of distinct channels seen so
        # far. Two reasons this matters, both found in production: (1) two
        # guilds monitoring the same creator would otherwise each pay the
        # full 100-unit search cost for that one channel on every scheduler
        # tick, silently doubling the real cost min_poll_interval_seconds
        # above was sized for; (2) more generally, N distinct channels
        # sharing this one adapter's search budget need N times as long
        # between checks on any one of them to stay within the same daily
        # budget — otherwise the budget exhausts partway through the day
        # and every channel goes dark until the sliding window frees up.
        # Growing (never shrinking) the known-channel count is a
        # deliberately conservative approximation: an account removed
        # later still counts until restart, which only makes checks
        # somewhat slower than the theoretical minimum, never over budget.
        self._live_status_cache: Dict[str, Tuple[float, Optional[LiveStatus]]] = {}
        self._known_channel_ids: Set[str] = set()
        # A channel's uploads-playlist ID never changes once known, so
        # caching it avoids spending a channels.list call re-fetching it
        # on every single content poll.
        self._uploads_playlist_cache: Dict[str, str] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def validate_account(self, identifier: str) -> AccountRef:
        kind, value = parser.parse_identifier(identifier)
        channel = await self._client.get_channel(
            channel_id=value if kind == "id" else None,
            handle=value if kind == "handle" else None,
            username=value if kind == "username" else None,
        )
        if channel is None:
            raise PermanentPlatformError(f"No YouTube channel found for {identifier!r}")
        return parser.channel_to_account_ref(channel)

    async def fetch_updates(self, account: AccountRef, cursor: Optional[str]) -> FetchResult:
        playlist_id = await self._get_uploads_playlist_id(account)
        if playlist_id is None:
            return FetchResult(items=[], next_cursor=cursor)

        await self._list_budget.acquire(cost=_LIST_COST)
        raw_items = await self._client.list_uploads(playlist_id, max_results=_UPLOADS_PAGE_SIZE)
        if not raw_items:
            return FetchResult(items=[], next_cursor=cursor)

        newest_video_id = parser.playlist_item_video_id(raw_items[0])

        if cursor is None:
            # First-ever poll for this account: establish a baseline
            # without notifying about the channel's entire back-catalog.
            return FetchResult(items=[], next_cursor=newest_video_id)

        new_items = []
        for item in raw_items:  # uploads playlist is newest-first
            if parser.playlist_item_video_id(item) == cursor:
                break
            new_items.append(item)

        if not new_items:
            return FetchResult(items=[], next_cursor=newest_video_id)

        video_ids = [parser.playlist_item_video_id(item) for item in reversed(new_items)]
        await self._list_budget.acquire(cost=_LIST_COST)
        videos = await self._client.get_videos(video_ids)
        # Livestreams (upcoming, live, or already ended) appear in the
        # uploads playlist too — excluded here so they're never reported
        # as a "new video"; get_live_status() is the only path that
        # should ever fire a live-related notification for them.
        videos = [video for video in videos if not parser.is_live_broadcast(video)]
        return FetchResult(items=videos, next_cursor=newest_video_id)

    async def get_live_status(self, account: AccountRef) -> Optional[LiveStatus]:
        channel_id = account.platform_account_id
        self._known_channel_ids.add(channel_id)
        cache_ttl = self.min_poll_interval_seconds * len(self._known_channel_ids)

        cached = self._live_status_cache.get(channel_id)
        if cached is not None:
            cached_at, cached_status = cached
            if self._clock() - cached_at < cache_ttl:
                return cached_status

        if not await self._search_budget.try_acquire(cost=_SEARCH_COST):
            logger.debug(
                "Skipping YouTube live check for %s — daily live-search budget exhausted.", account.username
            )
            return None

        live_results = await self._client.search_live(channel_id)
        if not live_results:
            return self._cache_live_status(channel_id, LiveStatus(is_live=False))

        video_id = live_results[0]["id"]["videoId"]
        await self._list_budget.acquire(cost=_LIST_COST)
        videos = await self._client.get_videos([video_id])
        if not videos:
            return self._cache_live_status(channel_id, LiveStatus(is_live=False))

        return self._cache_live_status(channel_id, parser.video_to_live_status(videos[0]))

    def _cache_live_status(self, channel_id: str, status: LiveStatus) -> LiveStatus:
        self._live_status_cache[channel_id] = (self._clock(), status)
        return status

    def normalize_event(self, account: AccountRef, raw_item: Any) -> NormalizedEvent:
        return parser.normalize_video(account, raw_item)

    async def _get_uploads_playlist_id(self, account: AccountRef) -> Optional[str]:
        cached = self._uploads_playlist_cache.get(account.platform_account_id)
        if cached is not None:
            return cached

        await self._list_budget.acquire(cost=_LIST_COST)
        channel = await self._client.get_channel(channel_id=account.platform_account_id)
        if channel is None:
            raise PermanentPlatformError(f"YouTube channel {account.platform_account_id} no longer exists")

        playlist_id = parser.uploads_playlist_id(channel)
        if playlist_id:
            self._uploads_playlist_cache[account.platform_account_id] = playlist_id
        return playlist_id
