"""Process entry point for the Telegram forwarding bot."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from pyrogram import Client, idle

try:
    import uvloop
except ImportError:  # Optional on platforms without uvloop wheels.
    uvloop = None

from config import Config
from database import db
from plugins.forwarding import restart_forwards

LOGGER = logging.getLogger("forword_bot")


def configure_logging() -> None:
    """Use consistent structured-enough logs on stdout for container hosts."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def create_bot() -> Client:
    """Build the Telegram client after validating deployment configuration."""
    Config.validate()
    return Client(
        Config.BOT_SESSION,
        bot_token=Config.BOT_TOKEN,
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        sleep_threshold=120,
        plugins={"root": "plugins"},
    )


async def run() -> None:
    client = create_bot()
    started = False
    try:
        await db.connect()
        await client.start()
        started = True
        bot_info = await client.get_me()
        LOGGER.info("Bot started as @%s (id=%s)", bot_info.username, bot_info.id)

        await restart_forwards(client)
        LOGGER.info("Resumed pending forwarding jobs")
        await idle()
    finally:
        if started:
            await client.stop()
        await db.close()
        LOGGER.info("Bot shutdown complete")


def main() -> None:
    configure_logging()
    try:
        if uvloop is not None:
            LOGGER.info("Using uvloop event loop")
            uvloop.run(run())
        else:
            LOGGER.info("uvloop is unavailable; using the standard asyncio loop")
            asyncio.run(run())
    except KeyboardInterrupt:
        LOGGER.info("Shutdown requested")
    except Exception:
        LOGGER.exception("Bot stopped because of an unrecoverable error")
        raise


if __name__ == "__main__":
    main()
