import unittest
from unittest.mock import AsyncMock

from database import Db


class DatabaseFilterEnforcementTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_blacklist_uses_shared_moderation_document(self):
        database = Db("", "")
        database._require_database = lambda: None
        database.moderation = type("Collection", (), {})()
        database.moderation.find_one = AsyncMock(
            return_value={"words": ["spam phrase"], "urls": ["spam.example"]}
        )
        database.moderation.update_one = AsyncMock()

        blacklist = await database.get_global_blacklist()
        await database.add_global_blacklist_entry("word", "spam phrase")
        await database.remove_global_blacklist_entry("url", "spam.example")

        self.assertEqual(blacklist, {"words": ["spam phrase"], "urls": ["spam.example"]})
        database.moderation.find_one.assert_awaited_once_with(
            {"_id": "global_blacklist"}, {"words": 1, "urls": 1}
        )
        self.assertEqual(database.moderation.update_one.await_args_list[0].args,
                         ({"_id": "global_blacklist"}, {"$addToSet": {"words": "spam phrase"}}))
        self.assertEqual(database.moderation.update_one.await_args_list[0].kwargs, {"upsert": True})
        self.assertEqual(database.moderation.update_one.await_args_list[1].args,
                         ({"_id": "global_blacklist"}, {"$pull": {"urls": "spam.example"}}))

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
