"""Shared task state and per-user forwarding configuration helpers."""

from __future__ import annotations

import time as clock
from typing import Any

from database import db

from .clients import parse_buttons

STATUS: dict[str, dict[str, Any]] = {}


class STS:
    """In-memory progress state for a forwarding task."""

    def __init__(self, task_id: str) -> None:
        self.id = task_id
        self.data = STATUS

    def verify(self):
        return self.data.get(self.id)

    def store(self, source: int | str, target: int | str, skip: int, limit: int):
        self.data[self.id] = {
            "FROM": source,
            "TO": target,
            "total_files": 0,
            "skip": skip,
            "limit": limit,
            "fetched": skip,
            "filtered": 0,
            "deleted": 0,
            "duplicate": 0,
            "total": limit,
            "start": 0,
        }
        self.get(full=True)
        return STS(self.id)

    def get(self, value=None, full: bool = False):
        values = self.data.get(self.id)
        if not full:
            return values.get(value)
        for key, item in values.items():
            setattr(self, key, item)
        return self

    def add(self, key=None, value: int = 1, time: bool = False, start_time=None):
        if time:
            timestamp = clock.time() if start_time is None else start_time
            self.data[self.id].update({"start": timestamp})
            return
        self.data[self.id][key] = self.get(key) + value

    @staticmethod
    def divide(number: float, divisor: float) -> float:
        return number / (divisor or 1)

    async def get_data(self, user_id: int):
        account = await db.get_bot(user_id)
        if account is None:
            account = await db.get_userbot(user_id)

        configs = await db.get_configs(user_id)
        disabled_filters = await db.get_filters(user_id)
        button = parse_buttons(configs.get("button") or "")
        random_gap = configs.get("random_gap") or {"min": 0, "max": 0}
        if not isinstance(random_gap, dict):
            random_gap = {"min": 0, "max": 0}

        options = {
            "filters": disabled_filters,
            "keywords": configs.get("keywords"),
            "min_size": int(configs.get("min_size") or 0),
            "max_size": int(configs.get("max_size") or 0),
            "extensions": configs.get("extension"),
            "skip_duplicate": bool(configs.get("duplicate", True)),
            "db_uri": configs.get("db_uri"),
            "random_gap": random_gap,
        }
        return (
            account,
            configs.get("caption"),
            bool(configs.get("forward_tag", False)),
            options,
            configs.get("protect"),
            button,
        )
