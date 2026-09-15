"""Process-wide configuration, loaded once from the environment (and .env locally).

Only Discord and Supabase credentials are required to boot the bot. Every
platform API key is optional here — each platform adapter validates what it
specifically needs when that adapter is added, so a missing key disables
just that platform instead of blocking startup (see the startup flow in the
project spec: a non-critical platform being unavailable must not stop the
bot from starting).
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings tries to JSON-decode env values for any "complex" field
# type (list/dict/set) before pydantic's own validators ever run, so a
# comma-separated string like "111,222" fails as invalid JSON. Owner IDs are
# therefore stored as a raw string field and exposed as a list via a plain
# property below, which sidesteps that JSON-decoding step entirely.

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_dir: str = Field(default="logs", alias="LOG_DIR")

    discord_token: str = Field(..., min_length=1, alias="DISCORD_TOKEN")
    discord_command_prefix: str = Field(default="pn!", alias="DISCORD_COMMAND_PREFIX")
    discord_owner_ids_raw: str = Field(default="", alias="DISCORD_OWNER_IDS")
    discord_dev_guild_id: Optional[int] = Field(default=None, alias="DEV_GUILD_ID")

    supabase_url: str = Field(..., min_length=1, alias="SUPABASE_URL")
    supabase_key: str = Field(..., min_length=1, alias="SUPABASE_KEY")

    # Platform credentials are intentionally optional in the foundation phase.
    twitter_api_key: Optional[str] = Field(default=None, alias="TWITTER_API_KEY")
    twitter_api_secret: Optional[str] = Field(default=None, alias="TWITTER_API_SECRET")
    youtube_api_key: Optional[str] = Field(default=None, alias="YOUTUBE_API_KEY")
    twitch_client_id: Optional[str] = Field(default=None, alias="TWITCH_CLIENT_ID")
    twitch_client_secret: Optional[str] = Field(default=None, alias="TWITCH_CLIENT_SECRET")
    kick_api_key: Optional[str] = Field(default=None, alias="KICK_API_KEY")
    instagram_api_key: Optional[str] = Field(default=None, alias="INSTAGRAM_API_KEY")
    facebook_api_key: Optional[str] = Field(default=None, alias="FACEBOOK_API_KEY")

    # Monitoring framework configuration (section 28: one place for these,
    # not scattered through the code). Content polling is far less
    # time-sensitive than live status, hence the separate interval.
    monitoring_content_poll_interval_seconds: float = Field(default=300.0, alias="MONITORING_CONTENT_POLL_INTERVAL_SECONDS")
    monitoring_live_poll_interval_seconds: float = Field(default=60.0, alias="MONITORING_LIVE_POLL_INTERVAL_SECONDS")
    monitoring_max_retry_attempts: int = Field(default=5, alias="MONITORING_MAX_RETRY_ATTEMPTS")
    monitoring_retry_base_delay_seconds: float = Field(default=2.0, alias="MONITORING_RETRY_BASE_DELAY_SECONDS")
    monitoring_retry_max_delay_seconds: float = Field(default=300.0, alias="MONITORING_RETRY_MAX_DELAY_SECONDS")
    monitoring_rate_limit_requests: int = Field(default=30, alias="MONITORING_RATE_LIMIT_REQUESTS")
    monitoring_rate_limit_period_seconds: float = Field(default=60.0, alias="MONITORING_RATE_LIMIT_PERIOD_SECONDS")
    monitoring_event_queue_size: int = Field(default=1000, alias="MONITORING_EVENT_QUEUE_SIZE")
    # Consecutive platform-level failures before platform_health flips to
    # 'degraded', then 'error'. Per-account failure thresholds live on the
    # account itself (platform_accounts.consecutive_failures / .status) and
    # aren't configured here — they're about one broken account, not the
    # platform's API as a whole.
    monitoring_health_degraded_after: int = Field(default=3, alias="MONITORING_HEALTH_DEGRADED_AFTER")
    monitoring_health_error_after: int = Field(default=8, alias="MONITORING_HEALTH_ERROR_AFTER")
    monitoring_http_timeout_seconds: float = Field(default=15.0, alias="MONITORING_HTTP_TIMEOUT_SECONDS")

    # YouTube Data API v3 quota (see platforms/youtube/adapter.py for the
    # full breakdown): free-tier default is 10,000 units/day, shared across
    # every YouTube account this bot monitors, in every guild — it's one
    # budget per API key, not per account. search.list (used for live
    # detection) costs 100 units/call; the adapter reserves a portion of
    # the daily budget for it specifically so it can't starve the cheap
    # calls (playlistItems.list / videos.list, 1 unit each) that new-video
    # detection depends on.
    youtube_daily_quota_units: int = Field(default=10_000, alias="YOUTUBE_DAILY_QUOTA_UNITS")
    youtube_live_search_daily_budget_units: int = Field(default=8_000, alias="YOUTUBE_LIVE_SEARCH_DAILY_BUDGET_UNITS")

    @property
    def discord_owner_ids(self) -> List[int]:
        return [int(part) for part in self.discord_owner_ids_raw.split(",") if part.strip()]

    @field_validator("discord_dev_guild_id", mode="before")
    @classmethod
    def _blank_dev_guild_id_means_unset(cls, value: object) -> object:
        # .env.example documents leaving this blank to mean "no dev guild" —
        # pydantic won't coerce "" to None for an Optional[int] on its own,
        # so a real .env with DEV_GUILD_ID= (unset) would otherwise fail
        # Settings validation and stop the bot from starting at all.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got {value!r}")
        return upper


@lru_cache
def get_settings() -> Settings:
    """Returns the process-wide Settings singleton, loading it on first use."""
    return Settings()  # type: ignore[call-arg]  # populated from the environment, not kwargs
