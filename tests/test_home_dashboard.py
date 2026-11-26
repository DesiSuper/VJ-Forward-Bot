import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from plugins.commands import (
    dashboard_text,
    group_moderation_help_page,
    help_page,
    home_keyboard,
    quick_forward,
)


class HomeDashboardTests(unittest.IsolatedAsyncioTestCase):
    def test_home_menu_hides_about_and_service_status(self):
        callbacks = [
            button.callback_data
            for row in home_keyboard().inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertNotIn("about", callbacks)
        self.assertNotIn("status", callbacks)
        self.assertIn("dashboard", callbacks)

    async def test_dashboard_shows_saved_bot_destinations_and_sources_without_secrets(
        self,
    ):
        with (
            patch(
                "plugins.commands.db.get_bot",
                new=AsyncMock(
                    return_value={
                        "name": "My Bot",
                        "username": "my_test_bot",
                        "id": 2468,
                        "token": "secret-token",
                    }
                ),
            ),
            patch("plugins.commands.db.get_userbot", new=AsyncMock(return_value=None)),
            patch(
                "plugins.commands.db.get_user_channels",
                new=AsyncMock(
                    return_value=[{"title": "Destination One", "chat_id": -100111}]
                ),
            ),
            patch(
                "plugins.commands.db.get_configs",
                new=AsyncMock(
                    return_value={
                        "sources": [{"title": "Saved Source", "chat_id": -100222}]
                    }
                ),
            ),
            patch(
                "plugins.commands.db.is_forwad_exit", new=AsyncMock(return_value=False)
            ),
        ):
            text = await dashboard_text(1234)

        self.assertIn("My Bot", text)
        self.assertIn("@my_test_bot", text)
        self.assertIn("ID <code>2468</code>", text)
        self.assertIn("Destination One", text)
        self.assertIn("Saved Source", text)
        self.assertNotIn("secret-token", text)

    async def test_start_forwarding_replaces_home_message_to_prevent_repeated_taps(
        self,
    ):
        user = SimpleNamespace(id=333, first_name="User")
        message = SimpleNamespace(
            chat=SimpleNamespace(id=333),
            edit_text=AsyncMock(),
            reply_text=AsyncMock(),
        )
        query = SimpleNamespace(
            from_user=user,
            message=message,
            answer=AsyncMock(),
        )
        begin_forward = AsyncMock()
        client = SimpleNamespace(send_message=AsyncMock())

        with patch("plugins.public.begin_forward", new=begin_forward):
            await quick_forward(client, query)

        message.edit_text.assert_awaited_once_with("<b>Preparing forwarding setup…</b>")
        begin_forward.assert_awaited_once()
        context = begin_forward.await_args.args[1]
        self.assertEqual(context.from_user, user)
        self.assertEqual(context.chat, message.chat)
        self.assertIs(context.reply_text, message.edit_text)
        self.assertIs(context.setup_message, message)
        self.assertIs(context.confirmation_reply.func, client.send_message)
        self.assertEqual(context.confirmation_reply.args, (message.chat.id,))

    async def test_help_page_only_shows_home_navigation(self):
        query = SimpleNamespace(
            answer=AsyncMock(),
            message=SimpleNamespace(edit_text=AsyncMock()),
        )
        await help_page(None, query)
        help_text = query.message.edit_text.await_args.args[0]
        self.assertNotIn("/dlink instagram.com/* 30s", help_text)
        markup = query.message.edit_text.await_args.kwargs["reply_markup"]
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertEqual(callbacks, ["group_moderation_help", "home"])

    async def test_group_moderation_help_button_shows_commands_and_navigation(self):
        query = SimpleNamespace(
            answer=AsyncMock(),
            message=SimpleNamespace(edit_text=AsyncMock()),
        )

        await group_moderation_help_page(None, query)

        help_text = query.message.edit_text.await_args.args[0]
        self.assertIn("/dlink instagram.com/* 30s", help_text)
        self.assertIn("/dlink list", help_text)
        self.assertIn("/blacklist list", help_text)
        markup = query.message.edit_text.await_args.kwargs["reply_markup"]
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertEqual(callbacks, ["help", "home"])


if __name__ == "__main__":
    unittest.main()
