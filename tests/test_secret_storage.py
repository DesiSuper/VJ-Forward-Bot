import unittest
from unittest.mock import AsyncMock, Mock, patch

from cryptography.fernet import Fernet

from config import Config
from database import Db
from secret_store import decrypt_secret, encrypt_secret


class AsyncCursor:
    def __init__(self, records):
        self.records = records

    def __aiter__(self):
        async def iterate():
            for record in self.records:
                yield record
        return iterate()


class SecretStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.key = Fernet.generate_key().decode()
        self.config_patch = patch.object(Config, "CREDENTIAL_ENCRYPTION_KEY", self.key)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)

    async def test_secrets_round_trip_and_ciphertext_does_not_contain_plaintext(self):
        secret = "token-or-session-or-mongodb-uri"
        encrypted = encrypt_secret(secret)

        self.assertTrue(encrypted.startswith("fernet:v1:"))
        self.assertNotIn(secret, encrypted)
        self.assertEqual(decrypt_secret(encrypted), secret)
        self.assertEqual(decrypt_secret("legacy-plaintext"), "legacy-plaintext")

    async def test_bot_and_userbot_credentials_are_encrypted_in_storage_and_decrypted_on_read(self):
        database = Db("mongodb://example", "db")
        database.bot = type("Collection", (), {})()
        database.userbot = type("Collection", (), {})()
        database.bot.update_one = AsyncMock()
        database.userbot.update_one = AsyncMock()
        database.bot.find_one = AsyncMock(return_value={"token": encrypt_secret("bot-secret")})
        database.userbot.find_one = AsyncMock(return_value={"session": encrypt_secret("session-secret")})

        await database.add_bot({"user_id": 1, "token": "bot-secret"})
        await database.add_userbot({"user_id": 1, "session": "session-secret"})
        bot = await database.get_bot(1)
        userbot = await database.get_userbot(1)

        bot_payload = database.bot.update_one.await_args.args[1]["$set"]
        user_payload = database.userbot.update_one.await_args.args[1]["$set"]
        self.assertNotIn("bot-secret", bot_payload["token"])
        self.assertNotIn("session-secret", user_payload["session"])
        self.assertEqual(bot["token"], "bot-secret")
        self.assertEqual(userbot["session"], "session-secret")

    async def test_startup_migrates_legacy_plaintext_secrets_without_logging_values(self):
        database = Db("mongodb://example", "db")
        bot_records = [{"_id": 1, "token": "legacy-bot-token"}]
        user_records = [{"_id": 2, "session": "legacy-session"}]
        config_records = [{"_id": 3, "configs": {"db_uri": "mongodb://legacy"}}]
        database.bot = type("Collection", (), {})()
        database.userbot = type("Collection", (), {})()
        database.col = type("Collection", (), {})()
        for collection, records in (
            (database.bot, bot_records),
            (database.userbot, user_records),
            (database.col, config_records),
        ):
            collection.find = Mock(return_value=AsyncCursor(records))
            collection.update_one = AsyncMock()

        await database._encrypt_legacy_credentials()

        self.assertEqual(database.bot.update_one.await_count, 1)
        self.assertEqual(database.userbot.update_one.await_count, 1)
        self.assertEqual(database.col.update_one.await_count, 1)
        for collection in (database.bot, database.userbot, database.col):
            stored = collection.update_one.await_args.args[1]["$set"]
            self.assertTrue(next(iter(stored.values())).startswith("fernet:v1:"))

    async def test_custom_database_uri_is_encrypted_in_config_document(self):
        database = Db("mongodb://example", "db")
        database.col = type("Collection", (), {})()
        database.col.update_one = AsyncMock()
        database.col.find_one = AsyncMock(
            return_value={"configs": {"db_uri": encrypt_secret("mongodb://user:password@host/db")}}
        )

        await database.update_configs(3, {"db_uri": "mongodb://user:password@host/db"})
        configs = await database.get_configs(3)

        stored_uri = database.col.update_one.await_args.args[1]["$set"]["configs"]["db_uri"]
        self.assertNotIn("password", stored_uri)
        self.assertEqual(configs["db_uri"], "mongodb://user:password@host/db")


if __name__ == "__main__":
    unittest.main()
