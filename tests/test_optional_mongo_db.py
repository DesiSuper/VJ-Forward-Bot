import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from plugins.db import MongoDB, connect_user_db


class OptionalMongoDBTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_pings_database_without_dropping_any_collection(self):
        collection = MagicMock()
        collection.create_index = AsyncMock()
        admin = SimpleNamespace(command=AsyncMock(return_value={"ok": 1}))
        database = MagicMock()
        database.__getitem__.return_value = collection
        client = MagicMock()
        client.__getitem__.return_value = database
        client.admin = admin
        with patch("plugins.db.motor.motor_asyncio.AsyncIOMotorClient", return_value=client):
            mongo = MongoDB("mongodb://host", "db", "collection")
            await mongo.connect()

        admin.command.assert_awaited_once_with("ping")
        collection.create_index.assert_awaited_once_with(
            "file_unique_id", unique=True, sparse=True
        )
        collection.drop.assert_not_called()

    async def test_failed_optional_connection_closes_client_and_returns_failure(self):
        mongo = MongoDB("mongodb://host", "db", "collection")
        mongo.connect = AsyncMock(side_effect=RuntimeError("connection unavailable"))
        mongo.close = AsyncMock()
        with patch("plugins.db.MongoDB", return_value=mongo):
            connected, returned = await connect_user_db(7, "mongodb://host", "room")

        self.assertFalse(connected)
        self.assertIs(returned, mongo)
        mongo.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
