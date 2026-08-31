import unittest

from calculator import add


class CalculatorTests(unittest.TestCase):
    def test_adds_two_integers(self) -> None:
        self.assertEqual(add(20, 22), 42)


if __name__ == "__main__":
    unittest.main()

