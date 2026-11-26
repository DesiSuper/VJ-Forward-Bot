"""Process entry point for the Telegram forwarding bot."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime
from html import escape

from pyrogram import Client, idle

try:
    import uvloop
except ImportError:  # Optional on platforms without uvloop wheels.
    uvloop = None

from config import Config
from database import db
from plugins.forwarding import cancel_pending_forwards, restart_forwards

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


def startup_notification_text(bot_info, started_at: datetime | None = None) -> str:
    """Format a compact, timezone-aware startup card for the bot owner."""
    started_at = started_at or datetime.now().astimezone()
    started_text = started_at.astimezone().strftime("%d %b %Y · %I:%M:%S %p %Z")
    bot_name = escape(str(getattr(bot_info, "first_name", None) or "Forward Bot"))
    username = getattr(bot_info, "username", None)
    bot_identity = f"@{escape(str(username))}" if username else bot_name
    return (
        "🚀 <b>Forward Bot Started</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🟢 <b>Status:</b> <code>Online</code>\n"
        f"🤖 <b>Bot:</b> {bot_identity}\n"
        f"🕒 <b>Started:</b> <code>{started_text}</code>\n"
        "✅ <b>Forwarding:</b> Ready"
    )


async def notify_bot_owner_started(client, bot_info) -> None:
    """Send the owner a startup card; notification failures must not stop the bot."""
    for owner_id in Config.bot_owner_ids():
        try:
            await client.send_message(
                owner_id,
                startup_notification_text(bot_info),
            )
        except Exception:
            LOGGER.warning(
                "Bot is running, but startup notification could not be delivered "
                "to bot admin %s",
                owner_id,
                exc_info=True,
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
        LOGGER.info("Scheduled pending forwarding jobs in the background")
        await notify_bot_owner_started(client, bot_info)
        await idle()
    finally:
        await cancel_pending_forwards()
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
