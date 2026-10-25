import unittest

from src.money import round_cents, split


class RoundCents(unittest.TestCase):
    def test_half_up(self):
        self.assertEqual(str(round_cents("2.675")), "2.68")


class Split(unittest.TestCase):
    def test_remainder_preserved(self):
        self.assertEqual(split(100, 3), [34, 33, 33])
        self.assertEqual(sum(split(100, 3)), 100)

    def test_even(self):
        self.assertEqual(split(90, 3), [30, 30, 30])
