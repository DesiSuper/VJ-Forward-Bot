import unittest
from types import SimpleNamespace

from plugins.forwarding import media_counter_key


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


if __name__ == "__main__":
    unittest.main()
