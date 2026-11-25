import asyncio
import unittest
from types import SimpleNamespace

from pyrogram import StopPropagation, filters

from plugins.prompts import ask


class FakeClient:
    def __init__(self):
        self.handlers = []
        self.sent = []
        self.message_sent = asyncio.Event()

    def add_handler(self, handler, group=0):
        self.handlers.append((handler, group))

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        self.message_sent.set()
        return SimpleNamespace(id=1)


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
