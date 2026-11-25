import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram.errors import SessionPasswordNeeded

from plugins.clients import CLIENT


class SensitivePromptCleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bot = SimpleNamespace(send_message=AsyncMock())
        self.message = SimpleNamespace(from_user=SimpleNamespace(id=77))

    async def test_botfather_token_message_is_deleted_after_capture(self):
        token_message = SimpleNamespace(
            text="not-a-forwarded-token",
            forward_origin=None,
            reply_text=AsyncMock(),
        )
        with patch("plugins.clients.prompt_for_input", new=AsyncMock(return_value=token_message)) as ask:
            await CLIENT().add_bot(self.bot, self.message)

        self.assertTrue(ask.await_args.kwargs["delete_prompt_and_reply"])
        token_message.reply_text.assert_not_awaited()
        self.assertNotIn("not-a-forwarded-token", str(self.bot.send_message.await_args))

    async def test_phone_and_otp_messages_are_deleted_after_capture(self):
        phone = SimpleNamespace(text="+15551234567")
        code = SimpleNamespace(text="1 2 3 4 5")
        prompts = AsyncMock(side_effect=[phone, code])
        login = SimpleNamespace(
            connect=AsyncMock(),
            send_code=AsyncMock(return_value=SimpleNamespace(phone_code_hash="hash")),
            sign_in=AsyncMock(),
            export_session_string=AsyncMock(return_value="serialized-session"),
            disconnect=AsyncMock(),
        )
        account = SimpleNamespace(id=5, first_name="User", username="user")
        validation = SimpleNamespace(
            start=AsyncMock(),
            get_me=AsyncMock(return_value=account),
            stop=AsyncMock(),
        )
        with (
            patch("plugins.clients.prompt_for_input", new=prompts),
            patch("plugins.clients.Client", side_effect=[login, validation]),
            patch("plugins.clients.db.add_userbot", new=AsyncMock()) as save,
        ):
            self.assertTrue(await CLIENT().add_session(self.bot, self.message))

        self.assertEqual(prompts.await_count, 2)
        self.assertTrue(all(call.kwargs["delete_prompt_and_reply"] for call in prompts.await_args_list))
        save.assert_awaited_once()
        self.assertNotIn("+15551234567", str(self.bot.send_message.await_args_list))
        self.assertNotIn("12345", str(self.bot.send_message.await_args_list))

    async def test_two_step_password_message_is_deleted_after_capture(self):
        phone = SimpleNamespace(text="+15551234567")
        code = SimpleNamespace(text="12345")
        password = SimpleNamespace(text="secret-password")
        prompts = AsyncMock(side_effect=[phone, code, password])
        login = SimpleNamespace(
            connect=AsyncMock(),
            send_code=AsyncMock(return_value=SimpleNamespace(phone_code_hash="hash")),
            sign_in=AsyncMock(side_effect=SessionPasswordNeeded()),
            check_password=AsyncMock(),
            export_session_string=AsyncMock(return_value="serialized-session"),
            disconnect=AsyncMock(),
        )
        account = SimpleNamespace(id=5, first_name="User", username="user")
        validation = SimpleNamespace(
            start=AsyncMock(),
            get_me=AsyncMock(return_value=account),
            stop=AsyncMock(),
        )
        with (
            patch("plugins.clients.prompt_for_input", new=prompts),
            patch("plugins.clients.Client", side_effect=[login, validation]),
            patch("plugins.clients.db.add_userbot", new=AsyncMock()),
        ):
            self.assertTrue(await CLIENT().add_session(self.bot, self.message))

        self.assertEqual(prompts.await_count, 3)
        self.assertTrue(all(call.kwargs["delete_prompt_and_reply"] for call in prompts.await_args_list))
        self.assertNotIn("secret-password", str(self.bot.send_message.await_args_list))


if __name__ == "__main__":
    unittest.main()
