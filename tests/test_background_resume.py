import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from plugins.forwarding import (
    _BACKGROUND_FORWARD_TASKS,
    cancel_pending_forwards,
    restart_forwards,
)
from config import temp


class AsyncCursor:
    def __aiter__(self):
        async def iterate():
            yield {"user_id": 818}
        return iterate()


class BackgroundResumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        await cancel_pending_forwards()
        _BACKGROUND_FORWARD_TASKS.clear()

    async def test_startup_schedules_resume_workers_and_returns_without_waiting_for_forwarding(self):
        started = asyncio.Event()
        gate = asyncio.Event()

        async def resume_worker(client, user):
            started.set()
            await gate.wait()

        with (
            patch("plugins.forwarding.db.get_all_frwd", new=AsyncMock(return_value=AsyncCursor())),
            patch("plugins.forwarding.restart_pending_forwads", side_effect=resume_worker),
        ):
            await restart_forwards(object())
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertEqual(len(_BACKGROUND_FORWARD_TASKS), 1)
            self.assertTrue(temp.lock.get(818))
            await cancel_pending_forwards()

        self.assertFalse(temp.lock.get(818))
        self.assertFalse(_BACKGROUND_FORWARD_TASKS)


if __name__ == "__main__":
    unittest.main()
