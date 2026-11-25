import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from plugins.instagram.insta import (
    DownloadedInstagramMedia,
    InvalidInstagramURL,
    instagram_link_handler,
    validate_instagram_url,
)


class InstagramPluginTests(unittest.TestCase):
    def test_normalizes_supported_public_instagram_urls(self):
        self.assertEqual(
            validate_instagram_url("www.instagram.com/reel/ABC123/?igsh=xyz"),
            "https://www.instagram.com/reel/ABC123/?igsh=xyz",
        )
        self.assertEqual(
            validate_instagram_url("https://instagr.am/p/ABC123/"),
            "https://instagr.am/p/ABC123/",
        )

    def test_rejects_non_instagram_and_malformed_urls(self):
        for url in (
            "https://instagram.com.evil.example/p/1/",
            "https://example.com/instagram.com/p/1/",
            "https://instagram.com:1234/p/1/",
            "https://instagram.com:invalid/p/1/",
            "javascript://instagram.com/p/1/",
            "https://instagram.com/",
        ):
            with self.subTest(url=url), self.assertRaises(InvalidInstagramURL):
                validate_instagram_url(url)


class InstagramHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_public_reel_download_is_sent_as_video_and_temporary_media_is_cleaned(self):
        sent_status = SimpleNamespace(delete=AsyncMock(), edit_text=AsyncMock())
        message = SimpleNamespace(
            text="Check this reel https://www.instagram.com/reel/ABC123/",
            chat=SimpleNamespace(id=77),
            from_user=SimpleNamespace(id=77),
            reply_text=AsyncMock(return_value=sent_status),
        )
        client = SimpleNamespace(send_video=AsyncMock(), send_photo=AsyncMock(), send_document=AsyncMock())
        observed_path = None

        def fake_download(url, output_dir):
            nonlocal observed_path
            self.assertEqual(url, "https://www.instagram.com/reel/ABC123/")
            observed_path = Path(output_dir) / "reel.mp4"
            observed_path.write_bytes(b"test video")
            return DownloadedInstagramMedia(
                str(observed_path), "A public reel", duration=17, width=720, height=1280
            )

        with patch("plugins.instagram.insta.download_instagram_media", side_effect=fake_download):
            await instagram_link_handler(client, message)

        client.send_video.assert_awaited_once()
        client.send_photo.assert_not_awaited()
        client.send_document.assert_not_awaited()
        self.assertEqual(client.send_video.await_args.args[:2], (77, str(observed_path)))
        self.assertEqual(client.send_video.await_args.kwargs["duration"], 17)
        self.assertEqual(client.send_video.await_args.kwargs["width"], 720)
        self.assertEqual(client.send_video.await_args.kwargs["height"], 1280)
        self.assertFalse(client.send_video.await_args.kwargs["no_sound"])
        sent_status.delete.assert_awaited_once()
        self.assertFalse(observed_path.exists())

    async def test_video_without_metadata_is_sent_as_document_instead_of_blank_video(self):
        sent_status = SimpleNamespace(delete=AsyncMock(), edit_text=AsyncMock())
        message = SimpleNamespace(
            text="https://instagram.com/reel/ABC123/",
            chat=SimpleNamespace(id=77),
            from_user=SimpleNamespace(id=77),
            reply_text=AsyncMock(return_value=sent_status),
        )
        client = SimpleNamespace(send_video=AsyncMock(), send_photo=AsyncMock(), send_document=AsyncMock())

        def fake_download(url, output_dir):
            path = Path(output_dir) / "reel.mp4"
            path.write_bytes(b"test video")
            return DownloadedInstagramMedia(str(path), "Reel", duration=0, width=0, height=0)

        with patch("plugins.instagram.insta.download_instagram_media", side_effect=fake_download):
            await instagram_link_handler(client, message)

        client.send_video.assert_not_awaited()
        client.send_document.assert_awaited_once()

    async def test_invalid_instagram_host_is_not_downloaded(self):
        message = SimpleNamespace(
            text="https://instagram.com.evil.example/p/1/",
            chat=SimpleNamespace(id=77),
            from_user=SimpleNamespace(id=77),
            reply_text=AsyncMock(),
        )
        client = SimpleNamespace()
        with patch("plugins.instagram.insta.download_instagram_media") as download:
            await instagram_link_handler(client, message)
        download.assert_not_called()
        message.reply_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
