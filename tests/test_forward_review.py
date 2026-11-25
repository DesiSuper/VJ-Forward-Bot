import unittest
from unittest.mock import AsyncMock, patch

from config import temp
from forward_review import format_forwarding_settings
from plugins.forwarding import review_forwarding_task
from plugins.settings import size_filter_dashboard, time_gap_dashboard
from plugins.utils import STS


class ForwardReviewTests(unittest.TestCase):
    def test_summary_shows_selected_options(self):
        text = format_forwarding_settings(
            {
                "filters": {"video": True, "photo": True, "text": False},
                "random_gap": {"min": 4, "max": 9},
                "keywords": ["spoiler"],
                "extension": ["zip"],
                "duplicate": True,
                "protect": True,
                "forward_tag": False,
                "caption": "{filename}",
                "button": "[Watch][buttonurl:https://example.com]",
            }
        )
        self.assertIn("Videos, Photos", text)
        self.assertIn("4–9 sec random", text)
        self.assertIn("spoiler", text)
        self.assertIn("zip", text)
        self.assertIn("Skip duplicates:</b> On", text)
        self.assertIn("Protect content:</b> On", text)
        self.assertIn("Custom caption", text)

    def test_summary_escapes_user_configured_values(self):
        text = format_forwarding_settings(
            {"keywords": ["<b>unsafe</b>"], "random_gap": {"min": 0, "max": 0}}
        )
        self.assertIn("&lt;b&gt;unsafe&lt;/b&gt;", text)
        self.assertNotIn("<b>unsafe</b>", text)

    def test_size_and_time_gap_settings_are_grouped_in_submenus(self):
        size_text, size_markup = size_filter_dashboard(
            {"min_size": 10, "max_size": 50}, "321-654"
        )
        gap_text, gap_markup = time_gap_dashboard(
            {"random_gap": {"min": 3, "max": 7}}, "321-654"
        )
        size_callbacks = [
            button.callback_data
            for row in size_markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        gap_callbacks = [
            button.callback_data
            for row in gap_markup.inline_keyboard
            for button in row
            if button.callback_data
        ]

        self.assertIn("Size filter", size_text)
        self.assertIn("Minimum:</b> 10 MB", size_text)
        self.assertIn("settings#update_size:15", size_callbacks)
        self.assertIn("settings#maxupdate_size:55", size_callbacks)
        self.assertIn("continue_public_321-654", size_callbacks)
        self.assertIn("Time gap", gap_text)
        self.assertIn("✅ ⏱️ 3–7 sec", gap_markup.inline_keyboard[1][0].text)
        self.assertIn("settings#gap:5:15", gap_callbacks)
        self.assertIn("continue_public_321-654", gap_callbacks)


class ForwardReviewCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_button_shows_settings_and_continue_action(self):
        user_id = 731002
        forward_id = f"{user_id}-99"
        STS(forward_id).store("source", -100123, 0, 100)
        temp.lock.pop(user_id, None)
        while -100123 in temp.IS_FRWD_CHAT:
            temp.IS_FRWD_CHAT.remove(-100123)

        message = type("FakeMessage", (), {})()
        message.chat = type("FakeChat", (), {"id": user_id})()
        message.text = "<b>Review forwarding task</b>"
        message.edit_text = AsyncMock()
        query = type("FakeQuery", (), {})()
        query.from_user = type("FakeUser", (), {"id": user_id})()
        query.data = f"start_public_{forward_id}"
        query.message = message
        query.answer = AsyncMock()
        bot = object()

        mock_config = {
            "filters": {"video": True, "text": False},
            "random_gap": {"min": 0, "max": 0},
        }
        with (
            patch("plugins.settings.get_configs", new=AsyncMock(return_value=mock_config)),
            patch("plugins.settings.db.get_bot", new=AsyncMock(return_value=None)),
            patch("plugins.settings.db.get_userbot", new=AsyncMock(return_value=None)),
            patch("plugins.settings.db.get_user_channels", new=AsyncMock(return_value=[])),
        ):
            await review_forwarding_task(bot, query)

        message.edit_text.assert_awaited_once()
        edited_text = message.edit_text.await_args.args[0]
        self.assertIn("All forwarding settings", edited_text)
        markup = message.edit_text.await_args.kwargs["reply_markup"]
        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("settings#updatefilter-text-False", callback_data)
        self.assertIn("settings#size_filter", callback_data)
        self.assertIn("settings#time_gap", callback_data)
        self.assertFalse(any(
            item.startswith("settings#update_size:")
            or item.startswith("settings#maxupdate_size:")
            or item.startswith("settings#gap:")
            for item in callback_data
        ))
        self.assertFalse(any(
            "voice" in item or "animation" in item or "sticker" in item or "poll" in item
            for item in callback_data
        ))
        self.assertIn(f"continue_public_{forward_id}", callback_data)
        self.assertIn(f"cancel_public_{forward_id}", callback_data)

        STS(forward_id).data.pop(forward_id, None)


if __name__ == "__main__":
    unittest.main()
