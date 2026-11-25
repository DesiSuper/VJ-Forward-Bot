import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram.errors import FloodWait, PeerIdInvalid

from database import DEFAULT_CONFIG
from plugins.broadcast import broadcast_messages
from plugins.clients import reset_settings


class AuditRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_peer_id_invalid_does_not_delete_user_record(self):
        message = SimpleNamespace(copy=AsyncMock(side_effect=PeerIdInvalid()))
        with patch("plugins.broadcast.db.delete_user", new=AsyncMock()) as delete_user:
            result = await broadcast_messages(123, message)

        self.assertEqual(result, (False, "Error"))
        delete_user.assert_not_awaited()

    async def test_broadcast_retries_floodwait_without_recursive_reentry(self):
        message = SimpleNamespace(copy=AsyncMock(side_effect=[FloodWait(0), None]))
        with patch("plugins.broadcast.asyncio.sleep", new=AsyncMock()) as sleep:
            result = await broadcast_messages(123, message)

        self.assertEqual(result, (True, "Success"))
        self.assertEqual(message.copy.await_count, 2)
        sleep.assert_awaited_once_with(0)

    async def test_user_reset_writes_real_defaults_without_mutating_shared_config(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=456), reply=AsyncMock())
        with patch("plugins.clients.db.update_configs", new=AsyncMock()) as update:
            await reset_settings(None, message)

        update.assert_awaited_once_with(456, DEFAULT_CONFIG)
        self.assertIsNot(update.await_args.args[1], DEFAULT_CONFIG)
        message.reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
