import unittest

from text.slug import slugify


class SlugifyTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_accents(self):
        self.assertEqual(slugify("Cr\u00e8me br\u00fbl\u00e9e"), "creme-brulee")

    def test_only_punctuation(self):
        self.assertEqual(slugify("  !!  "), "")

    def test_truncation_never_ends_with_dash(self):
        self.assertEqual(slugify("ab cd", max_length=3), "ab")
