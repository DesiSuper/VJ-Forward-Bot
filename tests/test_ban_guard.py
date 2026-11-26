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

    async def test_bot_admin_instagram_link_passes_through_to_downloader(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=12),
            text="https://www.instagram.com/reel/example",
            reply_text=AsyncMock(),
        )
        with (
            patch("plugins.ban_guard.Config.BOT_OWNER", 12),
            patch(
                "plugins.ban_guard.db.get_ban_status",
                new=AsyncMock(return_value={"is_banned": False}),
            ),
        ):
            await block_banned_messages(None, message)

        message.reply_text.assert_not_awaited()

    async def test_non_admin_instagram_link_is_stopped_without_reply(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(id=12),
            text="https://www.instagram.com/reel/example",
            reply_text=AsyncMock(),
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

        message.reply_text.assert_not_awaited()

    async def test_non_admin_callback_is_stopped_without_alert(self):
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

        query.answer.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
