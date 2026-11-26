"""Global word and URL blacklist moderation for groups.

Group administrators manage the shared blacklist with /blacklist commands. Any
matching group message is deleted silently; no user warning is sent.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from html import escape
from urllib.parse import urlsplit

from pyrogram import Client, StopPropagation, filters

from config import Config
from database import db

logger = logging.getLogger(__name__)
_CACHE_TTL_SECONDS = 15.0
_BLACKLIST_CACHE: dict[str, list[str]] | None = None
_BLACKLIST_CACHE_AT = 0.0
_PENDING_DELETIONS: set[asyncio.Task] = set()
_DURATION_RE = re.compile(
    r"^(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes)$", re.I
)
_URL_CANDIDATE = re.compile(
    r"(?i)(?<![\w@.-])(?:https?://)?(?:www\.)?"
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}"
    r"(?::\d+)?(?:/[^\s<>\[\]{}\"']*)?"
)


def normalize_blacklisted_url(value: str) -> str:
    """Normalize a domain or URL to a host and optional path prefix."""
    raw = value.strip().rstrip(".,!?;:)]}")
    if not raw:
        raise ValueError("Enter a domain or URL, such as <code>spam.example</code>.")
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as error:
        raise ValueError("That domain or URL is invalid.") from error

    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not host
        or "." not in host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 80, 443}
    ):
        raise ValueError("Enter a valid domain or http/https URL.")
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    if path == "/":
        path = ""
    return host + path


def parse_delay(value: str) -> int:
    """Parse seconds/minutes such as ``30s`` or ``2 minutes`` (up to a day)."""
    match = _DURATION_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError("Use a delay like <code>30s</code> or <code>2m</code>.")
    amount = int(match.group(1))
    unit = match.group(2).lower()
    seconds = amount * (60 if unit.startswith("m") else 1)
    if seconds > 86_400:
        raise ValueError("The maximum delete delay is 24 hours (1440m).")
    return seconds


def _entry_value(entry: str | dict) -> str:
    return entry if isinstance(entry, str) else entry.get("value", "")


def _entry_delay(entry: str | dict) -> int:
    if isinstance(entry, str):
        return 0
    try:
        return max(0, int(entry.get("delay_seconds", 0)))
    except (TypeError, ValueError):
        return 0


def _format_delay(delay_seconds: int) -> str:
    if delay_seconds >= 60 and delay_seconds % 60 == 0:
        return f"{delay_seconds // 60}m"
    return f"{delay_seconds}s"


def word_is_blacklisted(text: str, words: list[str | dict]) -> bool:
    """Match a whole word or phrase without matching inside larger words."""
    for entry in words:
        term = _entry_value(entry).strip()
        if term and re.search(
            r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE
        ):
            return True
    return False


def _extract_urls(text: str) -> list[str]:
    urls = []
    for match in _URL_CANDIDATE.finditer(text):
        candidate = match.group(0).rstrip(".,!?;:)]}")
        try:
            urls.append(normalize_blacklisted_url(candidate))
        except ValueError:
            continue
    return urls


def url_is_blacklisted(text: str, blocked_urls: list[str | dict]) -> bool:
    """Match a blocked host (including subdomains) and optional path prefix."""
    for candidate in _extract_urls(text):
        candidate_host, _, candidate_path = candidate.partition("/")
        for entry in blocked_urls:
            blocked = _entry_value(entry)
            blocked_host, separator, blocked_path = blocked.partition("/")
            if candidate_host != blocked_host and not candidate_host.endswith(
                "." + blocked_host
            ):
                continue
            if not separator or not blocked_path:
                return True
            if candidate_path == blocked_path or candidate_path.startswith(
                blocked_path + "/"
            ):
                return True
    return False


def matching_entry_delays(text: str, blacklist: dict[str, list[dict]]) -> list[int]:
    """Return the delays for every blacklist rule matching a message."""
    delays = []
    for entry in blacklist["words"]:
        value = _entry_value(entry).strip()
        if value and re.search(
            r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.IGNORECASE
        ):
            delays.append(_entry_delay(entry))

    urls = _extract_urls(text)
    for entry in blacklist["urls"]:
        blocked_host, separator, blocked_path = _entry_value(entry).partition("/")
        for candidate in urls:
            candidate_host, _, candidate_path = candidate.partition("/")
            if candidate_host != blocked_host and not candidate_host.endswith(
                "." + blocked_host
            ):
                continue
            if (
                not separator
                or not blocked_path
                or candidate_path == blocked_path
                or candidate_path.startswith(blocked_path + "/")
            ):
                delays.append(_entry_delay(entry))
                break
    return delays


async def _get_global_blacklist(*, refresh: bool = False) -> dict[str, list[dict]]:
    global _BLACKLIST_CACHE, _BLACKLIST_CACHE_AT
    now = time.monotonic()
    if (
        not refresh
        and _BLACKLIST_CACHE is not None
        and now - _BLACKLIST_CACHE_AT < _CACHE_TTL_SECONDS
    ):
        return _BLACKLIST_CACHE
    try:
        _BLACKLIST_CACHE = await db.get_global_blacklist()
        _BLACKLIST_CACHE_AT = now
    except Exception:
        logger.exception("Could not load the global group blacklist")
        if _BLACKLIST_CACHE is None:
            _BLACKLIST_CACHE = {"words": [], "urls": []}
        _BLACKLIST_CACHE_AT = now
    return _BLACKLIST_CACHE


def _invalidate_blacklist_cache() -> None:
    global _BLACKLIST_CACHE, _BLACKLIST_CACHE_AT
    _BLACKLIST_CACHE = None
    _BLACKLIST_CACHE_AT = 0.0


def _is_bot_owner_in_private(message) -> bool:
    """Only allow the configured bot owner to manage the blacklist in PM."""
    user = message.from_user
    chat_type = getattr(message.chat.type, "value", message.chat.type)
    return (
        user is not None
        and int(user.id) == int(Config.BOT_OWNER)
        and str(chat_type).lower() == "private"
    )


def _blacklist_help() -> str:
    return (
        "<b>📋 Group moderation help</b>\n\n"
        "The blacklist is shared across all groups. Only the bot owner can manage it, "
        "using the commands in a private chat with the bot. Matching messages are "
        "silently deleted. Entries stay blocked until removed.\n\n"
        "<b>Add entries</b>\n"
        "<code>/blacklist word add bad phrase</code>\n"
        "<code>/blacklist url add instagram.com</code>\n"
        "A domain blocks all its paths and subdomains; for example, "
        "<code>instagram.com</code> also matches <code>instagram.com/reel/…</code> "
        "and <code>www.instagram.com</code>. No <code>/*</code> is needed.\n\n"
        "<b>Set per-entry delete delay</b>\n"
        "<code>/blacklistdelay word bad phrase 30s</code>\n"
        "<code>/blacklistdelay url instagram.com 2m</code>\n"
        "Use <code>0s</code> for immediate deletion. The delay is how long a "
        "matching message waits before deletion; it does not expire the blacklist entry.\n\n"
        "<b>Remove or view entries</b>\n"
        "<code>/blacklist word remove bad phrase</code>\n"
        "<code>/blacklist url remove instagram.com</code>\n"
        "<code>/blacklist list</code> (or <code>/blacklist list word</code> / "
        "<code>/blacklist list url</code>)\n\n"
        "Time formats: seconds (<code>30s</code>) or minutes (<code>2m</code>), "
        "up to 24 hours. The bot needs permission to delete group messages."
    )


@Client.on_message(filters.group & filters.command("ghelp"))
async def group_help(client, message):
    """Show group admins and members how group moderation commands work."""
    return await message.reply_text(_blacklist_help())


def _normalize_entry(kind: str, value: str) -> str:
    if kind == "word":
        value = " ".join(value.split())
        if len(value) < 3 or len(value) > 80:
            raise ValueError("Blacklist words/phrases must be 3–80 characters.")
        return value.casefold()
    return normalize_blacklisted_url(value)


@Client.on_message(filters.private & filters.command("blacklist"))
async def manage_global_blacklist(client, message):
    """Let only the configured bot owner manage the shared blacklist in PM."""
    if not _is_bot_owner_in_private(message):
        return await message.reply_text(
            "Only the bot owner can manage the blacklist in a private chat with the bot."
        )

    parts = (message.text or "").split(maxsplit=3)
    if len(parts) == 1 or parts[1].lower() in {"help", "?"}:
        return await message.reply_text(_blacklist_help())

    action = parts[1].lower()
    if action == "list":
        if len(parts) >= 3 and parts[2].lower() in {"word", "words"}:
            selected = {"words": (await _get_global_blacklist(refresh=True))["words"]}
        elif len(parts) >= 3 and parts[2].lower() in {"url", "urls"}:
            selected = {"urls": (await _get_global_blacklist(refresh=True))["urls"]}
        else:
            selected = await _get_global_blacklist(refresh=True)
        lines = ["<b>Global blacklist</b>"]
        for kind, entries in selected.items():
            lines.append(f"\n<b>{kind.title()} ({len(entries)}):</b>")
            lines.extend(
                f"• <code>{escape(_entry_value(entry))}</code> — "
                f"{'immediate' if _entry_delay(entry) == 0 else f'after {_format_delay(_entry_delay(entry))}'}"
                for entry in entries[:50]
            )
            if len(entries) > 50:
                lines.append(f"• and {len(entries) - 50} more")
            if not entries:
                lines.append("• None")
        return await message.reply_text("\n".join(lines))

    if action not in {"word", "words", "url", "urls"} or len(parts) < 4:
        return await message.reply_text(_blacklist_help())
    kind = "word" if action in {"word", "words"} else "url"
    operation, value = parts[2].lower(), parts[3].strip()
    if operation not in {"add", "remove", "del", "delete"} or not value:
        return await message.reply_text(_blacklist_help())

    try:
        value = _normalize_entry(kind, value)
    except ValueError as error:
        return await message.reply_text(str(error))

    try:
        if operation == "add":
            await db.add_global_blacklist_entry(kind, value)
            result = "added (delete immediately)"
        else:
            await db.remove_global_blacklist_entry(kind, value)
            result = "removed"
    except Exception:
        logger.exception("Could not update the global blacklist")
        return await message.reply_text(
            "Could not update the blacklist right now. Please try again."
        )

    _invalidate_blacklist_cache()
    return await message.reply_text(
        f"<b>✓ {kind.title()} entry {result} for all groups.</b>\n"
        f"<code>{escape(value)}</code>"
    )


@Client.on_message(filters.private & filters.command("blacklistdelay"))
async def set_global_blacklist_delay(client, message):
    """Configure the per-entry delay in PM; only the configured bot owner may do so."""
    if not _is_bot_owner_in_private(message):
        return await message.reply_text(
            "Only the bot owner can manage blacklist delays in a private chat with the bot."
        )

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply_text(
            "Usage: <code>/blacklistdelay word phrase 30s</code> or "
            "<code>/blacklistdelay url spam.example 2m</code>. "
            "Use <code>0s</code> for immediate deletion."
        )

    kind_text, payload = parts[1].lower(), parts[2].strip()
    if kind_text not in {"word", "words", "url", "urls"}:
        return await message.reply_text(
            "Choose <code>word</code> or <code>url</code>, then the entry and its delay."
        )
    kind = "word" if kind_text in {"word", "words"} else "url"
    match = re.fullmatch(
        r"(.+?)\s+(\d+\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes))",
        payload,
        re.I,
    )
    if match is None:
        return await message.reply_text(
            "Add the delay at the end, e.g. <code>/blacklistdelay word phrase 30s</code>."
        )
    raw_value = match.group(1).strip()
    try:
        value = _normalize_entry(kind, raw_value)
        delay_seconds = parse_delay(match.group(2))
    except ValueError as error:
        return await message.reply_text(str(error))

    try:
        updated = await db.set_global_blacklist_entry_delay(kind, value, delay_seconds)
    except Exception:
        logger.exception("Could not update a global blacklist delay")
        return await message.reply_text(
            "Could not update the blacklist delay right now. Please try again."
        )
    if not updated:
        return await message.reply_text("That blacklist entry was not found.")

    _invalidate_blacklist_cache()
    delay_text = (
        "immediately" if delay_seconds == 0 else f"after {_format_delay(delay_seconds)}"
    )
    return await message.reply_text(
        f"<b>✓ {kind.title()} entry will be deleted {delay_text} in all groups:</b>\n"
        f"<code>{escape(value)}</code>"
    )


async def _delete_message_after(message, delay_seconds: int) -> None:
    """Delete a matching message after its rule's delay elapses."""
    try:
        await asyncio.sleep(delay_seconds)
        await message.delete()
        logger.info(
            "Deleted delayed blacklisted message in chat %s after %s seconds",
            message.chat.id,
            delay_seconds,
        )
    except Exception:
        logger.warning(
            "Could not delete delayed blacklisted message in group %s; "
            "check bot delete permissions and Telegram message age limits",
            message.chat.id,
            exc_info=True,
        )


@Client.on_message(filters.group & (filters.text | filters.caption), group=-1)
async def enforce_global_blacklist(client, message):
    """Silently delete group messages containing a blacklisted word or URL."""
    if message.from_user is not None and message.from_user.is_bot:
        return
    text = message.text or message.caption or ""
    if not text or text.lstrip().startswith("/"):
        return

    blacklist = await _get_global_blacklist()
    delays = matching_entry_delays(text, blacklist)
    if not delays:
        return

    # If multiple rules match the same message, honor the shortest configured
    # delay so a stricter matching rule is never held back by another entry.
    delay_seconds = min(delays)
    if delay_seconds > 0:
        task = asyncio.create_task(_delete_message_after(message, delay_seconds))
        _PENDING_DELETIONS.add(task)
        task.add_done_callback(_PENDING_DELETIONS.discard)
        return

    try:
        await message.delete()
        logger.info("Deleted blacklisted group message in chat %s", message.chat.id)
    except Exception:
        logger.warning(
            "Could not delete blacklisted message in group %s; check bot delete permissions",
            message.chat.id,
            exc_info=True,
        )
    raise StopPropagation
