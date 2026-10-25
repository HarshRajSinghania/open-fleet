import unittest

from src.slug import slugify


class Slugify(unittest.TestCase):
    def test_lowercases_and_hyphenates(self):
        self.assertEqual(slugify("Hello  World"), "hello-world")

    def test_transliterates_accents(self):
        self.assertEqual(slugify("Crème Brûlée"), "creme-brulee")
