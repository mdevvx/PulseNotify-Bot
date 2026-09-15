"""The real EventProcessor notification sink: looks up who wants to know
about an event and how, then sends it — respecting AllowedMentions
(section 36) and marking a channel invalid rather than retrying forever if
Discord says it's gone (section 23).

Discord-side rate limiting is handled by discord.py's own HTTP layer;
EventProcessor's single-consumer queue already serializes delivery (one
event handled at a time), which is what keeps this from ever firing a
burst of simultaneous sends — see events/processor.py's docstring for why
no separate notification queue was built on top of that.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import discord

from database.repositories.alert_configs import AlertConfigurationRepository
from database.repositories.channels import NotificationChannelRepository
from events.models import NormalizedEvent
from notifications.embeds import build_embed, build_plain_text
from notifications.templates import render_custom_message
from utils.logger import get_logger

logger = get_logger(__name__)


class NotificationSender:
    def __init__(
        self,
        bot: discord.Client,
        alert_config_repo: AlertConfigurationRepository,
        channel_repo: NotificationChannelRepository,
    ) -> None:
        self._bot = bot
        self._alert_config_repo = alert_config_repo
        self._channel_repo = channel_repo

    async def handle(self, event: NormalizedEvent) -> None:
        assert event.guild_id is not None and event.account_id is not None

        config = await self._alert_config_repo.get(event.account_id, event.event_type.value)
        if config is not None and not config["enabled"]:
            return

        channels = await self._channel_repo.list_valid_for_account(event.account_id)
        if not channels:
            logger.debug(
                "No notification channels configured for account %s (guild %s); dropping %s event.",
                event.account_id,
                event.guild_id,
                event.event_type.value,
            )
            return

        embed_enabled = config["embed_enabled"] if config else True
        mention_role_id = config["mention_role_id"] if config else None
        custom_message = config["custom_message"] if config else None
        content, embed, suppress_embeds = self._build_message(
            event, embed_enabled=embed_enabled, mention_role_id=mention_role_id, custom_message=custom_message
        )
        allowed_mentions = self._allowed_mentions_for(content, mention_role_id)

        for channel_row in channels:
            await self._send_to_channel(
                channel_row,
                content=content,
                embed=embed,
                allowed_mentions=allowed_mentions,
                suppress_embeds=suppress_embeds,
            )

    def _build_message(
        self,
        event: NormalizedEvent,
        *,
        embed_enabled: bool,
        mention_role_id: Optional[int],
        custom_message: Optional[str],
    ) -> tuple:
        if custom_message:
            # Never attach a manually-built embed alongside a custom
            # message — the admin's template typically already includes
            # {url} as plain text, and Discord auto-generates its own
            # preview from that raw link, so a hand-built embed on top
            # just duplicates it. embed_enabled instead controls whether
            # that native preview is allowed to show at all.
            content = render_custom_message(custom_message, event, mention_role_id=mention_role_id)
            return content, None, not embed_enabled

        mention_text = f"<@&{mention_role_id}>" if mention_role_id else None

        if embed_enabled:
            return mention_text, build_embed(event), False

        fallback = build_plain_text(event)
        content = f"{mention_text}\n{fallback}" if mention_text else fallback
        return content, None, False

    def _allowed_mentions_for(self, content: Optional[str], mention_role_id: Optional[int]) -> discord.AllowedMentions:
        text = content or ""
        return discord.AllowedMentions(
            # @everyone/@here can only appear here if the admin typed it
            # literally into their own custom_message template — platform
            # content substituted into placeholders is always
            # mention-escaped first (see notifications/templates.py).
            everyone="@everyone" in text or "@here" in text,
            users=False,
            roles=[discord.Object(id=mention_role_id)] if mention_role_id else False,
        )

    async def _send_to_channel(
        self,
        channel_row: Dict[str, Any],
        *,
        content: Optional[str],
        embed: Optional[discord.Embed],
        allowed_mentions: discord.AllowedMentions,
        suppress_embeds: bool = False,
    ) -> None:
        discord_channel_id = channel_row["channel_id"]
        discord_channel = self._bot.get_channel(discord_channel_id)

        if discord_channel is None:
            try:
                discord_channel = await self._bot.fetch_channel(discord_channel_id)
            except (discord.NotFound, discord.Forbidden):
                await self._mark_invalid(channel_row, "channel is no longer accessible")
                return
            except discord.HTTPException:
                logger.exception("Failed to look up notification channel %s.", discord_channel_id)
                return

        try:
            await discord_channel.send(
                content=content, embed=embed, allowed_mentions=allowed_mentions, suppress_embeds=suppress_embeds
            )
        except discord.Forbidden:
            await self._mark_invalid(channel_row, "missing permission to send messages")
        except discord.NotFound:
            await self._mark_invalid(channel_row, "channel was deleted")
        except discord.HTTPException:
            logger.exception("Failed to send notification to channel %s.", discord_channel_id)

    async def _mark_invalid(self, channel_row: Dict[str, Any], reason: str) -> None:
        await self._channel_repo.mark_invalid(channel_row["id"])
        logger.warning("Marking notification channel %s invalid: %s", channel_row["channel_id"], reason)
