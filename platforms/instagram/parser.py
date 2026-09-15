"""Pure functions converting raw Instagram Graph API (Business Discovery)
JSON into this project's normalized shapes. No HTTP calls or mutable
state here, so this is trivially testable against fixture JSON without a
client or network.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, Optional

from events.models import EventType, NormalizedEvent
from platforms.base import AccountRef

_INSTAGRAM_URL_RE = re.compile(r"^https?://(www\.)?instagram\.com/(?P<username>[^/?]+)", re.IGNORECASE)


def parse_identifier(identifier: str) -> str:
    """Resolves a user-supplied username, @mention, or full profile URL to
    a bare username — matching InstagramClient.get_business_discovery()'s
    parameter. Instagram usernames are always lowercase."""
    value = identifier.strip()

    url_match = _INSTAGRAM_URL_RE.match(value)
    if url_match:
        value = url_match.group("username")

    return value.lstrip("@").lower()


def discovery_to_account_ref(discovery: Dict[str, Any]) -> AccountRef:
    """`discovery` is a business_discovery resource. Unlike the other
    adapters, `username` here isn't just for display — Business Discovery
    can only be queried by username (there's no by-ID lookup), so every
    subsequent fetch_updates() call re-supplies account.username as the
    live query key. If the target ever renames their handle, polling
    breaks until the account is removed and re-added — a real, documented
    limitation of this endpoint, not something this adapter can work
    around."""
    return AccountRef(
        platform="instagram",
        platform_account_id=discovery["id"],
        username=discovery.get("username") or discovery["id"],
    )


def normalize_media(account: AccountRef, media: Dict[str, Any]) -> NormalizedEvent:
    """`media` is one item from business_discovery's `media` edge. Reels
    are not distinguishable from a plain video post through this endpoint
    (media_type is only IMAGE/VIDEO/CAROUSEL_ALBUM) — recorded as-is in
    metadata rather than guessed at, matching the honesty bar set by
    YouTube's documented Shorts heuristic rather than inventing a
    reels-detection heuristic with no real signal behind it."""
    media_id = media["id"]
    return NormalizedEvent(
        platform=account.platform,
        platform_account_id=account.platform_account_id,
        account_username=account.username,
        event_type=EventType.POST_CREATED,
        platform_event_id=media_id,
        description=media.get("caption"),
        url=media.get("permalink"),
        thumbnail_url=media.get("media_url"),
        author=account.username,
        published_at=_parse_timestamp(media.get("timestamp")),
        metadata={"media_type": media.get("media_type")},
    )


def _parse_timestamp(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
