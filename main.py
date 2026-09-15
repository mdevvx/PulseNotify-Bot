"""Entry point: load config, set up logging, construct the bot, run it.

Startup order matters here — configuration must be valid and logging must
be ready before anything else runs, so problems in either surface
immediately instead of being swallowed by a half-initialized bot.
"""

from __future__ import annotations

import asyncio

from bot.client import PulseNotifyBot
from bot.lifecycle import run
from config.settings import get_settings
from utils.logger import get_logger, setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_dir)
    logger = get_logger(__name__)

    logger.info("Starting PulseNotify (environment=%s)...", settings.environment)

    bot = PulseNotifyBot(settings=settings)
    await run(bot, settings.discord_token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
