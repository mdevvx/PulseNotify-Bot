"""Notification channels and their links to monitored accounts, backed by
`notification_channels` and the `account_channels` join table.
"""

from __future__ import annotations

from typing import List, Optional

from database.client import Database, is_unique_violation
from database.models import NotificationChannelRow
from utils.logger import get_logger

logger = get_logger(__name__)

_CHANNELS_TABLE = "pulsenotify_notification_channels"
_LINKS_TABLE = "pulsenotify_account_channels"


class NotificationChannelRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def get_by_discord_channel(self, guild_id: int, discord_channel_id: int) -> Optional[NotificationChannelRow]:
        result = (
            await self._db.client.table(_CHANNELS_TABLE)
            .select("*")
            .eq("guild_id", guild_id)
            .eq("channel_id", discord_channel_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def get_or_create(
        self, guild_id: int, discord_channel_id: int, *, name: Optional[str] = None
    ) -> NotificationChannelRow:
        """Reuses an existing row for this Discord channel if one exists —
        re-validating it (is_valid=true) if it had previously been marked
        invalid, since being re-registered means it's accessible again."""
        existing = await self.get_by_discord_channel(guild_id, discord_channel_id)
        if existing is not None:
            if not existing["is_valid"] or (name and existing.get("name") != name):
                await (
                    self._db.client.table(_CHANNELS_TABLE)
                    .update({"is_valid": True, "name": name})
                    .eq("id", existing["id"])
                    .execute()
                )
                existing = await self.get_by_discord_channel(guild_id, discord_channel_id)
                assert existing is not None
            return existing

        try:
            inserted = await (
                self._db.client.table(_CHANNELS_TABLE)
                .insert({"guild_id": guild_id, "channel_id": discord_channel_id, "name": name})
                .execute()
            )
            return inserted.data[0]
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            row = await self.get_by_discord_channel(guild_id, discord_channel_id)
            assert row is not None
            return row

    async def mark_invalid(self, channel_row_id: str) -> None:
        await self._db.client.table(_CHANNELS_TABLE).update({"is_valid": False}).eq("id", channel_row_id).execute()

    async def link_account(self, guild_id: int, account_id: str, channel_row_id: str) -> None:
        try:
            await (
                self._db.client.table(_LINKS_TABLE)
                .insert({"guild_id": guild_id, "account_id": account_id, "channel_id": channel_row_id})
                .execute()
            )
        except Exception as exc:
            if not is_unique_violation(exc):
                raise  # already linked — nothing to do

    async def list_valid_for_account(self, account_id: str) -> List[NotificationChannelRow]:
        links = await self._db.client.table(_LINKS_TABLE).select("channel_id").eq("account_id", account_id).execute()
        channel_row_ids = [row["channel_id"] for row in links.data]
        if not channel_row_ids:
            return []

        result = (
            await self._db.client.table(_CHANNELS_TABLE)
            .select("*")
            .in_("id", channel_row_ids)
            .eq("is_valid", True)
            .execute()
        )
        return result.data
