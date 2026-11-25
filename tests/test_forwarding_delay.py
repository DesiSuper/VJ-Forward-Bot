import unittest

from forwarding_delay import choose_random_gap, normalize_random_gap


class ForwardingDelayTests(unittest.TestCase):
    def test_disabled_and_legacy_values_normalize_to_zero(self):
        self.assertEqual(normalize_random_gap(None), (0, 0))
        self.assertEqual(normalize_random_gap({"min": "bad", "max": 4}), (0, 0))
        self.assertEqual(normalize_random_gap({"min": 9, "max": 3}), (0, 0))
        self.assertEqual(normalize_random_gap({"min": 0, "max": 3601}), (0, 0))

    def test_configured_range_is_normalized_and_randomized(self):
        gap = normalize_random_gap({"min": "2", "max": "6"})
        self.assertEqual(gap, (2, 6))
        for _ in range(100):
            self.assertIn(choose_random_gap(gap), range(2, 7))

    def test_fixed_gap_and_legacy_default(self):
        self.assertEqual(choose_random_gap((8, 8)), 8)
        self.assertEqual(choose_random_gap((0, 0), default_delay=2), 2)
        self.assertEqual(choose_random_gap((0, 0)), 0)


if __name__ == "__main__":
    unittest.main()
