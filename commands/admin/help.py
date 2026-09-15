"""`/pulsenotify help` — lists every command and what it does.

Built by introspecting `pulsenotify_group.commands` rather than a
hand-maintained list, so it can never drift out of sync with what's
actually registered — add a subcommand anywhere in the group and it shows
up here automatically, with no second place to remember to update.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from commands.pulsenotify_group import pulsenotify_group
from config import constants


@pulsenotify_group.command(name="help", description="Show all PulseNotify commands and what they do.")
async def help_command(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title=f"{constants.BOT_NAME} Commands",
        description="Every command below is a subcommand of `/pulsenotify`.",
        color=discord.Color(constants.COLOR_INFO),
    )

    for command in sorted(pulsenotify_group.commands, key=lambda c: c.name):
        if command.name == "help":
            continue
        usage = _format_usage(command)
        value = command.description or "No description."
        if usage:
            value += f"\n`{usage}`"
        embed.add_field(name=f"/pulsenotify {command.name}", value=value, inline=False)

    embed.set_footer(text=f"{constants.BOT_NAME} v{constants.BOT_VERSION} · pn!sync is a text command, not shown above")
    await interaction.response.send_message(embed=embed, ephemeral=True)


def _format_usage(command: app_commands.Command) -> str:
    tokens = [param.name if param.required else f"[{param.name}]" for param in command.parameters]
    if not tokens:
        return ""
    return f"/pulsenotify {command.name} " + " ".join(tokens)


async def setup(bot: commands.Bot) -> None:
    """No Cog needed — `help` attaches to the shared pulsenotify_group at
    import time (the decorator above)."""
