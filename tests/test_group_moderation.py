import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram import StopPropagation

from plugins.group_moderation import (
    _extract_urls,
    enforce_global_blacklist,
    manage_global_blacklist,
    normalize_blacklisted_url,
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

        add.assert_awaited_once_with("word", "bad phrase")
        self.assertIn("all groups", message.reply_text.await_args.args[0])

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
