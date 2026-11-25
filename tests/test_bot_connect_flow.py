import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from plugins import settings


class BotConnectFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_bot_callback_starts_prompt_without_deleting_accounts_screen(self):
        query = SimpleNamespace(
            data="settings#addbot",
            from_user=SimpleNamespace(id=12345),
            answer=AsyncMock(),
            message=SimpleNamespace(delete=AsyncMock()),
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        add_bot = AsyncMock(return_value=None)

        with patch.object(settings.CLIENT, "add_bot", add_bot):
            await settings.settings_query(bot, query)

        query.answer.assert_awaited_once()
        add_bot.assert_awaited_once_with(bot, query)
        query.message.delete.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    async def test_connect_bot_callback_reports_setup_failure(self):
        query = SimpleNamespace(
            data="settings#addbot",
            from_user=SimpleNamespace(id=12345),
            answer=AsyncMock(),
            message=SimpleNamespace(delete=AsyncMock()),
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        add_bot = AsyncMock(side_effect=RuntimeError("prompt failure"))

        with patch.object(settings.CLIENT, "add_bot", add_bot):
            await settings.settings_query(bot, query)

        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0], 12345)
        self.assertIn("Could not open bot setup", bot.send_message.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
