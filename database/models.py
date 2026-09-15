"""Typed shapes for rows returned by the Supabase repositories.

Pure documentation of the schema in database/migrations/ — no behavior.
Supabase's client returns plain dicts; these TypedDicts just give callers
(repositories now, the monitoring/event pipeline in later phases) a
checkable shape to code against instead of stringly-typed dict access.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TypedDict

Platform = str  # one of: youtube, twitch, kick, twitter, instagram, facebook, tiktok
EventType = str  # one of: post_created, video_published, short_published,
# stream_started, stream_ended, stream_updated, account_updated
AccountStatus = str  # one of: active, invalid, error
PlatformHealthStatus = str  # one of: healthy, degraded, error, disabled


class GuildRow(TypedDict):
    guild_id: int
    enabled: bool
    created_at: str
    updated_at: str


class BotSettingsRow(TypedDict):
    guild_id: int
    default_mention_role_id: Optional[int]
    embed_color: Optional[int]
    timezone: str
    created_at: str
    updated_at: str


class PlatformAccountRow(TypedDict):
    id: str
    guild_id: int
    platform: Platform
    platform_account_id: str
    username: str
    display_name: Optional[str]
    enabled: bool
    status: AccountStatus
    last_checked_at: Optional[str]
    last_error: Optional[str]
    consecutive_failures: int
    content_cursor: Optional[str]
    created_at: str
    updated_at: str


class NotificationChannelRow(TypedDict):
    id: str
    guild_id: int
    channel_id: int
    name: Optional[str]
    is_valid: bool
    webhook_url: Optional[str]
    created_at: str
    updated_at: str


class AccountChannelRow(TypedDict):
    guild_id: int
    account_id: str
    channel_id: str
    created_at: str


class AlertConfigurationRow(TypedDict):
    id: str
    guild_id: int
    account_id: str
    event_type: EventType
    enabled: bool
    mention_role_id: Optional[int]
    embed_enabled: bool
    custom_message: Optional[str]
    created_at: str
    updated_at: str


class EventRow(TypedDict):
    id: str
    guild_id: int
    account_id: str
    platform: Platform
    event_type: EventType
    platform_event_id: str
    notified: bool
    detected_at: str
    notified_at: Optional[str]
    metadata: Dict[str, Any]


class LiveStateRow(TypedDict):
    account_id: str
    guild_id: int
    is_live: bool
    current_stream_id: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    last_checked_at: Optional[str]
    updated_at: str


class AuditLogRow(TypedDict):
    id: str
    guild_id: int
    actor_id: int
    action: str
    target: Optional[str]
    metadata: Dict[str, Any]
    created_at: str


class PlatformHealthRow(TypedDict):
    platform: Platform
    status: PlatformHealthStatus
    last_success_at: Optional[str]
    last_error_at: Optional[str]
    last_error: Optional[str]
    consecutive_failures: int
    requests_today: int
    requests_today_reset_at: str
    rate_limited_until: Optional[str]
    quota_limit: Optional[int]
    quota_remaining: Optional[int]
    updated_at: str
