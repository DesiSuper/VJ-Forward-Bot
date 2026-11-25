"""Small private-chat prompt helper compatible with Kurigram's Client API."""

from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
import weakref
from dataclasses import dataclass
from typing import Any

from pyrogram import Client, StopPropagation, filters
from pyrogram.handlers import CallbackQueryHandler, MessageHandler
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


@dataclass
class _PromptChoice:
    text: str
    id: int
    callback_query: Any = None
    from_callback: bool = True


@dataclass
class _PendingPrompt:
    future: asyncio.Future[Any]
    message_filter: Any = None
    callback_values: dict[str, str] | None = None
    defer_callback_answer: bool = False


_PENDING: dict[tuple[int, int], _PendingPrompt] = {}
_PENDING_CALLBACKS: dict[str, _PendingPrompt] = {}
_REGISTERED_CLIENTS: weakref.WeakSet[Client] = weakref.WeakSet()
logger = logging.getLogger(__name__)


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


async def _capture_prompt_callback(client: Client, query: Any) -> None:
    pending = _PENDING_CALLBACKS.get(query.data)
    if pending is None or pending.future.done():
        return

    if not pending.defer_callback_answer:
        await query.answer()
    pending.future.set_result(
        _PromptChoice(
            text=pending.callback_values[query.data],
            id=query.message.id,
            callback_query=query,
        )
    )
    raise StopPropagation


def _ensure_private_message_handler(client: Client) -> None:
    if client not in _REGISTERED_CLIENTS:
        client.add_handler(
            MessageHandler(_capture_private_message, filters.private),
            group=-1,
        )
        client.add_handler(CallbackQueryHandler(_capture_prompt_callback), group=-1)
        _REGISTERED_CLIENTS.add(client)


async def ask(
    client: Client,
    chat_id: int,
    text: str,
    *,
    filters: Any = None,
    timeout: float | None = None,
    delete_prompt_and_reply: bool = False,
    callback_choices: dict[str, str] | None = None,
    return_prompt: bool = False,
    defer_callback_answer: bool = False,
    **send_options: Any,
) -> Any:
    """Send a prompt and wait for a matching private message or button choice.

    Kurigram's current ``Client`` does not include Pyromod's ``Client.ask``;
    keeping this helper local avoids a dependency on that removed extension.
    """
    _ensure_private_message_handler(client)
    key = (id(client), int(chat_id))
    if key in _PENDING:
        raise InputPromptAlreadyActive("A reply is already pending in this chat")

    future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    callback_values = None
    if callback_choices:
        token = uuid.uuid4().hex
        callback_values = {
            f"prompt_choice#{token}#{index}": value
            for index, value in enumerate(callback_choices.values())
        }
        send_options["reply_markup"] = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(label, callback_data=callback_data)]
                for label, callback_data in zip(callback_choices, callback_values)
            ]
        )
    pending = _PendingPrompt(
        future=future,
        message_filter=filters,
        callback_values=callback_values,
        defer_callback_answer=defer_callback_answer,
    )
    _PENDING[key] = pending
    if callback_values:
        _PENDING_CALLBACKS.update(
            {callback_data: pending for callback_data in callback_values}
        )
    prompt_message = None
    response = None
    try:
        prompt_message = await client.send_message(
            chat_id=chat_id, text=text, **send_options
        )
        if timeout is None:
            response = await future
        else:
            response = await asyncio.wait_for(future, timeout=timeout)
        return (response, prompt_message) if return_prompt else response
    finally:
        if _PENDING.get(key) is pending:
            _PENDING.pop(key, None)
        for callback_data in callback_values or {}:
            if _PENDING_CALLBACKS.get(callback_data) is pending:
                _PENDING_CALLBACKS.pop(callback_data, None)
        if not future.done():
            future.cancel()
        if delete_prompt_and_reply and prompt_message is not None:
            message_ids = [prompt_message.id]
            if response is not None and not getattr(response, "from_callback", False):
                message_ids.append(response.id)
            try:
                await client.delete_messages(chat_id, message_ids)
            except Exception:
                logger.debug(
                    "Could not delete consumed input prompt in chat %s",
                    chat_id,
                    exc_info=True,
                )
