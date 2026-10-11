import unittest

from textstats import word_count


class WordCountTests(unittest.TestCase):
    def test_counts_words(self):
        self.assertEqual(word_count("the quick brown fox"), 4)

    def test_empty(self):
        self.assertEqual(word_count(""), 0)

    def test_punctuation_and_apostrophes(self):
        self.assertEqual(word_count("Don't stop, believing!"), 3)


if __name__ == "__main__":
    unittest.main()
