"""Global word and URL blacklist moderation for groups.

Group administrators manage the shared blacklist with /blacklist commands. Any
matching group message is deleted silently; no user warning is sent.
"""

from __future__ import annotations

import logging
import re
import time
from html import escape
from urllib.parse import urlsplit

from pyrogram import Client, StopPropagation, filters

from database import db

logger = logging.getLogger(__name__)
_CACHE_TTL_SECONDS = 15.0
_BLACKLIST_CACHE: dict[str, list[str]] | None = None
_BLACKLIST_CACHE_AT = 0.0
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


def word_is_blacklisted(text: str, words: list[str]) -> bool:
    """Match a whole word or phrase without matching inside larger words."""
    for word in words:
        term = word.strip()
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


def url_is_blacklisted(text: str, blocked_urls: list[str]) -> bool:
    """Match a blocked host (including subdomains) and optional path prefix."""
    for candidate in _extract_urls(text):
        candidate_host, _, candidate_path = candidate.partition("/")
        for blocked in blocked_urls:
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


async def _get_global_blacklist(*, refresh: bool = False) -> dict[str, list[str]]:
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


async def _is_group_admin(client, message) -> bool:
    if message.from_user is None:
        return False
    try:
        member = await client.get_chat_member(message.chat.id, message.from_user.id)
    except Exception:
        logger.info("Could not verify group admin for blacklist command", exc_info=True)
        return False
    status = getattr(member.status, "value", member.status)
    return str(status).lower() in {"owner", "creator", "administrator"}


def _blacklist_help() -> str:
    return (
        "<b>Global group blacklist</b>\n"
        "Entries added by a group admin apply in every group where this bot is present. "
        "Matching messages are deleted silently.\n\n"
        "<code>/blacklist word add phrase</code>\n"
        "<code>/blacklist word remove phrase</code>\n"
        "<code>/blacklist url add spam.example</code>\n"
        "<code>/blacklist url add https://spam.example/path</code>\n"
        "<code>/blacklist url remove spam.example</code>\n"
        "<code>/blacklist list</code>"
    )


@Client.on_message(filters.group & filters.command("blacklist"))
async def manage_global_blacklist(client, message):
    """Let group administrators maintain the shared word/URL blacklist."""
    if not await _is_group_admin(client, message):
        return await message.reply_text(
            "Only this group's administrators can manage the blacklist."
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
            lines.extend(f"• <code>{escape(entry)}</code>" for entry in entries[:50])
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

    if kind == "word":
        value = " ".join(value.split())
        if len(value) < 3 or len(value) > 80:
            return await message.reply_text(
                "Blacklist words/phrases must be 3–80 characters."
            )
        value = value.casefold()
    else:
        try:
            value = normalize_blacklisted_url(value)
        except ValueError as error:
            return await message.reply_text(str(error))

    try:
        if operation == "add":
            await db.add_global_blacklist_entry(kind, value)
            result = "added"
        else:
            await db.remove_global_blacklist_entry(kind, value)
            result = "removed"
    except Exception:
        logger.exception("Could not update the global blacklist")
        return await message.reply_text(
            "Could not update the blacklist right now. Please try again."
        )

    _invalidate_blacklist_cache()
    scope = "all groups"
    return await message.reply_text(
        f"<b>✓ {kind.title()} blacklist entry {result} for {scope}.</b>\n<code>{escape(value)}</code>"
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
    if not word_is_blacklisted(text, blacklist["words"]) and not url_is_blacklisted(
        text, blacklist["urls"]
    ):
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
