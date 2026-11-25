"""MongoDB persistence for bot users, integrations, channels, and jobs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import motor.motor_asyncio

from config import Config
from secret_store import decrypt_secret, encrypt_secret, is_encrypted

DEFAULT_CONFIG: dict[str, Any] = {
    "caption": None,
    "duplicate": True,
    "forward_tag": False,
    "min_size": 0,
    "max_size": 0,
    "extension": None,
    "keywords": None,
    "sources": [],
    "protect": None,
    "db_uri": None,
    "random_gap": {"min": 0, "max": 0},
    "filters": {
        "poll": False,
        "text": True,
        "audio": True,
        "voice": False,
        "video_note": True,
        "video": True,
        "photo": True,
        "document": True,
        "animation": False,
        "sticker": False,
    },
}

DEFAULT_FORWARD_DETAILS: dict[str, Any] = {
    "chat_id": None,
    "forward_id": None,
    "toid": None,
    "last_id": None,
    "limit": None,
    "msg_id": None,
    "start_time": None,
    "fetched": 0,
    "offset": 0,
    "deleted": 0,
    "total": 0,
    "videos": 0,
    "photos": 0,
    "duplicate": 0,
    "skip": 0,
    "filtered": 0,
}


class Db:
    """Thin async repository over the collections used by the legacy handlers.

    The client is created lazily so importing handler modules does not require
    a configured MongoDB URI. Every database operation still reports a clear
    startup/configuration error if the URI is missing.
    """

    def __init__(self, uri: str, database_name: str) -> None:
        self.uri = uri
        self.database_name = database_name
        self._client: motor.motor_asyncio.AsyncIOMotorClient | None = None
        self.db = None
        self.bot = self.userbot = self.col = self.nfy = self.chl = None
        if uri:
            self._open_client()

    def _open_client(self) -> None:
        self._client = motor.motor_asyncio.AsyncIOMotorClient(
            self.uri,
            serverSelectionTimeoutMS=10_000,
            connectTimeoutMS=10_000,
        )
        self.db = self._client[self.database_name]
        self.bot = self.db.bots
        self.userbot = self.db.userbot
        self.col = self.db.users
        self.nfy = self.db.notify
        self.chl = self.db.channels

    def _require_database(self) -> None:
        if self._client is None:
            raise RuntimeError("DATABASE_URI is required to use MongoDB")

    async def connect(self) -> None:
        """Verify connectivity and create lightweight lookup indexes."""
        self._require_database()
        await self._client.admin.command("ping")
        await self.col.create_index("id")
        await self.bot.create_index("user_id")
        await self.userbot.create_index("user_id")
        await self.nfy.create_index("user_id")
        await self.chl.create_index([("user_id", 1), ("chat_id", 1)])
        await self._encrypt_legacy_credentials()

    async def _encrypt_legacy_credentials(self) -> None:
        """Migrate legacy plaintext secrets without logging their values."""
        for collection, field in ((self.bot, "token"), (self.userbot, "session")):
            async for record in collection.find({field: {"$type": "string"}}):
                value = record.get(field)
                if not value or is_encrypted(value):
                    continue
                await collection.update_one(
                    {"_id": record["_id"], field: value},
                    {"$set": {field: encrypt_secret(value)}},
                )

        async for record in self.col.find({"configs.db_uri": {"$type": "string"}}):
            configs = record.get("configs") or {}
            value = configs.get("db_uri") if isinstance(configs, dict) else None
            if not value or is_encrypted(value):
                continue
            await self.col.update_one(
                {"_id": record["_id"], "configs.db_uri": value},
                {"$set": {"configs.db_uri": encrypt_secret(value)}},
            )

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()

    @staticmethod
    def new_user(user_id: int, name: str) -> dict[str, Any]:
        return {
            "id": int(user_id),
            "name": name,
            "ban_status": {"is_banned": False, "ban_reason": ""},
        }

    async def add_user(self, id: int, name: str) -> None:
        self._require_database()
        await self.col.update_one(
            {"id": int(id)},
            {"$setOnInsert": self.new_user(id, name)},
            upsert=True,
        )

    async def is_user_exist(self, id: int) -> bool:
        self._require_database()
        return await self.col.find_one({"id": int(id)}, {"_id": 1}) is not None

    async def total_users_count(self) -> int:
        self._require_database()
        return await self.col.count_documents({})

    async def remove_ban(self, id: int) -> None:
        self._require_database()
        await self.col.update_one(
            {"id": int(id)},
            {"$set": {"ban_status": {"is_banned": False, "ban_reason": ""}}},
        )

    async def ban_user(self, user_id: int, ban_reason: str = "No Reason") -> None:
        self._require_database()
        await self.col.update_one(
            {"id": int(user_id)},
            {"$set": {"ban_status": {"is_banned": True, "ban_reason": ban_reason}}},
        )

    async def get_ban_status(self, id: int) -> dict[str, Any]:
        self._require_database()
        user = await self.col.find_one({"id": int(id)}, {"ban_status": 1})
        return (user or {}).get("ban_status", {"is_banned": False, "ban_reason": ""})

    async def get_all_users(self):
        self._require_database()
        return self.col.find({})

    async def delete_user(self, user_id: int) -> None:
        self._require_database()
        await self.col.delete_many({"id": int(user_id)})

    async def get_banned(self) -> list[int]:
        self._require_database()
        cursor = self.col.find({"ban_status.is_banned": True}, {"id": 1})
        return [user["id"] async for user in cursor]

    async def update_configs(self, id: int, configs: dict[str, Any]) -> None:
        self._require_database()
        stored_configs = deepcopy(configs)
        if stored_configs.get("db_uri"):
            stored_configs["db_uri"] = encrypt_secret(stored_configs["db_uri"])
        await self.col.update_one(
            {"id": int(id)}, {"$set": {"configs": stored_configs}}
        )

    async def get_configs(self, id: int) -> dict[str, Any]:
        self._require_database()
        user = await self.col.find_one({"id": int(id)}, {"configs": 1})
        configs = deepcopy(DEFAULT_CONFIG)
        if user and isinstance(user.get("configs"), dict):
            stored = user["configs"]
            configs.update(stored)
            stored_filters = stored.get("filters")
            if isinstance(stored_filters, dict):
                configs["filters"].update(stored_filters)
        for disabled_type in ("voice", "animation", "sticker", "poll"):
            configs["filters"][disabled_type] = False
        if configs.get("db_uri"):
            configs["db_uri"] = decrypt_secret(configs["db_uri"])
        # Old custom button settings are deliberately ignored and removed.
        configs.pop("button", None)
        return configs

    async def add_bot(self, datas: dict[str, Any]) -> None:
        self._require_database()
        stored = deepcopy(datas)
        if stored.get("token"):
            stored["token"] = encrypt_secret(stored["token"])
        await self.bot.update_one(
            {"user_id": int(stored["user_id"])}, {"$set": stored}, upsert=True
        )

    async def remove_bot(self, user_id: int) -> None:
        self._require_database()
        await self.bot.delete_many({"user_id": int(user_id)})

    async def get_bot(self, user_id: int) -> dict[str, Any] | None:
        self._require_database()
        account = await self.bot.find_one({"user_id": int(user_id)})
        if account and account.get("token"):
            account["token"] = decrypt_secret(account["token"])
        return account

    async def add_userbot(self, datas: dict[str, Any]) -> None:
        self._require_database()
        stored = deepcopy(datas)
        if stored.get("session"):
            stored["session"] = encrypt_secret(stored["session"])
        await self.userbot.update_one(
            {"user_id": int(stored["user_id"])}, {"$set": stored}, upsert=True
        )

    async def remove_userbot(self, user_id: int) -> None:
        self._require_database()
        await self.userbot.delete_many({"user_id": int(user_id)})

    async def get_userbot(self, user_id: int) -> dict[str, Any] | None:
        self._require_database()
        account = await self.userbot.find_one({"user_id": int(user_id)})
        if account and account.get("session"):
            account["session"] = decrypt_secret(account["session"])
        return account

    async def in_channel(self, user_id: int, chat_id: int) -> bool:
        self._require_database()
        return await self.chl.find_one(
            {"user_id": int(user_id), "chat_id": int(chat_id)}, {"_id": 1}
        ) is not None

    async def add_channel(
        self, user_id: int, chat_id: int, title: str, username: str | None
    ):
        self._require_database()
        if await self.in_channel(user_id, chat_id):
            return False
        return await self.chl.insert_one(
            {"user_id": int(user_id), "chat_id": int(chat_id), "title": title, "username": username}
        )

    async def update_channel(
        self,
        user_id: int,
        old_chat_id: int,
        chat_id: int,
        title: str,
        username: str | None,
    ) -> bool:
        """Replace a saved destination chat without disturbing its other settings."""
        self._require_database()
        if int(old_chat_id) != int(chat_id) and await self.in_channel(user_id, chat_id):
            return False
        result = await self.chl.update_one(
            {"user_id": int(user_id), "chat_id": int(old_chat_id)},
            {"$set": {"chat_id": int(chat_id), "title": title, "username": username}},
        )
        return result.matched_count > 0

    async def remove_channel(self, user_id: int, chat_id: int):
        self._require_database()
        return await self.chl.delete_many(
            {"user_id": int(user_id), "chat_id": int(chat_id)}
        )

    async def get_channel_details(self, user_id: int, chat_id: int):
        self._require_database()
        return await self.chl.find_one(
            {"user_id": int(user_id), "chat_id": int(chat_id)}
        )

    async def get_user_channels(self, user_id: int) -> list[dict[str, Any]]:
        self._require_database()
        return [channel async for channel in self.chl.find({"user_id": int(user_id)})]

    async def get_filters(self, user_id: int) -> list[str]:
        configs = await self.get_configs(user_id)
        return [name for name, enabled in configs.get("filters", {}).items() if not enabled]

    async def add_frwd(self, user_id: int):
        self._require_database()
        await self.nfy.update_one(
            {"user_id": int(user_id)}, {"$setOnInsert": {"user_id": int(user_id)}}, upsert=True
        )

    async def rmve_frwd(self, user_id: int = 0, all: bool = False):
        self._require_database()
        return await self.nfy.delete_many({} if all else {"user_id": int(user_id)})

    async def get_all_frwd(self):
        self._require_database()
        return self.nfy.find({})

    async def is_forwad_exit(self, user: int) -> bool:
        self._require_database()
        return await self.nfy.find_one({"user_id": int(user)}, {"_id": 1}) is not None

    async def get_forward_details(self, user_id: int) -> dict[str, Any]:
        self._require_database()
        user = await self.nfy.find_one({"user_id": int(user_id)}, {"details": 1})
        stored_details = (user or {}).get("details")
        if not isinstance(stored_details, dict):
            return deepcopy(DEFAULT_FORWARD_DETAILS)
        details = deepcopy(DEFAULT_FORWARD_DETAILS)
        details.update(stored_details)
        return details

    async def update_forward(self, user_id: int, details: dict[str, Any]) -> None:
        self._require_database()
        await self.nfy.update_one(
            {"user_id": int(user_id)},
            {"$set": {"user_id": int(user_id), "details": details}},
            upsert=True,
        )


# Existing plugin modules import this singleton directly.
db = Db(Config.DATABASE_URI, Config.DATABASE_NAME)
