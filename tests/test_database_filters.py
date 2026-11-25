import unittest
from unittest.mock import AsyncMock

from database import Db


class DatabaseFilterEnforcementTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_configs_cannot_enable_removed_message_types_or_buttons(self):
        database = Db("", "")
        database._require_database = lambda: None
        database.col = type("Collection", (), {})()
        database.col.find_one = AsyncMock(
            return_value={
                "configs": {
                    "button": "[Open][buttonurl:https://example.com]",
                    "filters": {
                        "voice": True,
                        "animation": True,
                        "sticker": True,
                        "poll": True,
                        "video": False,
                    },
                }
            }
        )

        config = await database.get_configs(42)

        self.assertEqual(
            {key: config["filters"][key] for key in ("voice", "animation", "sticker", "poll")},
            {"voice": False, "animation": False, "sticker": False, "poll": False},
        )
        self.assertFalse(config["filters"]["video"])
        self.assertNotIn("button", config)


if __name__ == "__main__":
    unittest.main()
