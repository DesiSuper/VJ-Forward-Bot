"""MongoDB persistence for bot users, integrations, channels, and jobs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import motor.motor_asyncio

from config import Config

DEFAULT_CONFIG: dict[str, Any] = {
    "caption": None,
    "duplicate": True,
    "forward_tag": False,
    "min_size": 0,
    "max_size": 0,
    "extension": None,
    "keywords": None,
    "protect": None,
    "button": None,
    "db_uri": None,
    "random_gap": {"min": 0, "max": 0},
    "filters": {
        "poll": True,
        "text": True,
        "audio": True,
        "voice": True,
        "video_note": True,
        "video": True,
        "photo": True,
        "document": True,
        "animation": True,
        "sticker": True,
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

    async def total_users_bots_count(self) -> tuple[int, int]:
        self._require_database()
        return await self.total_users_count(), await self.bot.count_documents({})

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
        await self.col.update_one(
            {"id": int(id)}, {"$set": {"configs": configs}}
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
        return configs

    async def add_bot(self, datas: dict[str, Any]) -> None:
        self._require_database()
        await self.bot.update_one(
            {"user_id": int(datas["user_id"])}, {"$set": datas}, upsert=True
        )

    async def remove_bot(self, user_id: int) -> None:
        self._require_database()
        await self.bot.delete_many({"user_id": int(user_id)})

    async def get_bot(self, user_id: int) -> dict[str, Any] | None:
        self._require_database()
        return await self.bot.find_one({"user_id": int(user_id)})

    async def is_bot_exist(self, user_id: int) -> bool:
        return await self.get_bot(user_id) is not None

    async def add_userbot(self, datas: dict[str, Any]) -> None:
        self._require_database()
        await self.userbot.update_one(
            {"user_id": int(datas["user_id"])}, {"$set": datas}, upsert=True
        )

    async def remove_userbot(self, user_id: int) -> None:
        self._require_database()
        await self.userbot.delete_many({"user_id": int(user_id)})

    async def get_userbot(self, user_id: int) -> dict[str, Any] | None:
        self._require_database()
        return await self.userbot.find_one({"user_id": int(user_id)})

    async def is_userbot_exist(self, user_id: int) -> bool:
        return await self.get_userbot(user_id) is not None

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

    async def forwad_count(self) -> int:
        self._require_database()
        return await self.nfy.count_documents({})

    async def is_forwad_exit(self, user: int) -> bool:
        self._require_database()
        return await self.nfy.find_one({"user_id": int(user)}, {"_id": 1}) is not None

    async def get_forward_details(self, user_id: int) -> dict[str, Any]:
        self._require_database()
        user = await self.nfy.find_one({"user_id": int(user_id)}, {"details": 1})
        if not user or "details" not in user:
            return deepcopy(DEFAULT_FORWARD_DETAILS)
        return user["details"]

    async def update_forward(self, user_id: int, details: dict[str, Any]) -> None:
        self._require_database()
        await self.nfy.update_one(
            {"user_id": int(user_id)},
            {"$set": {"user_id": int(user_id), "details": details}},
            upsert=True,
        )


# Existing plugin modules import this singleton directly.
db = Db(Config.DATABASE_URI, Config.DATABASE_NAME)
