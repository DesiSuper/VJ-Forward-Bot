import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram import enums

from plugins.unequeify import unequify


class UnequifyPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwarded_target_without_text_is_detected_and_cancelled_cleanly(self):
        target = SimpleNamespace(
            forward_origin=SimpleNamespace(
                chat=SimpleNamespace(type=enums.ChatType.CHANNEL, username="docs", id=-1005)
            )
        )
        confirm = SimpleNamespace(text="/cancel", reply=AsyncMock())
        prompt = AsyncMock(side_effect=[target, confirm])
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=99),
            reply=AsyncMock(),
            reply_text=AsyncMock(),
        )
        with (
            patch("plugins.unequeify.db.get_userbot", new=AsyncMock(return_value={"session": "s"})),
            patch("plugins.unequeify.prompt_for_input", new=prompt),
            patch("plugins.unequeify.get_client", new=AsyncMock()) as get_client,
        ):
            await unequify(None, message)

        self.assertEqual(prompt.await_args_list[0].args[1], 99)
        confirm.reply.assert_awaited_once_with("<b>Cleanup cancelled.</b>")
        get_client.assert_not_awaited()

    async def test_unforwarded_target_without_text_is_handled_without_attribute_error(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=100),
            reply=AsyncMock(),
            reply_text=AsyncMock(),
        )
        with (
            patch("plugins.unequeify.db.get_userbot", new=AsyncMock(return_value={"session": "s"})),
            patch("plugins.unequeify.prompt_for_input", new=AsyncMock(return_value=SimpleNamespace())),
        ):
            await unequify(None, message)

        message.reply_text.assert_awaited_once()
        self.assertIn("Could not identify the chat", message.reply_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
