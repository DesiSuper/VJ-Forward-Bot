import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram import StopPropagation

from plugins.group_moderation import (
    _delete_message_after,
    _extract_urls,
    enforce_global_blacklist,
    manage_global_blacklist,
    matching_entry_delays,
    normalize_blacklisted_url,
    parse_delay,
    url_is_blacklisted,
    word_is_blacklisted,
)


class GroupBlacklistMatchingTests(unittest.TestCase):
    def test_words_match_case_insensitively_without_matching_inside_larger_words(self):
        self.assertTrue(word_is_blacklisted("Please STOP THIS now", ["stop this"]))
        self.assertFalse(word_is_blacklisted("This is a classic", ["ass"]))
        self.assertFalse(word_is_blacklisted("nothing to see", ["blocked phrase"]))

    def test_url_entries_normalize_domains_and_url_paths(self):
        self.assertEqual(normalize_blacklisted_url("WWW.Spam.Example/"), "spam.example")
        self.assertEqual(
            normalize_blacklisted_url("https://spam.example/path/?utm=x"),
            "spam.example/path",
        )
        with self.assertRaises(ValueError):
            normalize_blacklisted_url("https://user:pass@spam.example/path")

    def test_delay_parser_accepts_seconds_and_minutes_with_a_safe_maximum(self):
        self.assertEqual(parse_delay("30s"), 30)
        self.assertEqual(parse_delay("2 minutes"), 120)
        self.assertEqual(parse_delay("0s"), 0)
        with self.assertRaises(ValueError):
            parse_delay("5h")
        with self.assertRaises(ValueError):
            parse_delay("1441m")

    def test_matching_rules_retain_their_individual_delays(self):
        blacklist = {
            "words": [
                {"value": "bad phrase", "delay_seconds": 75},
                {"value": "other", "delay_seconds": 10},
            ],
            "urls": [{"value": "spam.example", "delay_seconds": 30}],
        }
        self.assertEqual(
            matching_entry_delays("bad phrase at spam.example", blacklist), [75, 30]
        )

    def test_urls_match_domains_subdomains_and_path_prefixes(self):
        self.assertTrue(
            url_is_blacklisted("Visit https://news.spam.example/deal", ["spam.example"])
        )
        self.assertTrue(
            url_is_blacklisted("www.spam.example/path/page", ["spam.example/path"])
        )
        self.assertFalse(
            url_is_blacklisted("https://spam.example.evil.test/path", ["spam.example"])
        )
        self.assertFalse(
            url_is_blacklisted("https://spam.example/other", ["spam.example/path"])
        )
        self.assertEqual(_extract_urls("mail me at user@example.com"), [])


class GroupBlacklistHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_blacklisted_group_message_is_deleted_silently(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(is_bot=False),
            text="This has a blocked phrase in it",
            caption=None,
            chat=SimpleNamespace(id=-10099),
            delete=AsyncMock(),
        )
        with patch(
            "plugins.group_moderation._get_global_blacklist",
            new=AsyncMock(return_value={"words": ["blocked phrase"], "urls": []}),
        ):
            with self.assertRaises(StopPropagation):
                await enforce_global_blacklist(object(), message)

        message.delete.assert_awaited_once()

    async def test_delayed_delete_waits_for_its_configured_seconds(self):
        message = SimpleNamespace(chat=SimpleNamespace(id=-10099), delete=AsyncMock())
        with patch("plugins.group_moderation.asyncio.sleep", new=AsyncMock()) as sleep:
            await _delete_message_after(message, 25)

        sleep.assert_awaited_once_with(25)
        message.delete.assert_awaited_once()

    async def test_delayed_rule_schedules_delete_without_blocking_handler(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(is_bot=False),
            text="This has a blocked phrase in it",
            caption=None,
            chat=SimpleNamespace(id=-10099),
            delete=AsyncMock(),
        )
        delayed_delete = AsyncMock()
        with (
            patch(
                "plugins.group_moderation._get_global_blacklist",
                new=AsyncMock(
                    return_value={
                        "words": [{"value": "blocked phrase", "delay_seconds": 30}],
                        "urls": [],
                    }
                ),
            ),
            patch("plugins.group_moderation._delete_message_after", new=delayed_delete),
        ):
            await enforce_global_blacklist(object(), message)
            await asyncio.sleep(0)

        delayed_delete.assert_awaited_once_with(message, 30)
        message.delete.assert_not_awaited()

    async def test_message_with_blacklisted_url_is_deleted(self):
        message = SimpleNamespace(
            from_user=SimpleNamespace(is_bot=False),
            text="Check spam.example/path",
            caption=None,
            chat=SimpleNamespace(id=-10099),
            delete=AsyncMock(),
        )
        with patch(
            "plugins.group_moderation._get_global_blacklist",
            new=AsyncMock(return_value={"words": [], "urls": ["spam.example"]}),
        ):
            with self.assertRaises(StopPropagation):
                await enforce_global_blacklist(object(), message)

        message.delete.assert_awaited_once()

    async def test_blacklist_admin_command_adds_normalized_global_word(self):
        message = SimpleNamespace(
            text="/blacklist word add Bad Phrase",
            from_user=SimpleNamespace(id=123),
            chat=SimpleNamespace(id=-10099),
            reply_text=AsyncMock(),
        )
        with (
            patch(
                "plugins.group_moderation._is_group_admin",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "plugins.group_moderation.db.add_global_blacklist_entry",
                new=AsyncMock(),
            ) as add,
        ):
            await manage_global_blacklist(object(), message)

        add.assert_awaited_once_with("word", "bad phrase", 0)
        self.assertIn("all groups", message.reply_text.await_args.args[0])

    async def test_admin_can_add_entry_with_per_entry_delay(self):
        message = SimpleNamespace(
            text="/blacklist url add spam.example --delay 2m",
            from_user=SimpleNamespace(id=123),
            chat=SimpleNamespace(id=-10099),
            reply_text=AsyncMock(),
        )
        with (
            patch(
                "plugins.group_moderation._is_group_admin",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "plugins.group_moderation.db.add_global_blacklist_entry",
                new=AsyncMock(),
            ) as add,
        ):
            await manage_global_blacklist(object(), message)

        add.assert_awaited_once_with("url", "spam.example", 120)
        self.assertIn("after 2m", message.reply_text.await_args.args[0])

    async def test_admin_can_change_an_existing_entry_delay(self):
        message = SimpleNamespace(
            text="/blacklist word delay bad phrase 45s",
            from_user=SimpleNamespace(id=123),
            chat=SimpleNamespace(id=-10099),
            reply_text=AsyncMock(),
        )
        with (
            patch(
                "plugins.group_moderation._is_group_admin",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "plugins.group_moderation.db.set_global_blacklist_entry_delay",
                new=AsyncMock(return_value=True),
            ) as set_delay,
        ):
            await manage_global_blacklist(object(), message)

        set_delay.assert_awaited_once_with("word", "bad phrase", 45)
        self.assertIn("after 45s", message.reply_text.await_args.args[0])

    async def test_non_admin_cannot_change_global_blacklist(self):
        message = SimpleNamespace(
            text="/blacklist word add badword",
            from_user=SimpleNamespace(id=456),
            chat=SimpleNamespace(id=-10099),
            reply_text=AsyncMock(),
        )
        with (
            patch(
                "plugins.group_moderation._is_group_admin",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "plugins.group_moderation.db.add_global_blacklist_entry",
                new=AsyncMock(),
            ) as add,
        ):
            await manage_global_blacklist(object(), message)

        add.assert_not_awaited()
        self.assertIn(
            "Only this group's administrators", message.reply_text.await_args.args[0]
        )


if __name__ == "__main__":
    unittest.main()
