import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from plugins.clients import update_configs
from plugins.public import begin_forward, source_manager_markup, source_picker_markup


class SourceChannelSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_forward_setup_prompts_from_saved_source_list(self):
        user_id = 78901
        destination = {"chat_id": -100111, "title": "Destination"}
        sources = [{"chat_id": -100222, "title": "Saved source"}]
        message = SimpleNamespace(
            chat=SimpleNamespace(id=user_id),
            reply_text=AsyncMock(),
        )
        bot = object()

        with (
            patch("plugins.public.db.get_bot", new=AsyncMock(return_value={"name": "Bot"})),
            patch("plugins.public.db.get_user_channels", new=AsyncMock(return_value=[destination])),
            patch("plugins.public.db.get_configs", new=AsyncMock(return_value={"sources": sources})),
            patch("plugins.public.prompt_for_input", new=AsyncMock()) as prompt,
        ):
            await begin_forward(bot, message, user_id=user_id)

        message.reply_text.assert_awaited_once()
        self.assertIn("Choose a source channel", message.reply_text.await_args.args[0])
        markup = message.reply_text.await_args.kwargs["reply_markup"]
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertIn("choose_source#-100111#-100222", callbacks)
        self.assertIn("add_source#-100111#save", callbacks)
        self.assertIn("add_source#-100111#once", callbacks)
        self.assertIn("manage_sources#-100111", callbacks)
        prompt.assert_not_awaited()

    def test_source_picker_and_manager_offer_keep_add_and_remove_actions(self):
        sources = [
            {"chat_id": -100222, "title": "First source"},
            {"chat_id": -100333, "title": "Second source"},
        ]
        picker = source_picker_markup(sources, -100111)
        manager = source_manager_markup(sources, -100111)
        picker_callbacks = [button.callback_data for row in picker.inline_keyboard for button in row]
        manager_callbacks = [button.callback_data for row in manager.inline_keyboard for button in row]

        self.assertIn("choose_source#-100111#-100222", picker_callbacks)
        self.assertIn("add_source#-100111#save", picker_callbacks)
        self.assertIn("add_source#-100111#once", picker_callbacks)
        self.assertIn("remove_source#-100111#-100222", manager_callbacks)
        self.assertIn("back_to_sources#-100111", manager_callbacks)

    async def test_source_list_is_saved_in_user_config(self):
        user_id = 78901
        saved_sources = [{"chat_id": -100222, "title": "Saved source"}]
        current = {"caption": None, "sources": []}
        with (
            patch("plugins.clients.db.get_configs", new=AsyncMock(return_value=current)),
            patch("plugins.clients.db.update_configs", new=AsyncMock()) as persist,
        ):
            await update_configs(user_id, "sources", saved_sources)

        persist.assert_awaited_once_with(user_id, {"caption": None, "sources": saved_sources})


if __name__ == "__main__":
    unittest.main()
