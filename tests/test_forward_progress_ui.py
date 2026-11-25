import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from plugins.forwarding import edit, render_progress_bar
from plugins.utils import STS


class ForwardProgressUiTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_bar_is_rendered_in_message_text_not_as_a_button(self):
        user_id = 9081
        task_id = f"progress-ui-{user_id}"
        task = STS(task_id).store(-100111, -100222, 0, 100)
        task.data[task_id].update(
            {
                "fetched": 50,
                "total": 100,
                "total_files": 2,
                "videos": 1,
                "photos": 1,
                "start": time.time() - 10,
            }
        )
        message = SimpleNamespace(id=88123, edit=AsyncMock())

        try:
            with patch("plugins.forwarding.update_forward", new=AsyncMock()):
                await edit(user_id, message, "Working", 5, task)

            rendered_text = message.edit.await_args.args[0]
            markup = message.edit.await_args.kwargs["reply_markup"]
            callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
            self.assertIn("[██████████░░░░░░░░░░]", rendered_text)
            self.assertIn("ETA", rendered_text)
            self.assertEqual(callbacks, ["terminate_frwd"])
        finally:
            task.data.pop(task_id, None)

    def test_progress_bar_clamps_percentages_and_has_fixed_width(self):
        self.assertEqual(render_progress_bar(50, width=4), "[██░░]")
        self.assertEqual(render_progress_bar(150, width=4), "[████]")
        self.assertEqual(render_progress_bar(-5, width=4), "[░░░░]")


if __name__ == "__main__":
    unittest.main()
