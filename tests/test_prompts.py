import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pyrogram import StopPropagation, filters
from pyrogram.enums import ButtonStyle

from plugins.prompts import ask


class FakeClient:
    def __init__(self):
        self.handlers = []
        self.sent = []
        self.deleted = []
        self.message_sent = asyncio.Event()

    def add_handler(self, handler, group=0):
        self.handlers.append((handler, group))

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        self.message_sent.set()
        return SimpleNamespace(id=1)

    async def delete_messages(self, chat_id, message_ids):
        self.deleted.append((chat_id, message_ids))


class PromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_ask_sends_prompt_and_consumes_matching_private_reply(self):
        client = FakeClient()
        prompt_task = asyncio.create_task(
            ask(
                client,
                12345,
                "Send the BotFather token message",
                filters=filters.text,
                timeout=2,
            )
        )
        await client.message_sent.wait()

        self.assertEqual(client.sent[0]["chat_id"], 12345)
        self.assertEqual(client.sent[0]["text"], "Send the BotFather token message")
        handler, group = client.handlers[0]
        self.assertEqual(group, -1)
        incoming = SimpleNamespace(
            chat=SimpleNamespace(id=12345),
            text="forwarded token",
        )
        with self.assertRaises(StopPropagation):
            await handler.callback(client, incoming)

        self.assertIs(await prompt_task, incoming)

    async def test_consumed_prompt_and_reply_can_be_deleted_together(self):
        client = FakeClient()
        prompt_task = asyncio.create_task(
            ask(
                client,
                12345,
                "Forward a source message",
                filters=filters.all,
                timeout=2,
                delete_prompt_and_reply=True,
            )
        )
        await client.message_sent.wait()
        handler, _ = client.handlers[0]
        incoming = SimpleNamespace(
            id=2,
            chat=SimpleNamespace(id=12345),
            forward_origin=SimpleNamespace(date=object()),
        )
        with self.assertRaises(StopPropagation):
            await handler.callback(client, incoming)

        self.assertIs(await prompt_task, incoming)
        self.assertEqual(client.deleted, [(12345, [1, 2])])

    async def test_callback_choice_returns_value_and_deletes_prompt(self):
        client = FakeClient()
        prompt_task = asyncio.create_task(
            ask(
                client,
                12345,
                "Skip messages?",
                filters=filters.text,
                timeout=2,
                delete_prompt_and_reply=True,
                callback_choices={"Skip (0)": "0"},
            )
        )
        await client.message_sent.wait()

        markup = client.sent[0]["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].text, "Skip (0)")
        callback_handler, group = client.handlers[1]
        self.assertEqual(group, -1)
        answer = AsyncMock()
        query = SimpleNamespace(
            data=markup.inline_keyboard[0][0].callback_data,
            message=SimpleNamespace(id=1),
            answer=answer,
        )
        with self.assertRaises(StopPropagation):
            await callback_handler.callback(client, query)

        result = await prompt_task
        self.assertEqual(result.text, "0")
        self.assertEqual(result.id, 1)
        answer.assert_awaited_once()
        self.assertEqual(client.deleted, [(12345, [1])])

    async def test_prompt_can_return_prompt_and_defer_callback_acknowledgement(self):
        client = FakeClient()
        prompt_task = asyncio.create_task(
            ask(
                client,
                12345,
                "Forwarding setup",
                callback_choices={
                    "🚀 Start (skip 0)": "0",
                    "⚙️ Settings": "__settings__",
                    "❌ Cancel": "__cancel__",
                },
                callback_choice_rows=[
                    ["🚀 Start (skip 0)", "⚙️ Settings"],
                    ["❌ Cancel"],
                ],
                return_prompt=True,
                defer_callback_answer=True,
                timeout=2,
            )
        )
        await client.message_sent.wait()
        buttons = client.sent[0]["reply_markup"].inline_keyboard
        self.assertEqual(len(buttons[0]), 2)
        self.assertIs(buttons[0][0].style, ButtonStyle.SUCCESS)
        self.assertIs(buttons[0][1].style, ButtonStyle.PRIMARY)
        self.assertIs(buttons[1][0].style, ButtonStyle.DANGER)
        prompt_message = SimpleNamespace(id=1)
        callback_handler, _ = client.handlers[1]
        answer = AsyncMock()
        query = SimpleNamespace(
            data=client.sent[0]["reply_markup"].inline_keyboard[0][0].callback_data,
            message=prompt_message,
            answer=answer,
        )
        with self.assertRaises(StopPropagation):
            await callback_handler.callback(client, query)

        choice, returned_prompt = await prompt_task
        self.assertEqual(choice.text, "0")
        self.assertIs(choice.callback_query, query)
        self.assertEqual(returned_prompt.id, 1)
        answer.assert_not_awaited()

    async def test_prompt_timeout_cleans_up_waiter(self):
        client = FakeClient()
        with self.assertRaises(TimeoutError):
            await ask(client, 67890, "Reply soon", timeout=0.01)

        # A new prompt in the same chat is allowed after the timeout.
        task = asyncio.create_task(ask(client, 67890, "Try again", timeout=1))
        await client.message_sent.wait()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    unittest.main()
