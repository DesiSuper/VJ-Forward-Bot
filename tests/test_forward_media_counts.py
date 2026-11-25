import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from plugins.forwarding import media_counter_key, update_forward


class ForwardMediaCountTests(unittest.TestCase):
    def test_counts_native_video_and_video_note_as_video(self):
        self.assertEqual(media_counter_key(SimpleNamespace(video=object())), "videos")
        self.assertEqual(media_counter_key(SimpleNamespace(video_note=object())), "videos")

    def test_counts_photos_and_image_documents(self):
        self.assertEqual(media_counter_key(SimpleNamespace(photo=object())), "photos")
        image_document = SimpleNamespace(
            document=SimpleNamespace(mime_type="image/png", file_name="upload.bin")
        )
        self.assertEqual(media_counter_key(image_document), "photos")

    def test_counts_video_documents_by_mime_type_or_extension(self):
        mime_document = SimpleNamespace(
            document=SimpleNamespace(mime_type="video/mp4", file_name="upload.bin")
        )
        extension_document = SimpleNamespace(
            document=SimpleNamespace(mime_type="application/octet-stream", file_name="clip.mkv")
        )
        self.assertEqual(media_counter_key(mime_document), "videos")
        self.assertEqual(media_counter_key(extension_document), "videos")

    def test_non_video_image_message_has_no_media_counter(self):
        self.assertIsNone(media_counter_key(SimpleNamespace(document=None, text="hello")))


class ForwardProgressPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_forward_persists_video_and_photo_counts(self):
        with patch("plugins.forwarding.db.update_forward", new=AsyncMock()) as persist:
            await update_forward(
                user_id=1,
                chat_id=-1001,
                start_time=100.0,
                toid=-1002,
                last_id=None,
                limit=50,
                forward_id=None,
                msg_id=99,
                fetched=10,
                total=8,
                duplicate=1,
                deleted=0,
                skip=0,
                filterd=1,
                videos=3,
                photos=2,
            )

        persist.assert_awaited_once()
        details = persist.await_args.args[1]
        self.assertEqual(details["videos"], 3)
        self.assertEqual(details["photos"], 2)


if __name__ == "__main__":
    unittest.main()
