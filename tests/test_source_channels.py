import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from plugins.clients import update_configs
from plugins.public import begin_forward, source_manager_markup, source_picker_markup
from plugins.utils import STS


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

    async def test_saved_source_selection_uses_latest_message_then_asks_skip_count(self):
        user_id = 78902
        forward_id = f"{user_id}-555"
        message = SimpleNamespace(
            chat=SimpleNamespace(id=user_id),
            reply=AsyncMock(),
            reply_text=AsyncMock(),
        )
        source = {"chat_id": -100222, "title": "Saved source"}
        skip_reply = SimpleNamespace(text="0", id=555)
        skip_prompt = SimpleNamespace(id=54, edit_text=AsyncMock())
        bot = object()

        with (
            patch("plugins.public.db.get_bot", new=AsyncMock(return_value={"name": "My bot", "username": "my_bot"})),
            patch("plugins.public.db.get_user_channels", new=AsyncMock(return_value=[{"chat_id": -100111, "title": "Destination"}])),
            patch("plugins.public.db.get_configs", new=AsyncMock(return_value={"sources": [source]})),
            patch("plugins.public.latest_source_message_id", new=AsyncMock(return_value=987)) as latest_message,
            patch("plugins.public.update_configs", new=AsyncMock()) as save_checkpoint,
            patch("plugins.public.prompt_for_input", new=AsyncMock(return_value=(skip_reply, skip_prompt))) as prompt,
        ):
            await begin_forward(
                bot,
                message,
                user_id=user_id,
                selected_destination=(-100111, "Destination"),
                selected_source=source,
            )

        latest_message.assert_awaited_once_with(user_id, -100222)
        self.assertEqual(source["last_message_id"], 987)
        save_checkpoint.assert_awaited_once_with(user_id, "sources", [source])
        prompt.assert_awaited_once()
        self.assertIn("Messages to skip", prompt.await_args.args[2])
        self.assertIn("Saved source", prompt.await_args.args[2])
        self.assertEqual(prompt.await_args.kwargs["callback_choices"]["🚀 Start (skip 0)"], "0")
        task = STS(forward_id)
        self.assertTrue(task.verify())
        self.assertEqual(task.get("FROM"), -100222)
        self.assertEqual(task.get("limit"), 987)
        task.data.pop(forward_id, None)

    async def test_start_skip_zero_button_starts_without_a_review_step(self):
        user_id = 78905
        forward_id = f"{user_id}-801"
        source = {"chat_id": -100222, "title": "Saved source"}
        message = SimpleNamespace(chat=SimpleNamespace(id=user_id), reply_text=AsyncMock())
        prompt_message = SimpleNamespace(id=801)
        callback_query = SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            message=prompt_message,
            answer=AsyncMock(),
        )
        skip_choice = SimpleNamespace(
            text="0",
            id=801,
            from_callback=True,
            callback_query=callback_query,
        )
        bot = object()

        with (
            patch("plugins.public.db.get_bot", new=AsyncMock(return_value={"name": "My bot", "username": "my_bot"})),
            patch("plugins.public.db.get_user_channels", new=AsyncMock(return_value=[{"chat_id": -100111, "title": "Destination"}])),
            patch("plugins.public.db.get_configs", new=AsyncMock(return_value={"sources": [source]})),
            patch("plugins.public.latest_source_message_id", new=AsyncMock(return_value=987)),
            patch("plugins.public.update_configs", new=AsyncMock()),
            patch("plugins.public.prompt_for_input", new=AsyncMock(return_value=(skip_choice, prompt_message))) as prompt,
            patch("plugins.forwarding.pub_", new=AsyncMock()) as start_forwarding,
        ):
            await begin_forward(
                bot,
                message,
                user_id=user_id,
                selected_destination=(-100111, "Destination"),
                selected_source=source,
            )

        self.assertEqual(prompt.await_args.kwargs["callback_choices"], {
            "🚀 Start (skip 0)": "0",
            "⚙️ Settings": "__settings__",
        })
        start_forwarding.assert_awaited_once()
        routed_query = start_forwarding.await_args.args[1]
        self.assertEqual(routed_query.data, f"continue_public_{forward_id}")
        self.assertIs(routed_query.message, prompt_message)
        self.assertEqual(STS(forward_id).get("skip"), 0)
        STS(forward_id).data.pop(forward_id, None)

    async def test_settings_button_opens_task_settings_from_skip_prompt(self):
        user_id = 78906
        forward_id = f"{user_id}-802"
        source = {"chat_id": -100222, "title": "Saved source"}
        message = SimpleNamespace(chat=SimpleNamespace(id=user_id), reply_text=AsyncMock())
        prompt_message = SimpleNamespace(id=802)
        callback_query = SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            message=prompt_message,
            answer=AsyncMock(),
        )
        settings_choice = SimpleNamespace(
            text="__settings__",
            id=802,
            from_callback=True,
            callback_query=callback_query,
        )
        bot = object()

        with (
            patch("plugins.public.db.get_bot", new=AsyncMock(return_value={"name": "My bot", "username": "my_bot"})),
            patch("plugins.public.db.get_user_channels", new=AsyncMock(return_value=[{"chat_id": -100111, "title": "Destination"}])),
            patch("plugins.public.db.get_configs", new=AsyncMock(return_value={"sources": [source]})),
            patch("plugins.public.latest_source_message_id", new=AsyncMock(return_value=987)),
            patch("plugins.public.update_configs", new=AsyncMock()),
            patch("plugins.public.prompt_for_input", new=AsyncMock(return_value=(settings_choice, prompt_message))),
            patch("plugins.forwarding.review_forwarding_task", new=AsyncMock()) as open_settings,
        ):
            await begin_forward(
                bot,
                message,
                user_id=user_id,
                selected_destination=(-100111, "Destination"),
                selected_source=source,
            )

        open_settings.assert_awaited_once()
        routed_query = open_settings.await_args.args[1]
        self.assertEqual(routed_query.data, f"start_public_{forward_id}")
        self.assertIs(routed_query.message, prompt_message)
        self.assertEqual(STS(forward_id).get("skip"), 0)
        STS(forward_id).data.pop(forward_id, None)

    async def test_saved_source_uses_cached_message_id_when_history_read_fails(self):
        user_id = 78904
        forward_id = f"{user_id}-557"
        message = SimpleNamespace(
            chat=SimpleNamespace(id=user_id),
            reply=AsyncMock(),
            reply_text=AsyncMock(),
        )
        source = {"chat_id": -100222, "title": "Saved source", "last_message_id": 876}
        skip_reply = SimpleNamespace(text="0", id=557)
        skip_prompt = SimpleNamespace(id=57, edit_text=AsyncMock())
        bot = object()

        with (
            patch("plugins.public.db.get_bot", new=AsyncMock(return_value={"name": "My bot", "username": "my_bot"})),
            patch("plugins.public.db.get_user_channels", new=AsyncMock(return_value=[{"chat_id": -100111, "title": "Destination"}])),
            patch("plugins.public.db.get_configs", new=AsyncMock(return_value={"sources": [source]})),
            patch("plugins.public.latest_source_message_id", new=AsyncMock(side_effect=RuntimeError("history unavailable"))),
            patch("plugins.public.prompt_for_input", new=AsyncMock(return_value=(skip_reply, skip_prompt))) as prompt,
        ):
            await begin_forward(
                bot,
                message,
                user_id=user_id,
                selected_destination=(-100111, "Destination"),
                selected_source=source,
            )

        prompt.assert_awaited_once()
        self.assertIn("Messages to skip", prompt.await_args.args[2])
        self.assertTrue(STS(forward_id).verify())
        self.assertEqual(STS(forward_id).get("limit"), 876)
        STS(forward_id).data.pop(forward_id, None)

    async def test_saved_source_falls_back_to_forwarded_message_when_history_read_fails(self):
        user_id = 78903
        forward_id = f"{user_id}-556"
        setup_message = SimpleNamespace(delete=AsyncMock(), edit_text=AsyncMock())
        confirmation_reply = AsyncMock()
        message = SimpleNamespace(
            chat=SimpleNamespace(id=user_id),
            reply=AsyncMock(),
            reply_text=AsyncMock(),
            setup_message=setup_message,
            confirmation_reply=confirmation_reply,
        )
        source = {"chat_id": -100222, "title": "Saved source"}
        endpoint = SimpleNamespace(
            text=None,
            forward_origin=SimpleNamespace(
                date=object(),
                message_id=987,
                chat=SimpleNamespace(id=-100222),
            ),
        )
        skip_reply = SimpleNamespace(text="0", id=556)
        skip_prompt = SimpleNamespace(id=58, edit_text=AsyncMock())

        with (
            patch("plugins.public.db.get_bot", new=AsyncMock(return_value={"name": "My bot", "username": "my_bot"})),
            patch("plugins.public.db.get_user_channels", new=AsyncMock(return_value=[{"chat_id": -100111, "title": "Destination"}])),
            patch("plugins.public.db.get_configs", new=AsyncMock(return_value={"sources": [source]})),
            patch("plugins.public.latest_source_message_id", new=AsyncMock(side_effect=RuntimeError("history unavailable"))),
            patch("plugins.public.update_configs", new=AsyncMock()) as save_checkpoint,
            patch("plugins.public.prompt_for_input", new=AsyncMock(side_effect=[endpoint, (skip_reply, skip_prompt)])) as prompt,
        ):
            await begin_forward(
                object(),
                message,
                user_id=user_id,
                selected_destination=(-100111, "Destination"),
                selected_source=source,
            )

        self.assertEqual(prompt.await_count, 2)
        self.assertIn("could not fetch", prompt.await_args_list[0].args[2].lower())
        self.assertEqual(source["last_message_id"], 987)
        save_checkpoint.assert_awaited_once_with(user_id, "sources", [source])
        self.assertTrue(STS(forward_id).verify())
        self.assertEqual(STS(forward_id).get("limit"), 987)
        setup_message.delete.assert_awaited_once()
        confirmation_reply.assert_not_awaited()
        self.assertIn("Review forwarding task", skip_prompt.edit_text.await_args.args[0])
        callbacks = [
            button.callback_data
            for row in skip_prompt.edit_text.await_args.kwargs["reply_markup"].inline_keyboard
            for button in row
        ]
        self.assertIn(f"continue_public_{forward_id}", callbacks)
        self.assertIn(f"start_public_{forward_id}", callbacks)
        self.assertIn(f"cancel_public_{forward_id}", callbacks)
        self.assertEqual(STS(forward_id).get("review")["from_chat"], "Saved source")
        message.reply_text.assert_not_awaited()
        STS(forward_id).data.pop(forward_id, None)

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
