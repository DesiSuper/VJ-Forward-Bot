import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram import enums

from plugins.settings import settings_query


class ChannelSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_channels_hub_shows_source_and_destination_counts_and_names(self):
        query = SimpleNamespace(
            data="settings#channels",
            from_user=SimpleNamespace(id=123),
            message=SimpleNamespace(edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        destinations = [{"chat_id": -10010, "title": "Destination A"}]
        sources = [{"chat_id": -10020, "title": "Source B"}]
        with (
            patch("plugins.settings.db.get_user_channels", new=AsyncMock(return_value=destinations)),
            patch("plugins.settings.get_configs", new=AsyncMock(return_value={"sources": sources})),
        ):
            await settings_query(object(), query)

        text = query.message.edit_text.await_args.args[0]
        markup = query.message.edit_text.await_args.kwargs["reply_markup"]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn("Destination A", text)
        self.assertIn("Source B", text)
        self.assertIn("settings#destinations", callbacks)
        self.assertIn("settings#sources", callbacks)

    async def test_source_list_renders_saved_names_and_ids(self):
        query = SimpleNamespace(
            data="settings#sources",
            from_user=SimpleNamespace(id=123),
            message=SimpleNamespace(edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        sources = [{"chat_id": -10020, "title": "Saved Source"}]
        with patch("plugins.settings.get_configs", new=AsyncMock(return_value={"sources": sources})):
            await settings_query(object(), query)

        text = query.message.edit_text.await_args.args[0]
        markup = query.message.edit_text.await_args.kwargs["reply_markup"]
        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn("Saved Source", text)
        self.assertIn("-10020", text)
        self.assertIn("settings#editsource_-10020", callbacks)
        self.assertIn("settings#addsource", callbacks)

    async def test_add_source_saves_forwarded_channel_to_user_config(self):
        user_id = 123
        query = SimpleNamespace(
            data="settings#addsource",
            from_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(delete=AsyncMock()),
            answer=AsyncMock(),
        )
        source_message = SimpleNamespace(
            text=None,
            forward_origin=SimpleNamespace(
                date=object(),
                chat=SimpleNamespace(
                    id=-100444,
                    title="New Source",
                    username="new_source",
                    type=enums.ChatType.CHANNEL,
                ),
            ),
        )
        source_message.reply_text = AsyncMock()
        bot = SimpleNamespace(send_message=AsyncMock())

        with (
            patch("plugins.settings.prompt_for_input", new=AsyncMock(return_value=source_message)),
            patch("plugins.settings.get_configs", new=AsyncMock(return_value={"sources": []})),
            patch("plugins.settings.update_configs", new=AsyncMock()) as save_source,
        ):
            await settings_query(bot, query)

        save_source.assert_awaited_once_with(
            user_id,
            "sources",
            [{"chat_id": -100444, "title": "New Source"}],
        )
        source_message.reply_text.assert_awaited_once()
        self.assertIn("Source channel saved", source_message.reply_text.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
