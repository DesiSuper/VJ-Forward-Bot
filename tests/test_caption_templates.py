import unittest

from plugins.settings import mongo_uri_summary, valid_size_range, validate_caption_template


class CaptionTemplateTests(unittest.TestCase):
    def test_accepts_documented_named_fields_and_escaped_braces(self):
        validate_caption_template("{filename} · {size} · {caption} {{archive}}")

    def test_rejects_unknown_and_positional_fields(self):
        for template in ("{title}", "{}", "{caption.__class__}"):
            with self.subTest(template=template):
                with self.assertRaises(ValueError):
                    validate_caption_template(template)

    def test_rejects_malformed_braces_and_format_modifiers(self):
        for template in ("{filename", "{size:>8}", "{caption!r}"):
            with self.subTest(template=template):
                with self.assertRaises(ValueError):
                    validate_caption_template(template)

    def test_size_bounds_allow_disabled_limits_but_reject_inverted_ranges(self):
        self.assertTrue(valid_size_range(0, 10))
        self.assertTrue(valid_size_range(10, 0))
        self.assertTrue(valid_size_range(10, 10))
        self.assertFalse(valid_size_range(11, 10))

    def test_mongo_uri_summary_masks_credentials_and_handles_malformed_saved_values(self):
        summary = mongo_uri_summary("mongodb://alice:secret@db.example:27017/app?authSource=admin")
        self.assertEqual(summary, "mongodb://db.example:27017/app")
        self.assertNotIn("alice", summary)
        self.assertNotIn("secret", summary)
        self.assertIn("needs correction", mongo_uri_summary("mongodb://bad:port/db"))


if __name__ == "__main__":
    unittest.main()
