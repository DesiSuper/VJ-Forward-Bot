"""Application configuration and small runtime state containers.

Values are read once at process startup. Keep configuration in environment
variables; do not commit secrets to the repository.
"""

from __future__ import annotations

import os
from typing import ClassVar


def _integer(name: str, default: int = 0) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid integer") from exc


class Config:
    """Environment-backed settings kept compatible with existing plugins."""

    API_ID = _integer("API_ID")
    API_HASH = os.getenv("API_HASH", "").strip()
    BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
    BOT_SESSION = os.getenv("BOT_SESSION", "forwordbot").strip() or "forwordbot"
    DATABASE_URI = os.getenv("DATABASE_URI", "").strip()
    DATABASE_NAME = os.getenv("DATABASE_NAME", "forword-bot").strip() or "forword-bot"
    BOT_OWNER = _integer("BOT_OWNER", _integer("BOT_OWNER_ID"))

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
                ("BOT_OWNER (or BOT_OWNER_ID)", cls.BOT_OWNER),
            )
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required environment variable(s): {joined}")
        if cls.API_ID < 1:
            raise RuntimeError("API_ID must be a positive integer")
        if cls.BOT_OWNER < 1:
            raise RuntimeError("BOT_OWNER must be a positive Telegram user ID")


class temp:
    """Volatile state shared by the existing forwarding handlers."""

    lock: ClassVar[dict[int, bool]] = {}
    CANCEL: ClassVar[dict[int, bool]] = {}
    forwardings: ClassVar[int] = 0
    BANNED_USERS: ClassVar[list[int]] = []
    IS_FRWD_CHAT: ClassVar[list[int]] = []
