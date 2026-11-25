import unittest

from plugins.media_filters import extension_filter, keyword_filter, size_filter


class MediaFilterTests(unittest.TestCase):
    def test_keyword_filter_is_literal_and_case_insensitive(self):
        self.assertTrue(keyword_filter(["holiday", "draft"], "HOLIDAY_video.mp4"))
        self.assertFalse(keyword_filter(["[test]"], "video_test.mp4"))
        self.assertFalse(keyword_filter(None, "video.mp4"))

    def test_extension_filter_checks_the_final_extension_case_insensitively(self):
        self.assertTrue(extension_filter(["mkv", ".mp4"], "movie.MKV"))
        self.assertFalse(extension_filter(["zip"], "archive.zip.mp4"))
        self.assertFalse(extension_filter(["zip"], "no-extension"))
        self.assertFalse(extension_filter(None, "movie.mp4"))

    def test_size_filter_applies_min_and_max_bounds_correctly(self):
        mb = 1024 * 1024
        self.assertTrue(size_filter(0, 10, 5 * mb))
        self.assertTrue(size_filter(10, 0, 15 * mb))
        self.assertTrue(size_filter(10, 5, 3 * mb))
        self.assertTrue(size_filter(10, 5, 11 * mb))
        self.assertFalse(size_filter(10, 5, 7 * mb))
        self.assertFalse(size_filter(0, 0, 7 * mb))

    def test_invalid_or_missing_size_is_not_treated_as_out_of_range(self):
        self.assertFalse(size_filter(10, 5, None))
        self.assertFalse(size_filter(10, 5, "not-a-size"))


if __name__ == "__main__":
    unittest.main()
