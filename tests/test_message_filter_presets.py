import unittest

from message_filter_presets import MESSAGE_TYPES, filters_for_preset


class MessageFilterPresetTests(unittest.TestCase):
    def test_all_types_preset_enables_every_message_type(self):
        self.assertEqual(filters_for_preset("all"), dict.fromkeys(MESSAGE_TYPES, True))

    def test_individual_preset_disables_everything_except_selected_type(self):
        for preset, selected in (("video", "video"), ("photo", "photo"), ("audio", "audio")):
            with self.subTest(preset=preset):
                result = filters_for_preset(preset)
                self.assertEqual({name for name, enabled in result.items() if enabled}, {selected})

    def test_video_photo_audio_preset_enables_exactly_those_types(self):
        result = filters_for_preset("video_photo_audio")
        self.assertEqual(
            {name for name, enabled in result.items() if enabled},
            {"video", "photo", "audio"},
        )

    def test_removed_message_types_are_not_available_in_presets(self):
        self.assertFalse({"voice", "animation", "sticker", "poll"} & set(MESSAGE_TYPES))

    def test_media_preset_excludes_text(self):
        result = filters_for_preset("media")
        self.assertFalse(result["text"])
        self.assertTrue(result["document"])
        self.assertTrue(result["video"])
        self.assertTrue(result["photo"])
        self.assertTrue(result["audio"])
        self.assertTrue(result["video_note"])

    def test_unknown_preset_is_rejected(self):
        with self.assertRaises(ValueError):
            filters_for_preset("unknown")


if __name__ == "__main__":
    unittest.main()
