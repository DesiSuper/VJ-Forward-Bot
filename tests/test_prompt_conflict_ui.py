import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from plugins.prompts import InputPromptAlreadyActive
from plugins.settings import handle_active_prompt
from plugins.unequeify import handle_active_prompt as handle_cleanup_prompt


class PromptConflictUiTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_prompt_conflict_keeps_cleanup_flow_responsive(self):
        async def handler(client, message):
            raise InputPromptAlreadyActive("already active")

        message = SimpleNamespace(reply=AsyncMock())
        await handle_cleanup_prompt(handler)(object(), message)

        message.reply.assert_awaited_once()
        self.assertIn("input prompt is already active", message.reply.await_args.args[0])

    async def test_active_prompt_conflict_keeps_settings_flow_responsive(self):
        async def handler(bot, query):
            raise InputPromptAlreadyActive("already active")

        bot = SimpleNamespace(send_message=AsyncMock())
        query = SimpleNamespace(from_user=SimpleNamespace(id=43))

        await handle_active_prompt(handler)(bot, query)

        bot.send_message.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.args[0], 43)
        self.assertIn("input prompt is already active", bot.send_message.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
