"""Pure functions converting raw Twitch Helix API JSON into this project's
normalized shapes. No HTTP calls or mutable state here, so this is
trivially testable against fixture JSON without a client or network.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, Optional

from platforms.base import AccountRef, LiveStatus

_TWITCH_URL_RE = re.compile(r"^https?://(www\.)?twitch\.tv/(?P<login>[^/?]+)", re.IGNORECASE)


def parse_identifier(identifier: str) -> str:
    """Resolves a user-supplied login, @handle-style mention, or full
    channel URL to a bare Twitch login — matching TwitchClient.get_user()'s
    `login` parameter. Twitch logins are always lowercase."""
    value = identifier.strip()

    url_match = _TWITCH_URL_RE.match(value)
    if url_match:
        value = url_match.group("login")

    return value.lstrip("@").lower()


def user_to_account_ref(user: Dict[str, Any]) -> AccountRef:
    """`user` is a Get Users resource. The numeric `id` (not `login`) is
    used as platform_account_id since a login can be renamed but the ID
    can't — matches how YouTube uses the channel ID over its handle."""
    return AccountRef(
        platform="twitch",
        platform_account_id=user["id"],
        username=user.get("display_name") or user["login"],
    )


def stream_to_live_status(stream: Dict[str, Any]) -> LiveStatus:
    """`stream` is a Get Streams resource — only ever called for a channel
    Twitch already reported as live (an offline channel is simply absent
    from that endpoint's response), so is_live is always True here."""
    user_login = stream.get("user_login")
    return LiveStatus(
        is_live=True,
        stream_id=stream.get("id"),
        title=stream.get("title"),
        category=stream.get("game_name") or None,
        viewer_count=_safe_int(stream.get("viewer_count")),
        started_at=_parse_timestamp(stream.get("started_at")),
        thumbnail_url=_format_thumbnail(stream.get("thumbnail_url")),
        url=f"https://twitch.tv/{user_login}" if user_login else None,
    )


def _format_thumbnail(template: Optional[str]) -> Optional[str]:
    """Twitch's thumbnail_url is a template containing literal
    '{width}'/'{height}' placeholders the caller must substitute — it
    isn't a usable URL as-is."""
    if not template:
        return None
    return template.replace("{width}", "1280").replace("{height}", "720")


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
