import unittest

from messages import Script


class MessageTemplateTests(unittest.TestCase):
    def test_positional_templates_accept_expected_values(self):
        self.assertIn("Ari", Script.START_TXT.format("Ari"))
        progress = Script.TEXT.format(
            1, 2, 3, 4, 5, 6, 7, 8, "Running", 50,
            "[██████████░░░░░░░░░░]", "2m", "Task"
        )
        self.assertIn("📥 <b>Fetched:</b>", progress)
        self.assertIn("📤 <b>Forwarded:</b>", progress)
        self.assertIn("📊 <b>Progress:</b>", progress)
        self.assertIn("⏳ <b>ETA:</b>", progress)
        self.assertIn("scanned", Script.DUPLICATE_TEXT.format(10, 2, "Done"))

    def test_public_copy_has_no_promotion_or_subscription_gate_links(self):
        public_copy = "\\n".join(
            [Script.START_TXT, Script.HELP_TXT, Script.HOW_USE_TXT]
        ).lower()
        for text in ("youtube.com", "t.me/", "subscribe", "join our channel"):
            self.assertNotIn(text, public_copy)

    def test_named_confirmation_template_accepts_expected_values(self):
        text = Script.DOUBLE_CHECK.format(
            botname="Forwarder",
            botuname="forwarder_bot",
            from_chat="Source",
            to_chat="Destination",
            skip=0,
        )
        self.assertIn("Source", text)
        self.assertIn("Destination", text)


if __name__ == "__main__":
    unittest.main()
