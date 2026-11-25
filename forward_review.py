"""Format a readable summary of a user's saved forwarding options."""

from __future__ import annotations

from html import escape
from typing import Any

from forwarding_delay import normalize_random_gap

PENDING_REVIEW: dict[int, str] = {}

MESSAGE_TYPE_LABELS = (
    ("text", "Text"),
    ("document", "Documents"),
    ("video", "Videos"),
    ("photo", "Photos"),
    ("audio", "Audio"),
    ("video_note", "Video notes"),
)


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.replace("|", ",").split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(part).strip() for part in value if str(part).strip()]
    return [str(value)]


def _render_values(value: Any) -> str:
    values = _values(value)
    rendered = ", ".join(values) if values else "None"
    if len(rendered) > 400:
        rendered = rendered[:397] + "…"
    return escape(rendered)


def _size_bound(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def format_forwarding_settings(config: dict[str, Any]) -> str:
    """Render the effective filters and options as concise Telegram HTML."""
    message_filters = config.get("filters") or {}
    if not isinstance(message_filters, dict):
        message_filters = {}
    selected_types = [
        label
        for key, label in MESSAGE_TYPE_LABELS
        if message_filters.get(key, True)
    ]
    selected_text = ", ".join(selected_types) if selected_types else "None"

    gap_min, gap_max = normalize_random_gap(config.get("random_gap"))
    if gap_min == gap_max == 0:
        gap_text = "Off (default pacing)"
    elif gap_min == gap_max:
        gap_text = f"{gap_min} sec fixed"
    else:
        gap_text = f"{gap_min}–{gap_max} sec random"

    minimum = _size_bound(config.get("min_size"))
    maximum = _size_bound(config.get("max_size"))
    if minimum and maximum:
        size_text = f"{minimum}–{maximum} MB"
    elif minimum:
        size_text = f"At least {minimum} MB"
    elif maximum:
        size_text = f"Up to {maximum} MB"
    else:
        size_text = "No size limit"

    caption_text = "Custom caption" if config.get("caption") else "Original caption"
    transfer_text = "Forward original messages" if config.get("forward_tag") else "Copy messages"
    keyword_text = _render_values(config.get("keywords"))
    extension_text = _render_values(config.get("extension"))

    return (
        "<b>⚙️ Selected forwarding settings</b>\n"
        f"<b>Message types:</b> {escape(selected_text)}\n"
        f"<b>Transfer mode:</b> {transfer_text}\n"
        f"<b>Caption:</b> {caption_text}\n"
        f"<b>Skip duplicates:</b> {'On' if config.get('duplicate', True) else 'Off'}\n"
        f"<b>Protect content:</b> {'On' if config.get('protect') else 'Off'}\n"
        f"<b>File size:</b> {size_text}\n"
        f"<b>Excluded keywords:</b> {keyword_text}\n"
        f"<b>Excluded extensions:</b> {extension_text}\n"
        "<b>Always skipped:</b> Voice messages, animations, stickers, and polls\n"
        "<b>Custom message buttons:</b> Unavailable\n"
        f"<b>Random delay:</b> {gap_text}"
    )


def format_task_setup_preview(
    review: dict[str, Any],
    config: dict[str, Any],
    skip: int,
    *,
    awaiting_skip: bool = False,
) -> str:
    """Summarize the task and effective filters in the skip/review message."""
    skip_line = (
        "enter a number (default: <code>0</code>)"
        if awaiting_skip
        else f"<code>{int(skip)}</code>"
    )
    text = (
        "<b>Forwarding setup</b>\n\n"
        f"<b>Account:</b> {escape(str(review.get('botname') or 'Connected account'))} "
        f"(@{escape(str(review.get('botuname') or 'no username'))})\n"
        f"<b>Source:</b> {escape(str(review.get('from_chat') or 'Unknown'))}\n"
        f"<b>Destination:</b> {escape(str(review.get('to_chat') or 'Unknown'))}\n\n"
        f"{format_forwarding_settings(config)}\n\n"
        f"<b>Messages to skip:</b> {skip_line}"
    )
    if awaiting_skip:
        text += "\nType a number, or tap <b>Start (skip 0)</b> to start now."
    return text
