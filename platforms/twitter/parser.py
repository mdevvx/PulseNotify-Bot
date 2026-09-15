"""Pure functions converting raw X API v2 JSON into this project's
normalized shapes. No HTTP calls or mutable state here, so this is
trivially testable against fixture JSON without a client or network.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, Optional

from events.models import EventType, NormalizedEvent
from platforms.base import AccountRef

_X_URL_RE = re.compile(r"^https?://(www\.)?(x|twitter)\.com/(?P<handle>[^/?]+)", re.IGNORECASE)


def parse_identifier(identifier: str) -> str:
    """Resolves a user-supplied handle, @mention, or full profile URL to a
    bare handle — matching TwitterClient.get_user_by_username()'s
    parameter."""
    value = identifier.strip()

    url_match = _X_URL_RE.match(value)
    if url_match:
        value = url_match.group("handle")

    return value.lstrip("@")


def user_to_account_ref(user: Dict[str, Any]) -> AccountRef:
    """`user` is a Get User by Username resource. The numeric `id` (not
    `username`) is used as platform_account_id since a handle can be
    renamed but the ID can't — matches how the YouTube/Twitch/Kick
    adapters use their platforms' stable channel/user IDs over handles."""
    return AccountRef(
        platform="twitter",
        platform_account_id=user["id"],
        username=user.get("name") or user["username"],
    )


def normalize_tweet(account: AccountRef, tweet: Dict[str, Any]) -> NormalizedEvent:
    """`tweet` is a Post resource (tweet.fields=created_at). The permalink
    deliberately uses the handle-less `i/web/status/` form rather than
    `/{handle}/status/{id}` — the tweet list response doesn't include the
    author's handle (that needs a separate `expansions=author_id` fetch),
    and `i/web/status/` is a real, stable X-provided redirect that doesn't
    need it."""
    tweet_id = tweet["id"]
    return NormalizedEvent(
        platform=account.platform,
        platform_account_id=account.platform_account_id,
        account_username=account.username,
        event_type=EventType.POST_CREATED,
        platform_event_id=tweet_id,
        description=tweet.get("text"),
        url=f"https://x.com/i/web/status/{tweet_id}",
        author=account.username,
        published_at=_parse_timestamp(tweet.get("created_at")),
    )


def _parse_timestamp(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
