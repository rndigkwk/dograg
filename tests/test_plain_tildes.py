"""src/ui.py plain_tildes: "~" in answers and reports is shown, not read as strikethrough."""

import unittest

from src.ui import plain_tildes


class PlainTildeTests(unittest.TestCase):
    def test_ranges_keep_their_tildes(self):
        text = "범위는 15,000~110,000원입니다. 초진은 5,000~50,000원입니다."
        self.assertEqual(plain_tildes(text), "범위는 15,000\~110,000원입니다. 초진은 5,000\~50,000원입니다.")

    def test_text_without_tildes_is_unchanged(self):
        self.assertEqual(plain_tildes("강남구 초진 11,000원"), "강남구 초진 11,000원")


if __name__ == "__main__":
    unittest.main()
