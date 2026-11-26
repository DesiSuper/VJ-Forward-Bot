"""Download public Instagram posts/reels and send the media back in Telegram.

Only public, directly accessible Instagram URLs are supported. This plugin does
not use cookies, credentials, or private-account workarounds.
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from pyrogram import Client, filters

from config import Config
from database import db

logger = logging.getLogger(__name__)
_MAX_DOWNLOAD_BYTES = 45 * 1024 * 1024
_MAX_PHOTO_BYTES = 10 * 1024 * 1024
_DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
_INSTAGRAM_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "instagr.am",
    "www.instagr.am",
}
_INSTAGRAM_LINK_PATTERN = re.compile(
    r"(?<![\w.-])(?:https?://)?(?:(?:www|m)\.)?(?:instagram\.com|instagr\.am)/[^\s<>()]+",
    re.IGNORECASE,
)
_VIDEO_EXTENSIONS = {".mp4"}
_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class DownloadedInstagramMedia:
    path: str
    title: str
    duration: int
    width: int
    height: int


class InvalidInstagramURL(ValueError):
    """Raised when an input URL is not an allowed Instagram URL."""


class InstagramDownloadError(RuntimeError):
    """Raised for unsupported, inaccessible, or oversized Instagram media."""


def validate_instagram_url(value: str) -> str:
    """Validate and normalize an Instagram URL before passing it to yt-dlp."""
    raw_url = value.strip()
    if not raw_url:
        raise InvalidInstagramURL("Send a public Instagram post, reel, or TV link.")

    if not re.match(r"^https?://", raw_url, re.IGNORECASE):
        raw_url = f"https://{raw_url}"
    try:
        parsed = urlsplit(raw_url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as error:
        raise InvalidInstagramURL("That is not a valid Instagram link.") from error
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or host not in _INSTAGRAM_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise InvalidInstagramURL("That is not a valid Instagram link.")

    if not parsed.path or parsed.path == "/":
        raise InvalidInstagramURL("Send a link to a post, reel, or IGTV video.")
    return raw_url


def download_instagram_media(url: str, output_dir: str) -> tuple[str, str]:
    """Download a single public Instagram item; intended to run in a worker thread."""
    try:
        from yt_dlp import YoutubeDL
    except ImportError as error:
        raise InstagramDownloadError(
            "Instagram downloader dependency is not installed."
        ) from error

    options = {
        "outtmpl": str(Path(output_dir) / "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "max_filesize": _MAX_DOWNLOAD_BYTES,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "overwrites": True,
    }
    try:
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            if not info:
                raise InstagramDownloadError(
                    "No downloadable media was found at that link."
                )
            if info.get("entries"):
                info = next((entry for entry in info["entries"] if entry), None)
            if not info:
                raise InstagramDownloadError(
                    "No downloadable media was found at that link."
                )

            candidates = []
            for key in ("filepath", "_filename"):
                candidate = info.get(key)
                if candidate:
                    candidates.append(Path(candidate))
            for item in info.get("requested_downloads") or ():
                candidate = item.get("filepath") or item.get("_filename")
                if candidate:
                    candidates.append(Path(candidate))
            candidates.append(Path(downloader.prepare_filename(info)))
            candidates.extend(Path(output_dir).glob("*"))

            media_path = next((path for path in candidates if path.is_file()), None)
            if media_path is None:
                raise InstagramDownloadError(
                    "Instagram did not provide a downloadable media file."
                )
            if media_path.stat().st_size > _MAX_DOWNLOAD_BYTES:
                raise InstagramDownloadError(
                    "The media is too large to send through Telegram (limit: 45 MB)."
                )

            title = str(info.get("title") or "Instagram media").strip()
            duration = max(0, int(float(info.get("duration") or 0)))
            width = max(0, int(info.get("width") or 0))
            height = max(0, int(info.get("height") or 0))
            return DownloadedInstagramMedia(
                str(media_path), title[:900], duration, width, height
            )
    except InstagramDownloadError:
        raise
    except Exception as error:
        logger.info("Instagram media download failed: %s", type(error).__name__)
        raise InstagramDownloadError(
            "Could not download that link. It may be private, unavailable, or temporarily restricted."
        ) from error


@Client.on_message(filters.private & filters.command("insta"))
async def instagram_toggle_command(client, message):
    """Let the configured bot owner toggle their private Instagram downloader."""
    user = getattr(message, "from_user", None)
    if user is None or int(user.id) != int(Config.BOT_OWNER):
        return

    parts = (message.text or "").split(maxsplit=1)
    action = parts[1].strip().lower() if len(parts) > 1 else "status"
    if action == "status":
        enabled = await db.get_instagram_enabled(user.id)
        state = "ON" if enabled else "OFF"
        return await message.reply_text(
            f"Instagram downloads are <b>{state}</b> for you."
        )
    if action not in {"on", "off"}:
        return await message.reply_text(
            "Usage: <code>/insta on</code> or <code>/insta off</code>"
        )

    enabled = action == "on"
    await db.set_instagram_enabled(user.id, enabled)
    state = "ON" if enabled else "OFF"
    return await message.reply_text(f"Instagram downloads are <b>{state}</b> for you.")


@Client.on_message(
    filters.private & filters.text & filters.regex(_INSTAGRAM_LINK_PATTERN)
)
async def instagram_link_handler(client, message):
    """Download public Instagram media when a user sends an Instagram URL."""
    url_match = _INSTAGRAM_LINK_PATTERN.search(message.text or "")
    if not url_match:
        return
    user = getattr(message, "from_user", None)
    if user is None or int(user.id) != int(Config.BOT_OWNER):
        return
    if not await db.get_instagram_enabled(user.id):
        return

    try:
        url = validate_instagram_url(url_match.group(0).rstrip(".,!?;:"))
    except InvalidInstagramURL as error:
        return await message.reply_text(str(error))

    status = await message.reply_text("Downloading public Instagram media…")
    try:
        async with _DOWNLOAD_SEMAPHORE:
            with tempfile.TemporaryDirectory(prefix="instagram-download-") as directory:
                downloaded = await asyncio.to_thread(
                    download_instagram_media, url, directory
                )
                media_path = Path(downloaded.path)
                caption = escape(downloaded.title)
                suffix = media_path.suffix.lower()
                if (
                    suffix in _PHOTO_EXTENSIONS
                    and media_path.stat().st_size <= _MAX_PHOTO_BYTES
                ):
                    await client.send_photo(
                        message.chat.id, str(media_path), caption=caption
                    )
                elif (
                    suffix in _VIDEO_EXTENSIONS
                    and downloaded.duration > 0
                    and downloaded.width > 0
                    and downloaded.height > 0
                ):
                    await client.send_video(
                        message.chat.id,
                        str(media_path),
                        caption=caption,
                        duration=downloaded.duration,
                        width=downloaded.width,
                        height=downloaded.height,
                        supports_streaming=True,
                        no_sound=False,
                    )
                else:
                    await client.send_document(
                        message.chat.id, str(media_path), caption=caption
                    )
        await status.delete()
    except InstagramDownloadError as error:
        await status.edit_text(escape(str(error)))
    except Exception:
        logger.exception(
            "Could not send Instagram media to Telegram user %s", message.from_user.id
        )
        try:
            await status.edit_text(
                "Could not send this media. It may exceed Telegram's upload limit."
            )
        except Exception:
            logger.debug("Could not update Instagram download status", exc_info=True)
