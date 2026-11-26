import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram import StopPropagation

from plugins.ban_guard import block_banned_callbacks, block_banned_messages


class BanGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_ban_stops_private_message_handlers_and_escapes_reason(
        self,
    ):
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=12),
            reply_text=AsyncMock(),
        )
        with patch(
            "plugins.ban_guard.db.get_ban_status",
            new=AsyncMock(
                return_value={"is_banned": True, "ban_reason": "<restricted>"}
            ),
        ):
            with self.assertRaises(StopPropagation):
                await block_banned_messages(None, message)

        message.reply_text.assert_awaited_once_with(
            "<b>Access to this bot is restricted.</b>\n&lt;restricted&gt;"
        )

    async def test_unbanned_bot_owner_callback_is_not_intercepted(self):
        query = SimpleNamespace(from_user=SimpleNamespace(id=34))
        with (
            patch("plugins.ban_guard.Config.BOT_OWNER", 34),
            patch(
                "plugins.ban_guard.db.get_ban_status",
                new=AsyncMock(return_value={"is_banned": False}),
            ),
        ):
            await block_banned_callbacks(None, query)

    async def test_non_admin_private_message_is_stopped_with_admin_only_notice(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=12), reply_text=AsyncMock()
        )
        with (
            patch("plugins.ban_guard.Config.BOT_OWNER", 99),
            patch(
                "plugins.ban_guard.db.get_ban_status",
                new=AsyncMock(return_value={"is_banned": False}),
            ),
        ):
            with self.assertRaises(StopPropagation):
                await block_banned_messages(None, message)

        message.reply_text.assert_awaited_once_with(
            "<b>This forwarding bot is for the configured bot admin only.</b>"
        )

    async def test_non_admin_callback_is_stopped_with_admin_only_alert(self):
        query = SimpleNamespace(from_user=SimpleNamespace(id=34), answer=AsyncMock())
        with (
            patch("plugins.ban_guard.Config.BOT_OWNER", 99),
            patch(
                "plugins.ban_guard.db.get_ban_status",
                new=AsyncMock(return_value={"is_banned": False}),
            ),
        ):
            with self.assertRaises(StopPropagation):
                await block_banned_callbacks(None, query)

        query.answer.assert_awaited_once_with(
            "This forwarding bot is for the configured bot admin only.",
            show_alert=True,
        )


if __name__ == "__main__":
    unittest.main()
