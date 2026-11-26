import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from main import notify_bot_owner_started, startup_notification_text


class StartupNotificationTests(unittest.IsolatedAsyncioTestCase):
    def test_startup_card_includes_bot_identity_status_and_date_time(self):
        text = startup_notification_text(
            SimpleNamespace(first_name="Forward Bot", username="forward_test_bot"),
            datetime(2026, 11, 26, 10, 9, 5, tzinfo=timezone.utc),
        )

        self.assertIn("🚀 <b>Forward Bot Started</b>", text)
        self.assertIn("<code>Online</code>", text)
        self.assertIn("@forward_test_bot", text)
        self.assertIn("26 Nov 2026", text)
        self.assertIn("10:09:05 AM", text)
        self.assertIn("UTC", text)

    async def test_startup_notification_goes_to_bot_owner_with_dashboard_buttons(self):
        client = SimpleNamespace(send_message=AsyncMock())
        with (
            patch("main.Config.BOT_OWNER", 123),
            patch("main.Config.BOT_OWNERS", ()),
        ):
            await notify_bot_owner_started(
                client,
                SimpleNamespace(first_name="Forward Bot", username="forward_test_bot"),
            )

        client.send_message.assert_awaited_once()
        args = client.send_message.await_args
        self.assertEqual(args.args[0], 123)
        self.assertIn("Forward Bot Started", args.args[1])
        buttons = args.kwargs["reply_markup"].inline_keyboard[0]
        self.assertEqual(
            [button.callback_data for button in buttons], ["dashboard", "help"]
        )

    async def test_startup_notification_is_sent_to_every_configured_admin(self):
        client = SimpleNamespace(send_message=AsyncMock())
        with (
            patch("main.Config.BOT_OWNER", 123),
            patch("main.Config.BOT_OWNERS", (123, 456)),
        ):
            await notify_bot_owner_started(
                client, SimpleNamespace(first_name="Forward Bot", username="forward_test_bot")
            )

        self.assertEqual(
            [call.args[0] for call in client.send_message.await_args_list], [123, 456]
        )

    async def test_notification_delivery_failure_does_not_abort_startup(self):
        client = SimpleNamespace(
            send_message=AsyncMock(side_effect=RuntimeError("owner has not opened bot"))
        )

        with (
            patch("main.Config.BOT_OWNER", 123),
            patch("main.Config.BOT_OWNERS", ()),
        ):
            await notify_bot_owner_started(
                client, SimpleNamespace(first_name="Forward Bot", username=None)
            )

        client.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
