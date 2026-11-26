"""Application configuration and small runtime state containers.

Values are read once at process startup. Keep configuration in environment
variables; do not commit secrets to the repository.
"""

from __future__ import annotations

import os
import re
from typing import ClassVar


def _integer(name: str, default: int = 0) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid integer") from exc


def _integer_list(name: str, fallback_name: str) -> tuple[int, ...]:
    """Parse Telegram IDs separated by whitespace and/or commas."""
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        raw_value = os.getenv(fallback_name, "").strip()
    if not raw_value:
        return ()

    values = []
    for item in re.split(r"[\s,]+", raw_value):
        if not item:
            continue
        try:
            value = int(item)
        except ValueError as exc:
            raise ValueError(
                f"{name} must contain Telegram user IDs separated by spaces or commas"
            ) from exc
        if value not in values:
            values.append(value)
    return tuple(values)


class Config:
    """Environment-backed settings kept compatible with existing plugins."""

    API_ID = _integer("API_ID")
    API_HASH = os.getenv("API_HASH", "").strip()
    BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
    BOT_SESSION = os.getenv("BOT_SESSION", "forwordbot").strip() or "forwordbot"
    DATABASE_URI = os.getenv("DATABASE_URI", "").strip()
    CREDENTIAL_ENCRYPTION_KEY = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    DATABASE_NAME = os.getenv("DATABASE_NAME", "forword-bot").strip() or "forword-bot"
    BOT_OWNERS = _integer_list("BOT_OWNER", "BOT_OWNER_ID")
    # Keep a scalar primary ID for older integrations while allowing all admins.
    BOT_OWNER = BOT_OWNERS[0] if BOT_OWNERS else 0

    @classmethod
    def bot_owner_ids(cls) -> tuple[int, ...]:
        """Return all configured admins and remain compatible with patched legacy IDs."""
        owners = list(getattr(cls, "BOT_OWNERS", ()) or ())
        primary = getattr(cls, "BOT_OWNER", 0)
        if primary:
            owners.append(primary)
        return tuple(dict.fromkeys(int(owner_id) for owner_id in owners if owner_id))

    @classmethod
    def is_bot_owner(cls, user_id: int) -> bool:
        try:
            return int(user_id) in cls.bot_owner_ids()
        except (TypeError, ValueError):
            return False

    @classmethod
    def validate(cls) -> None:
        """Fail early with an actionable message if required secrets are absent."""
        missing = [
            name
            for name, value in (
                ("API_ID", cls.API_ID),
                ("API_HASH", cls.API_HASH),
                ("BOT_TOKEN", cls.BOT_TOKEN),
                ("DATABASE_URI", cls.DATABASE_URI),
                ("CREDENTIAL_ENCRYPTION_KEY", cls.CREDENTIAL_ENCRYPTION_KEY),
                ("BOT_OWNER (or BOT_OWNER_ID)", cls.bot_owner_ids()),
            )
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required environment variable(s): {joined}")
        if cls.API_ID < 1:
            raise RuntimeError("API_ID must be a positive integer")
        if not cls.bot_owner_ids():
            raise RuntimeError("BOT_OWNER (or BOT_OWNER_ID) must include a Telegram user ID")
        if any(owner_id < 1 for owner_id in cls.bot_owner_ids()):
            raise RuntimeError("Every BOT_OWNER ID must be a positive Telegram user ID")
        from cryptography.fernet import Fernet

        try:
            Fernet(cls.CREDENTIAL_ENCRYPTION_KEY.encode("ascii"))
        except (UnicodeEncodeError, ValueError) as error:
            raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key") from error


class temp:
    """Volatile state shared by the existing forwarding handlers."""

    lock: ClassVar[dict[int, bool]] = {}
    CANCEL: ClassVar[dict[int, bool]] = {}
    forwardings: ClassVar[int] = 0
    BANNED_USERS: ClassVar[list[int]] = []
    IS_FRWD_CHAT: ClassVar[list[int]] = []
