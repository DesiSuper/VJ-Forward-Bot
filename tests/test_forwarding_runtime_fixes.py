import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from pyrogram.errors import ChatWriteForbidden

from config import temp
from plugins.db import MongoDB
from plugins.forwarding import (
    DestinationPermissionError,
    copy,
    custom_caption,
    forward_source_messages,
    store_vars,
    stop,
)
from plugins.utils import STATUS, STS


class FakeTask:
    def __init__(self, total=1000):
        self.values = {
            "total": total,
            "fetched": 0,
            "total_files": 0,
            "videos": 0,
            "photos": 0,
            "duplicate": 0,
            "filtered": 0,
            "deleted": 0,
        }

    def add(self, key, value=1, **kwargs):
        self.values[key] = self.values.get(key, 0) + value

    def get(self, key):
        return self.values.get(key)


class ForwardingRuntimeFixTests(unittest.IsolatedAsyncioTestCase):
    async def test_forward_tag_flushes_final_partial_batch_and_persists_unique_ids(self):
        messages = [
            SimpleNamespace(
                id=index,
                empty=False,
                service=False,
                document=SimpleNamespace(
                    file_unique_id=f"stable-{index}",
                    file_id=f"temporary-{index}",
                    file_name=f"{index}.pdf",
                    file_size=10,
                    mime_type="application/pdf",
                ),
                media=None,
            )
            for index in range(1, 4)
        ]

        async def source_iter(*args, **kwargs):
            for item in messages:
                yield item

        task = FakeTask()
        user_db = SimpleNamespace(add_file=AsyncMock())
        forwarded_batches = []

        async def forward(*args):
            forwarded_batches.append(list(args[2]))
            return True

        with (
            patch("plugins.forwarding.iter_messages", source_iter),
            patch("plugins.forwarding.is_cancelled", new=AsyncMock(return_value=False)),
            patch("plugins.forwarding.edit", new=AsyncMock()),
            patch("plugins.forwarding.forward", side_effect=forward),
            patch("plugins.forwarding.pause_between_messages", new=AsyncMock()),
            patch("plugins.forwarding.persist_task_checkpoint", new=AsyncMock()) as checkpoint,
        ):
            result = await forward_source_messages(
                9,
                object(),
                SimpleNamespace(id=1),
                task,
                0,
                {
                    "filters": {},
                    "max_size": 0,
                    "min_size": 0,
                    "extensions": (),
                    "keywords": (),
                    "skip_duplicate": True,
                },
                None,
                True,
                False,
                None,
                user_db,
                set(),
                (0, 0),
                0,
            )

        self.assertTrue(result)
        self.assertEqual(forwarded_batches, [[1, 2, 3]])
        self.assertEqual(task.get("total_files"), 3)
        checkpoint.assert_awaited_once()
        self.assertEqual(
            [call.args[0] for call in user_db.add_file.await_args_list],
            ["stable-1", "stable-2", "stable-3"],
        )

    async def test_copy_aborts_on_destination_permission_error_instead_of_counting_deleted(self):
        client = SimpleNamespace(copy_message=AsyncMock(side_effect=ChatWriteForbidden()))
        task = FakeTask()

        with self.assertRaises(DestinationPermissionError):
            await copy(9, client, {"msg_id": 1}, SimpleNamespace(id=2), task)

        self.assertEqual(task.get("deleted"), 0)

    async def test_non_tag_copy_checkpoints_each_processed_message(self):
        messages = [
            SimpleNamespace(id=index, empty=False, service=False, document=None, media=None)
            for index in range(1, 4)
        ]

        async def source_iter(*args, **kwargs):
            for item in messages:
                yield item

        checkpoint = AsyncMock()
        with (
            patch("plugins.forwarding.iter_messages", source_iter),
            patch("plugins.forwarding.is_cancelled", new=AsyncMock(return_value=False)),
            patch("plugins.forwarding.edit", new=AsyncMock()),
            patch("plugins.forwarding.copy", new=AsyncMock(return_value=True)),
            patch("plugins.forwarding.persist_task_checkpoint", new=checkpoint),
            patch("plugins.forwarding.pause_between_messages", new=AsyncMock()),
        ):
            await forward_source_messages(
                9,
                object(),
                SimpleNamespace(id=1),
                FakeTask(),
                0,
                {
                    "filters": [],
                    "max_size": 0,
                    "min_size": 0,
                    "extensions": (),
                    "keywords": (),
                    "skip_duplicate": False,
                },
                None,
                False,
                False,
                None,
                None,
                set(),
                (0, 0),
                0,
            )

        self.assertEqual(checkpoint.await_count, 3)

    async def test_custom_caption_escapes_external_filename_and_none_caption_is_empty(self):
        document = SimpleNamespace(file_name="<b>spoof</b>.pdf", file_size=2048)
        message = SimpleNamespace(
            media=SimpleNamespace(value="document"),
            document=document,
            video=None,
            audio=None,
            photo=None,
            caption=None,
        )

        self.assertEqual(custom_caption(message, "{filename}"), "&lt;b&gt;spoof&lt;/b&gt;.pdf")
        self.assertEqual(custom_caption(message, "{caption}"), "")

    async def test_stop_releases_counter_lock_and_progress_edit_cache(self):
        from plugins.forwarding import _LAST_PROGRESS_EDIT

        user_id = 717
        destination = -100717
        temp.forwardings = 1
        temp.lock[user_id] = True
        temp.CANCEL[user_id] = True
        temp.IS_FRWD_CHAT.append(destination)
        _LAST_PROGRESS_EDIT[(user_id, 123)] = 1.0
        client = SimpleNamespace(stop=AsyncMock())
        with patch("plugins.forwarding.db.rmve_frwd", new=AsyncMock()):
            await stop(client, user_id, destination=destination)

        self.assertEqual(temp.forwardings, 0)
        self.assertFalse(temp.lock[user_id])
        self.assertNotIn(user_id, temp.CANCEL)
        self.assertNotIn(destination, temp.IS_FRWD_CHAT)
        self.assertNotIn((user_id, 123), _LAST_PROGRESS_EDIT)

    async def test_resume_task_store_uses_supported_task_id_argument(self):
        STATUS.clear()
        details = {
            "fetched": 10,
            "chat_id": -1001,
            "toid": -1002,
            "skip": 2,
            "limit": 50,
        }
        with patch("plugins.forwarding.db.get_forward_details", new=AsyncMock(return_value=details)):
            task_id = await store_vars(123)
        self.assertEqual(task_id, "123-10")
        self.assertTrue(STS(task_id).verify())
        STATUS.clear()

    async def test_optional_db_cursor_is_returned_directly_and_unique_id_upsert_is_idempotent(self):
        database = MongoDB("mongodb://localhost", "db", "files")
        cursor = object()
        collection = SimpleNamespace(
            find=unittest.mock.Mock(return_value=cursor),
            update_one=AsyncMock(return_value="updated"),
            find_one=AsyncMock(return_value={"_id": 1}),
        )
        database.files = collection

        self.assertIs(await database.get_all_files(), cursor)
        self.assertEqual(await database.add_file("stable-id"), "updated")
        self.assertTrue(await database.is_file_exit("stable-id"))
        collection.update_one.assert_awaited_once_with(
            {"file_unique_id": "stable-id"},
            {"$setOnInsert": {"file_unique_id": "stable-id"}},
            upsert=True,
        )
        collection.find_one.assert_awaited_once_with(
            {"file_unique_id": "stable-id"}, {"_id": 1}
        )


if __name__ == "__main__":
    unittest.main()
