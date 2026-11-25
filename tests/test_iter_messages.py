import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from plugins.clients import iter_messages


class MessageIterationTests(unittest.IsolatedAsyncioTestCase):
    async def test_iterates_one_based_ids_without_including_zero_or_extra_boundary(self):
        client = SimpleNamespace(
            get_messages=AsyncMock(
                return_value=[
                    SimpleNamespace(id=1, document=True),
                    SimpleNamespace(id=2, document=True),
                    SimpleNamespace(id=3, document=True),
                ]
            )
        )

        result = [item async for item in iter_messages(client, -100, limit=3)]

        self.assertEqual([item.id for item in result], [1, 2, 3])
        client.get_messages.assert_awaited_once_with(-100, [1, 2, 3])

    async def test_resume_offset_starts_after_already_processed_message_ids(self):
        client = SimpleNamespace(
            get_messages=AsyncMock(
                return_value=[
                    SimpleNamespace(id=4, document=True),
                    SimpleNamespace(id=5, document=True),
                ]
            )
        )

        result = [item async for item in iter_messages(client, -100, limit=5, offset=3)]

        self.assertEqual([item.id for item in result], [4, 5])
        client.get_messages.assert_awaited_once_with(-100, [4, 5])

    async def test_missing_message_ids_are_counted_as_deleted_markers(self):
        client = SimpleNamespace(get_messages=AsyncMock(return_value=[None, None]))

        result = [item async for item in iter_messages(client, -100, limit=2)]

        self.assertEqual(result, ["DELETED", "DELETED"])

    async def test_empty_or_exhausted_ranges_do_not_call_telegram(self):
        client = SimpleNamespace(get_messages=AsyncMock())

        result = [item async for item in iter_messages(client, -100, limit=5, offset=5)]

        self.assertEqual(result, [])
        client.get_messages.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
