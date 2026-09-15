"""The single top-level `/pulsenotify` command group every slash command
attaches to (e.g. `/pulsenotify toggle`, `/pulsenotify status`).

One shared module-level Group instance — commands/admin/status.py,
commands/admin/toggle.py, and commands/accounts/cog.py each decorate their
command against THIS object rather than defining their own top-level
`@app_commands.command()`. bot/client.py registers it to the tree exactly
once (`tree.add_command(pulsenotify_group)`), after every extension that
contributes a subcommand has been loaded.

Account management (`account-add`/`account-remove`/`account-list`) is
flattened into direct subcommands here rather than nested under an
"account" subcommand group: Discord does not allow mixing plain
subcommands and subcommand groups as siblings under the same parent, and
`/pulsenotify toggle` (a plain subcommand) is the pattern this project
was explicitly asked to match — so every subcommand here is a plain
subcommand, none are groups.
"""

from __future__ import annotations

from discord import app_commands

pulsenotify_group = app_commands.Group(
    name="pulsenotify",
    description="PulseNotify — monitor social/streaming accounts and post alerts to this server.",
    guild_only=True,
)
