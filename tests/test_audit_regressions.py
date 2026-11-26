import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database import DEFAULT_CONFIG
from plugins.clients import reset_settings


class AuditRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_reset_writes_real_defaults_without_mutating_shared_config(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=456), reply=AsyncMock())
        with patch("plugins.clients.db.update_configs", new=AsyncMock()) as update:
            await reset_settings(None, message)

        update.assert_awaited_once_with(456, DEFAULT_CONFIG)
        self.assertIsNot(update.await_args.args[1], DEFAULT_CONFIG)
        message.reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
