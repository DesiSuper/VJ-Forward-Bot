import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from config import temp
from forward_review import PENDING_REVIEW, format_forwarding_settings
from plugins.forwarding import return_to_task_review, review_forwarding_task
from plugins.settings import quick_settings_dashboard, size_filter_dashboard, time_gap_dashboard
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

    def test_quick_presets_are_grouped_in_their_own_menu(self):
        text, markup = quick_settings_dashboard(
            {
                "filters": {
                    "text": False,
                    "document": False,
                    "video": True,
                    "photo": True,
                    "audio": True,
                    "video_note": False,
                }
            },
            "321-654",
        )
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]

        self.assertIn("Quick settings", text)
        self.assertIn("Videos, Photos, Audio", text)
        self.assertIn("settings#filterpreset:all", callbacks)
        self.assertIn("settings#filterpreset:media", callbacks)
        self.assertIn("settings#filterpreset:video_photo_audio", callbacks)
        self.assertNotIn("continue_public_321-654", callbacks)
        self.assertNotIn("review_public_321-654", callbacks)

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
        self.assertNotIn("continue_public_321-654", size_callbacks)
        self.assertNotIn("review_public_321-654", size_callbacks)
        self.assertIn("Time gap", gap_text)
        self.assertIn("✅ ⏱️ 3–7 sec", gap_markup.inline_keyboard[1][0].text)
        self.assertIn("settings#gap:5:15", gap_callbacks)
        self.assertNotIn("continue_public_321-654", gap_callbacks)
        self.assertNotIn("review_public_321-654", gap_callbacks)


class ForwardReviewCallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_screen_omits_redundant_task_actions_but_keeps_review_navigation(self):
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
        self.assertIn("settings#quick_settings", callback_data)
        self.assertFalse(any(item.startswith("settings#filterpreset:") for item in callback_data))
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
        self.assertNotIn(f"continue_public_{forward_id}", callback_data)
        self.assertIn(f"review_public_{forward_id}", callback_data)
        self.assertNotIn(f"cancel_public_{forward_id}", callback_data)
        self.assertEqual(callback_data[-1], f"review_public_{forward_id}")

        STS(forward_id).data.pop(forward_id, None)

class ReturnToTaskReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_back_button_returns_to_review_with_current_settings(self):
        user_id = 731003
        forward_id = f"{user_id}-101"
        STS(forward_id).store(
            -100222,
            -100333,
            2,
            900,
            review={
                "botname": "Forward Bot",
                "botuname": "forward_bot",
                "from_chat": "Source",
                "to_chat": "Destination",
            },
        )
        PENDING_REVIEW[user_id] = forward_id
        temp.lock.pop(user_id, None)
        message = SimpleNamespace(
            chat=SimpleNamespace(id=user_id),
            edit_text=AsyncMock(),
        )
        query = SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            message=message,
            data=f"review_public_{forward_id}",
            answer=AsyncMock(),
        )
        config = {
            "filters": {
                "text": True,
                "document": False,
                "video": False,
                "photo": True,
                "audio": False,
                "video_note": False,
            },
            "random_gap": {"min": 0, "max": 0},
        }

        with patch("plugins.forwarding.db.get_configs", new=AsyncMock(return_value=config)):
            await return_to_task_review(None, query)

        query.answer.assert_awaited_once()
        self.assertNotIn(user_id, PENDING_REVIEW)
        text = message.edit_text.await_args.args[0]
        self.assertIn("Review forwarding task", text)
        self.assertNotIn("<b>Forwarding setup</b>", text)
        self.assertIn("Messages to skip:</b> <code>2</code>", text)
        self.assertIn("Message types:</b> Text, Photos", text)
        markup = message.edit_text.await_args.kwargs["reply_markup"]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        button_labels = {
            button.callback_data: button.text
            for row in markup.inline_keyboard
            for button in row
        }
        self.assertIn(f"continue_public_{forward_id}", callbacks)
        self.assertEqual(button_labels[f"continue_public_{forward_id}"], "🚀 Start (skip 2)")
        self.assertIn(f"start_public_{forward_id}", callbacks)
        self.assertIn(f"cancel_public_{forward_id}", callbacks)
        STS(forward_id).data.pop(forward_id, None)


if __name__ == "__main__":
    unittest.main()
