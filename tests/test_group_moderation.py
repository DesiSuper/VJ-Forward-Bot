import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram import StopPropagation

from plugins.group_moderation import (
    _delete_message_after,
    _extract_urls,
    enforce_global_blacklist,
    group_help,
    manage_global_blacklist,
    set_global_blacklist_delay,
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
    async def test_ghelp_lists_management_and_delay_commands_with_examples(self):
        message = SimpleNamespace(reply_text=AsyncMock())

        await group_help(object(), message)

        help_text = message.reply_text.await_args.args[0]
        self.assertIn("/blacklist url add instagram.com", help_text)
        self.assertIn("/blacklistdelay url instagram.com 2m", help_text)
        self.assertIn("does not expire the blacklist entry", help_text)
        self.assertIn("/blacklist list", help_text)

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

    async def test_only_bot_owner_can_manage_blacklist_from_private_chat(self):
        message = SimpleNamespace(
            text="/blacklist word add Bad Phrase",
            from_user=SimpleNamespace(id=123),
            chat=SimpleNamespace(id=123, type="private"),
            reply_text=AsyncMock(),
        )
        with (
            patch("plugins.group_moderation.Config.BOT_OWNER", 123),
            patch(
                "plugins.group_moderation.db.add_global_blacklist_entry",
                new=AsyncMock(),
            ) as add,
        ):
            await manage_global_blacklist(object(), message)

        add.assert_awaited_once_with("word", "bad phrase")
        self.assertIn("all groups", message.reply_text.await_args.args[0])

    async def test_bot_owner_cannot_manage_blacklist_from_a_group(self):
        message = SimpleNamespace(
            text="/blacklist word add badword",
            from_user=SimpleNamespace(id=123),
            chat=SimpleNamespace(id=-10099, type="supergroup"),
            reply_text=AsyncMock(),
        )
        with (
            patch("plugins.group_moderation.Config.BOT_OWNER", 123),
            patch(
                "plugins.group_moderation.db.add_global_blacklist_entry",
                new=AsyncMock(),
            ) as add,
        ):
            await manage_global_blacklist(object(), message)

        add.assert_not_awaited()
        self.assertIn("private chat with the bot", message.reply_text.await_args.args[0])

    async def test_dedicated_command_sets_delay_only_for_bot_owner_in_private(self):
        message = SimpleNamespace(
            text="/blacklistdelay word bad phrase 45s",
            from_user=SimpleNamespace(id=123),
            chat=SimpleNamespace(id=123, type="private"),
            reply_text=AsyncMock(),
        )
        with (
            patch("plugins.group_moderation.Config.BOT_OWNER", 123),
            patch(
                "plugins.group_moderation.db.set_global_blacklist_entry_delay",
                new=AsyncMock(return_value=True),
            ) as set_delay,
        ):
            await set_global_blacklist_delay(object(), message)

        set_delay.assert_awaited_once_with("word", "bad phrase", 45)
        self.assertIn("after 45s", message.reply_text.await_args.args[0])

    async def test_non_owner_cannot_change_global_blacklist_delay(self):
        message = SimpleNamespace(
            text="/blacklistdelay word bad phrase 1m",
            from_user=SimpleNamespace(id=456),
            chat=SimpleNamespace(id=456, type="private"),
            reply_text=AsyncMock(),
        )
        with (
            patch("plugins.group_moderation.Config.BOT_OWNER", 123),
            patch(
                "plugins.group_moderation.db.set_global_blacklist_entry_delay",
                new=AsyncMock(),
            ) as set_delay,
        ):
            await set_global_blacklist_delay(object(), message)

        set_delay.assert_not_awaited()
        self.assertIn("Only the bot owner", message.reply_text.await_args.args[0])

    async def test_non_owner_cannot_change_global_blacklist(self):
        message = SimpleNamespace(
            text="/blacklist word add badword",
            from_user=SimpleNamespace(id=456),
            chat=SimpleNamespace(id=456, type="private"),
            reply_text=AsyncMock(),
        )
        with (
            patch("plugins.group_moderation.Config.BOT_OWNER", 123),
            patch(
                "plugins.group_moderation.db.add_global_blacklist_entry",
                new=AsyncMock(),
            ) as add,
        ):
            await manage_global_blacklist(object(), message)

        add.assert_not_awaited()
        self.assertIn("Only the bot owner", message.reply_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
