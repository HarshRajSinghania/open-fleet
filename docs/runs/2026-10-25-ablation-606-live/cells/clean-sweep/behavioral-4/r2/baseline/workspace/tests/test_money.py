import unittest

from src.money import round_cents, split


class RoundCents(unittest.TestCase):
    def test_half_up(self):
        self.assertEqual(str(round_cents("2.675")), "2.68")


class Split(unittest.TestCase):
    def test_remainder_is_distributed(self):
        self.assertEqual(split(100, 3), [34, 33, 33])

    def test_sum_preserved(self):
        for total, parts in [(100, 3), (1, 5), (7, 7), (0, 4)]:
            self.assertEqual(sum(split(total, parts)), total)
