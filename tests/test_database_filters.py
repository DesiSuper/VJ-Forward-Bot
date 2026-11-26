import unittest
from unittest.mock import AsyncMock

from database import Db


class DatabaseFilterEnforcementTests(unittest.IsolatedAsyncioTestCase):
    async def test_instagram_preference_defaults_on_and_persists_per_user(self):
        database = Db("", "")
        database._require_database = lambda: None
        database.preferences = type("Collection", (), {})()
        database.preferences.find_one = AsyncMock(
            side_effect=[None, {"enabled": False}]
        )
        database.preferences.update_one = AsyncMock()

        self.assertTrue(await database.get_instagram_enabled(77))
        await database.set_instagram_enabled(77, False)
        self.assertFalse(await database.get_instagram_enabled(77))

        database.preferences.find_one.assert_any_await(
            {"_id": "instagram:77"}, {"enabled": 1}
        )
        database.preferences.update_one.assert_awaited_once_with(
            {"_id": "instagram:77"}, {"$set": {"enabled": False}}, upsert=True
        )

    async def test_global_blacklist_uses_shared_moderation_document(self):
        database = Db("", "")
        database._require_database = lambda: None
        database.moderation = type("Collection", (), {})()
        database.moderation.find_one = AsyncMock(
            return_value={"words": ["spam phrase"], "urls": ["spam.example"]}
        )
        database.moderation.update_one = AsyncMock()

        blacklist = await database.get_global_blacklist()
        await database.add_global_blacklist_entry("word", "spam phrase", 30)
        await database.remove_global_blacklist_entry("url", "spam.example")

        self.assertEqual(
            blacklist,
            {
                "words": [{"value": "spam phrase", "delay_seconds": 0}],
                "urls": [{"value": "spam.example", "delay_seconds": 0}],
            },
        )
        database.moderation.find_one.assert_awaited_once_with(
            {"_id": "global_blacklist"}, {"words": 1, "urls": 1}
        )
        updates = database.moderation.update_one.await_args_list
        self.assertEqual(
            updates[0].args,
            ({"_id": "global_blacklist"}, {"$pull": {"words": "spam phrase"}}),
        )
        self.assertEqual(
            updates[2].args,
            (
                {"_id": "global_blacklist"},
                {"$addToSet": {"words": {"value": "spam phrase", "delay_seconds": 30}}},
            ),
        )
        self.assertEqual(updates[2].kwargs, {"upsert": True})
        self.assertEqual(
            updates[3].args,
            ({"_id": "global_blacklist"}, {"$pull": {"urls": "spam.example"}}),
        )
        self.assertEqual(
            updates[4].args,
            (
                {"_id": "global_blacklist"},
                {"$pull": {"urls": {"value": "spam.example"}}},
            ),
        )

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
            {
                key: config["filters"][key]
                for key in ("voice", "animation", "sticker", "poll")
            },
            {"voice": False, "animation": False, "sticker": False, "poll": False},
        )
        self.assertFalse(config["filters"]["video"])
        self.assertNotIn("button", config)


if __name__ == "__main__":
    unittest.main()
