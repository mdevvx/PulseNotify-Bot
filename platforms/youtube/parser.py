"""Pure functions converting raw YouTube Data API v3 JSON into this
project's normalized shapes. No HTTP calls or mutable state here, so this
is trivially testable against fixture JSON without a client or network.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, Optional, Tuple

from events.models import EventType, NormalizedEvent
from platforms.base import AccountRef, LiveStatus

# No official "is this a Short" field exists on the Data API (verified
# 2026-09-15 against current Google documentation and community reports —
# there is no isShort/shortsEligible field on the Video resource). This is
# a best-effort heuristic using the official contentDetails.duration field:
# it will misclassify a short *regular* video (<=60s) as a Short. Treat
# EventType.SHORT_PUBLISHED as "probably a Short," not a guarantee.
_SHORT_MAX_SECONDS = 60

_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_YOUTUBE_URL_RE = re.compile(r"^https?://(www\.)?youtube\.com/(?P<path>.+)$", re.IGNORECASE)
_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def parse_identifier(identifier: str) -> Tuple[str, str]:
    """Resolves a user-supplied channel ID, @handle, legacy username, or
    full URL to (lookup_kind, value) — lookup_kind is 'id', 'handle', or
    'username', matching YouTubeClient.get_channel()'s parameters."""
    value = identifier.strip()

    url_match = _YOUTUBE_URL_RE.match(value)
    if url_match:
        path = url_match.group("path").split("?")[0].strip("/")
        if path.startswith("channel/"):
            return "id", path[len("channel/") :]
        if path.startswith("user/"):
            return "username", path[len("user/") :]
        if path.startswith("c/"):
            path = path[len("c/") :]
        return "handle", path if path.startswith("@") else f"@{path}"

    if _CHANNEL_ID_RE.match(value):
        return "id", value

    return "handle", value if value.startswith("@") else f"@{value}"


def channel_to_account_ref(channel: Dict[str, Any]) -> AccountRef:
    snippet = channel.get("snippet", {})
    return AccountRef(
        platform="youtube",
        platform_account_id=channel["id"],
        username=snippet.get("customUrl") or snippet.get("title") or channel["id"],
    )


def uploads_playlist_id(channel: Dict[str, Any]) -> Optional[str]:
    return channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")


def playlist_item_video_id(item: Dict[str, Any]) -> str:
    return item["snippet"]["resourceId"]["videoId"]


def normalize_video(account: AccountRef, video: Dict[str, Any]) -> NormalizedEvent:
    """`video` is a videos.list resource (part=snippet,contentDetails)."""
    snippet = video.get("snippet", {})
    content_details = video.get("contentDetails", {})
    video_id = video["id"]

    duration_seconds = _parse_iso8601_duration(content_details.get("duration"))
    is_probably_short = duration_seconds is not None and duration_seconds <= _SHORT_MAX_SECONDS

    return NormalizedEvent(
        platform=account.platform,
        platform_account_id=account.platform_account_id,
        account_username=account.username,
        event_type=EventType.SHORT_PUBLISHED if is_probably_short else EventType.VIDEO_PUBLISHED,
        platform_event_id=video_id,
        title=snippet.get("title"),
        description=snippet.get("description"),
        url=f"https://www.youtube.com/watch?v={video_id}",
        thumbnail_url=_best_thumbnail(snippet.get("thumbnails")),
        author=snippet.get("channelTitle"),
        published_at=_parse_timestamp(snippet.get("publishedAt")),
        metadata={"duration_seconds": duration_seconds, "is_short_heuristic": is_probably_short},
    )


def video_to_live_status(video: Dict[str, Any]) -> LiveStatus:
    """`video` is a videos.list resource (part=snippet,liveStreamingDetails)."""
    snippet = video.get("snippet", {})
    live_details = video.get("liveStreamingDetails", {})

    return LiveStatus(
        is_live=snippet.get("liveBroadcastContent") == "live",
        stream_id=video.get("id"),
        title=snippet.get("title"),
        category=None,  # not exposed for a channel this bot doesn't own, without extra API calls
        viewer_count=_safe_int(live_details.get("concurrentViewers")),
        started_at=_parse_timestamp(live_details.get("actualStartTime")),
        thumbnail_url=_best_thumbnail(snippet.get("thumbnails")),
    )


def _best_thumbnail(thumbnails: Optional[Dict[str, Any]]) -> Optional[str]:
    if not thumbnails:
        return None
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbnails:
            return thumbnails[key].get("url")
    return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_timestamp(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_iso8601_duration(value: Optional[str]) -> Optional[int]:
    """Parses 'PT1M30S'-style durations into total seconds. Only covers the
    hour/minute/second components YouTube actually emits for videos (not
    days/weeks/months/years, which ISO 8601 allows but video durations
    never use)."""
    if not value:
        return None
    match = _DURATION_RE.match(value)
    if not match:
        return None
    hours, minutes, seconds = (int(group) if group else 0 for group in match.groups())
    return hours * 3600 + minutes * 60 + seconds
