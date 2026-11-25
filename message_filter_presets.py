"""Dependency-free presets for selecting which Telegram message types to forward."""

from __future__ import annotations

MESSAGE_TYPES = (
    "text",
    "document",
    "video",
    "photo",
    "audio",
    "voice",
    "video_note",
    "animation",
    "sticker",
    "poll",
)

FILTER_PRESETS: dict[str, tuple[str, ...]] = {
    "all": MESSAGE_TYPES,
    "media": ("document", "video", "photo", "audio", "voice", "video_note", "animation", "sticker"),
    "video_photo_audio": ("video", "photo", "audio"),
    "video": ("video",),
    "photo": ("photo",),
    "audio": ("audio",),
    "document": ("document",),
}


def filters_for_preset(name: str) -> dict[str, bool]:
    """Build a complete enabled/disabled message-type map for a named preset."""
    if name not in FILTER_PRESETS:
        raise ValueError(f"Unknown message-type preset: {name}")
    enabled = set(FILTER_PRESETS[name])
    return {message_type: message_type in enabled for message_type in MESSAGE_TYPES}
