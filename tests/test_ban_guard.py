import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram import StopPropagation

from plugins.ban_guard import block_banned_callbacks, block_banned_messages


class BanGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_ban_stops_private_message_handlers_and_escapes_reason(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=12),
            reply_text=AsyncMock(),
        )
        with patch(
            "plugins.ban_guard.db.get_ban_status",
            new=AsyncMock(return_value={"is_banned": True, "ban_reason": "<restricted>"}),
        ):
            with self.assertRaises(StopPropagation):
                await block_banned_messages(None, message)

        message.reply_text.assert_awaited_once_with(
            "<b>Access to this bot is restricted.</b>\n&lt;restricted&gt;"
        )

    async def test_unbanned_callback_is_not_intercepted(self):
        query = SimpleNamespace(from_user=SimpleNamespace(id=34))
        with patch(
            "plugins.ban_guard.db.get_ban_status",
            new=AsyncMock(return_value={"is_banned": False}),
        ):
            await block_banned_callbacks(None, query)


if __name__ == "__main__":
    unittest.main()
