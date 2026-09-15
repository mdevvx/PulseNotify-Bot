"""Pure functions converting raw Kick Public API JSON into this project's
normalized shapes. No HTTP calls or mutable state here, so this is
trivially testable against fixture JSON without a client or network.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, Optional

from platforms.base import AccountRef, LiveStatus

_KICK_URL_RE = re.compile(r"^https?://(www\.)?kick\.com/(?P<slug>[^/?]+)", re.IGNORECASE)


def parse_identifier(identifier: str) -> str:
    """Resolves a user-supplied slug, @handle-style mention, or full
    channel URL to a bare Kick slug — matching KickClient.get_channel_by_slug()'s
    parameter. Kick slugs are always lowercase."""
    value = identifier.strip()

    url_match = _KICK_URL_RE.match(value)
    if url_match:
        value = url_match.group("slug")

    return value.lstrip("@").lower()


def channel_to_account_ref(channel: Dict[str, Any]) -> AccountRef:
    """`channel` is a GET /public/v1/channels resource. The numeric
    broadcaster_user_id (not `slug`) is used as platform_account_id since a
    slug can be renamed but the ID can't — matches how the YouTube/Twitch
    adapters use their platforms' stable channel/user IDs over handles."""
    return AccountRef(
        platform="kick",
        platform_account_id=str(channel["broadcaster_user_id"]),
        username=channel.get("slug") or str(channel["broadcaster_user_id"]),
    )


def channel_to_live_status(channel: Dict[str, Any]) -> LiveStatus:
    """`channel` is a GET /public/v1/channels resource — Kick nests live
    state under `stream` (absent/empty for a channel that's never gone
    live) rather than exposing a top-level boolean.

    Unlike YouTube/Twitch, Kick's API exposes no per-session stream ID —
    stream_id is deliberately left None here. monitoring.worker.py's
    fallback platform_event_id generation accounts for exactly this case
    (it varies by started_at, not just by account, so two different Kick
    live sessions never collide under the events table's dedup key)."""
    stream = channel.get("stream") or {}
    if not stream.get("is_live"):
        return LiveStatus(is_live=False)

    category = (channel.get("category") or {}).get("name")
    slug = channel.get("slug")
    return LiveStatus(
        is_live=True,
        stream_id=None,
        title=channel.get("stream_title"),
        category=category or None,
        viewer_count=_safe_int(stream.get("viewer_count")),
        started_at=_parse_timestamp(stream.get("start_time")),
        thumbnail_url=stream.get("thumbnail"),
        url=stream.get("url") or (f"https://kick.com/{slug}" if slug else None),
    )


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
