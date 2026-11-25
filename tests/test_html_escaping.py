import unittest
from unittest.mock import AsyncMock, patch

from plugins.settings import settings_dashboard


class HtmlEscapingTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_dashboard_escapes_saved_user_controlled_values(self):
        config = {
            "caption": None,
            "duplicate": True,
            "forward_tag": False,
            "protect": None,
            "min_size": 0,
            "max_size": 0,
            "extension": ["<b>spoof</b>"],
            "keywords": ["<i>spoof</i>"],
            "sources": [{"chat_id": -1001, "title": "<u>source</u>"}],
            "random_gap": {"min": 0, "max": 0},
            "filters": {"text": True, "document": True, "video": True, "photo": True, "audio": True, "video_note": True},
        }
        with (
            patch("plugins.settings.get_configs", new=AsyncMock(return_value=config)),
            patch("plugins.settings.db.get_bot", new=AsyncMock(return_value={"name": "<b>account</b>"})),
            patch("plugins.settings.db.get_userbot", new=AsyncMock(return_value=None)),
            patch("plugins.settings.db.get_user_channels", new=AsyncMock(return_value=[{"chat_id": -1002, "title": "<i>destination</i>"}])),
        ):
            text, _ = await settings_dashboard(12)

        for raw in ("<b>account</b>", "<i>destination</i>", "<u>source</u>", "<b>spoof</b>", "<i>spoof</i>"):
            self.assertNotIn(raw, text)
        self.assertIn("&lt;b&gt;account&lt;/b&gt;", text)
        self.assertIn("&lt;i&gt;destination&lt;/i&gt;", text)
        self.assertIn("&lt;u&gt;source&lt;/u&gt;", text)
        self.assertIn("&lt;b&gt;spoof&lt;/b&gt;", text)
        self.assertIn("&lt;i&gt;spoof&lt;/i&gt;", text)


if __name__ == "__main__":
    unittest.main()
