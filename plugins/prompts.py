"""Small private-chat prompt helper compatible with Kurigram's Client API."""

from __future__ import annotations

import asyncio
import inspect
import weakref
from dataclasses import dataclass
from typing import Any

from pyrogram import Client, StopPropagation, filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message


@dataclass
class _PendingPrompt:
    future: asyncio.Future[Message]
    message_filter: Any = None


_PENDING: dict[tuple[int, int], _PendingPrompt] = {}
_REGISTERED_CLIENTS: weakref.WeakSet[Client] = weakref.WeakSet()


class InputPromptAlreadyActive(RuntimeError):
    """Raised if a second input flow is opened in the same private chat."""


async def _capture_private_message(client: Client, message: Message) -> None:
    key = (id(client), message.chat.id)
    pending = _PENDING.get(key)
    if pending is None or pending.future.done():
        return

    if pending.message_filter is not None:
        result = pending.message_filter(client, message)
        if inspect.isawaitable(result):
            result = await result
        if not result:
            return

    pending.future.set_result(message)
    # A reply consumed by a prompt must not also trigger commands or another
    # conversation handler registered in later dispatcher groups.
    raise StopPropagation


def _ensure_private_message_handler(client: Client) -> None:
    if client not in _REGISTERED_CLIENTS:
        client.add_handler(
            MessageHandler(_capture_private_message, filters.private),
            group=-1,
        )
        _REGISTERED_CLIENTS.add(client)


async def ask(
    client: Client,
    chat_id: int,
    text: str,
    *,
    filters: Any = None,
    timeout: float | None = None,
    **send_options: Any,
) -> Message:
    """Send a prompt and wait for the next matching private message.

    Kurigram's current ``Client`` does not include Pyromod's ``Client.ask``;
    keeping this helper local avoids a dependency on that removed extension.
    """
    _ensure_private_message_handler(client)
    key = (id(client), int(chat_id))
    if key in _PENDING:
        raise InputPromptAlreadyActive("A reply is already pending in this chat")

    future: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
    pending = _PendingPrompt(future=future, message_filter=filters)
    _PENDING[key] = pending
    try:
        await client.send_message(chat_id=chat_id, text=text, **send_options)
        if timeout is None:
            return await future
        return await asyncio.wait_for(future, timeout=timeout)
    finally:
        if _PENDING.get(key) is pending:
            _PENDING.pop(key, None)
        if not future.done():
            future.cancel()
