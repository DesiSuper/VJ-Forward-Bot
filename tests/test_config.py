import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from config import Config, _integer, _integer_list

ENCRYPTION_KEY = Fernet.generate_key().decode()


class ConfigurationTests(unittest.TestCase):
    def test_integer_reads_value_and_default(self):
        with patch.dict(os.environ, {"TEST_INTEGER": "42"}, clear=False):
            self.assertEqual(_integer("TEST_INTEGER"), 42)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_integer("MISSING_INTEGER", 7), 7)

    def test_integer_list_accepts_space_and_comma_separated_ids(self):
        with patch.dict(
            os.environ,
            {"BOT_OWNER": "5292444428 5203913929,310042633 5364274733"},
            clear=True,
        ):
            self.assertEqual(
                _integer_list("BOT_OWNER", "BOT_OWNER_ID"),
                (5292444428, 5203913929, 310042633, 5364274733),
            )

    def test_integer_list_uses_legacy_owner_id_fallback_and_deduplicates(self):
        with patch.dict(
            os.environ, {"BOT_OWNER_ID": "123456,123456"}, clear=True
        ):
            self.assertEqual(_integer_list("BOT_OWNER", "BOT_OWNER_ID"), (123456,))

    def test_integer_list_reports_invalid_value_by_variable_name(self):
        with patch.dict(os.environ, {"BOT_OWNER": "123 nope"}, clear=True):
            with self.assertRaisesRegex(ValueError, "BOT_OWNER"):
                _integer_list("BOT_OWNER", "BOT_OWNER_ID")

    def test_config_checks_each_configured_admin_id(self):
        with patch.multiple(
            Config,
            BOT_OWNER=5292444428,
            BOT_OWNERS=(5292444428, 5203913929, 310042633),
        ):
            self.assertTrue(Config.is_bot_owner(5203913929))
            self.assertFalse(Config.is_bot_owner(999))

    def test_integer_reports_invalid_value_by_variable_name(self):
        with patch.dict(os.environ, {"TEST_INTEGER": "not-a-number"}, clear=False):
            with self.assertRaisesRegex(ValueError, "TEST_INTEGER"):
                _integer("TEST_INTEGER")

    def test_validate_reports_all_missing_values(self):
        settings = {
            "API_ID": 0,
            "API_HASH": "",
            "BOT_TOKEN": "",
            "DATABASE_URI": "",
            "CREDENTIAL_ENCRYPTION_KEY": "",
            "BOT_OWNER": 0,
        }
        with patch.multiple(Config, **settings):
            with self.assertRaises(RuntimeError) as error:
                Config.validate()
        for name in ("API_ID", "API_HASH", "BOT_TOKEN", "DATABASE_URI", "CREDENTIAL_ENCRYPTION_KEY", "BOT_OWNER"):
            self.assertIn(name, str(error.exception))

    def test_validate_rejects_non_positive_api_id(self):
        settings = {
            "API_ID": -1,
            "API_HASH": "hash",
            "BOT_TOKEN": "token",
            "DATABASE_URI": "mongodb://example",
            "CREDENTIAL_ENCRYPTION_KEY": ENCRYPTION_KEY,
            "BOT_OWNER": 123456,
        }
        with patch.multiple(Config, **settings):
            with self.assertRaisesRegex(RuntimeError, "API_ID must be a positive integer"):
                Config.validate()

    def test_validate_rejects_invalid_credential_encryption_key(self):
        settings = {
            "API_ID": 123,
            "API_HASH": "hash",
            "BOT_TOKEN": "token",
            "DATABASE_URI": "mongodb://example",
            "CREDENTIAL_ENCRYPTION_KEY": "not-a-fernet-key",
            "BOT_OWNER": 123456,
        }
        with patch.multiple(Config, **settings):
            with self.assertRaisesRegex(RuntimeError, "CREDENTIAL_ENCRYPTION_KEY"):
                Config.validate()

    def test_validate_accepts_complete_configuration(self):
        settings = {
            "API_ID": 123,
            "API_HASH": "hash",
            "BOT_TOKEN": "token",
            "DATABASE_URI": "mongodb://example",
            "CREDENTIAL_ENCRYPTION_KEY": ENCRYPTION_KEY,
            "BOT_OWNER": 123456,
        }
        with patch.multiple(Config, **settings):
            Config.validate()


if __name__ == "__main__":
    unittest.main()
