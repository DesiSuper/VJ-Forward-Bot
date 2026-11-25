import unittest

from pyrogram import raw
from pyrogram.enums import ButtonStyle

from plugins.ui import InlineKeyboardButton


class KurigramButtonStyleTests(unittest.TestCase):
    def test_semantic_actions_receive_distinct_colors(self):
        start = InlineKeyboardButton("🚀 Start forwarding", callback_data="start_public_1")
        cancel = InlineKeyboardButton("❌ Cancel", callback_data="close_btn")
        back = InlineKeyboardButton("⬅️ Back", callback_data="settings#main")

        self.assertIs(start.style, ButtonStyle.SUCCESS)
        self.assertIs(cancel.style, ButtonStyle.DANGER)
        self.assertIs(back.style, ButtonStyle.PRIMARY)

    def test_old_positional_callback_argument_is_translated(self):
        button = InlineKeyboardButton("⬅️ Back", "settings#main")
        self.assertEqual(button.callback_data, "settings#main")
        self.assertIs(button.style, ButtonStyle.PRIMARY)

    def test_styles_are_serialized_into_kurigram_inline_buttons(self):
        button = InlineKeyboardButton("✅ Done", callback_data="done")
        wire_button = button.write(None)

        self.assertIsInstance(wire_button, raw.types.KeyboardInlineButton)
        self.assertTrue(wire_button.style.bg_success)
        self.assertFalse(wire_button.style.bg_danger)


if __name__ == "__main__":
    unittest.main()
