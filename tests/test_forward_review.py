import unittest
from unittest.mock import AsyncMock, patch

from config import temp
from forward_review import format_forwarding_settings
from plugins.forwarding import review_forwarding_task
from plugins.settings import main_buttons
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

    def test_task_dashboard_has_continue_and_cancel_actions(self):
        markup = main_buttons("123-456")
        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("continue_public_123-456", callback_data)
        self.assertIn("cancel_public_123-456", callback_data)


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

        with patch("plugins.forwarding.db.get_configs", new=AsyncMock(return_value={
            "filters": {"video": True, "text": False},
            "random_gap": {"min": 0, "max": 0},
        })):
            await review_forwarding_task(bot, query)

        message.edit_text.assert_awaited_once()
        edited_text = message.edit_text.await_args.args[0]
        self.assertIn("Selected forwarding settings", edited_text)
        markup = message.edit_text.await_args.kwargs["reply_markup"]
        callback_data = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("settings#filters", callback_data)
        self.assertIn(f"continue_public_{forward_id}", callback_data)
        self.assertIn(f"cancel_public_{forward_id}", callback_data)

        STS(forward_id).data.pop(forward_id, None)


if __name__ == "__main__":
    unittest.main()
