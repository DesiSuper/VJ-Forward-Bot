"""Kurigram inline keyboard helpers with consistent semantic colors."""

from __future__ import annotations

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton as _InlineKeyboardButton


_DANGER_WORDS = ("cancel", "remove", "delete", "clear", "stop", "terminate", "reset", "off")
_SUCCESS_WORDS = ("start", "connect", "add", "save", "done", "confirm", "apply", "retry")


def _button_style(text: str, callback_data: str | bytes | None = None) -> ButtonStyle:
    """Choose a readable green/blue/red style from the action's intent."""
    label = text.casefold()
    action = callback_data.decode(errors="ignore") if isinstance(callback_data, bytes) else str(callback_data or "")
    action = action.casefold()

    if text.startswith("🚫") or any(word in label or word in action for word in _DANGER_WORDS):
        return ButtonStyle.DANGER
    if text.startswith("✅") or any(word in label or word in action for word in _SUCCESS_WORDS):
        return ButtonStyle.SUCCESS
    return ButtonStyle.PRIMARY


def InlineKeyboardButton(*args, **kwargs):
    """Build a Kurigram inline button while preserving old positional callback usage.

    Older Pyrogram-compatible forks accepted ``callback_data`` as the second
    positional argument. Kurigram uses that position for a custom emoji ID, so
    translate existing call sites here and always set a semantic button style.
    """
    if args:
        text, *positional = args
        if len(positional) > 1:
            raise TypeError("InlineKeyboardButton accepts at most text and callback_data positionally")
        if positional:
            if "callback_data" in kwargs:
                raise TypeError("callback_data was supplied both positionally and by keyword")
            kwargs["callback_data"] = positional[0]
    else:
        try:
            text = kwargs.pop("text")
        except KeyError as error:
            raise TypeError("InlineKeyboardButton requires text") from error

    kwargs.setdefault("style", _button_style(str(text), kwargs.get("callback_data")))
    return _InlineKeyboardButton(text=text, **kwargs)
