"""Whole/fraction prefix storage and local cancellation."""
# ruff: noqa: PT009

import unittest
from decimal import Decimal

from sekai.lib.timescale_math import TimePosition
from tests.test_timescale_math import quantized32


class TimescaleNumericTests(unittest.TestCase):
    def test_negative_values_and_carry(self):
        value = TimePosition.of(-3.25)
        self.assertEqual((value.whole, value.fraction), (-3, -0.25))
        value = value.add(3.5)
        self.assertEqual((value.whole, value.fraction), (0, 0.25))
        for sign in (-1, 1):
            carried = TimePosition.of(sign * 3.75).add(sign * 0.5)
            self.assertEqual((carried.whole, carried.fraction), (sign * 4, sign * 0.25))

    def test_nearby_prefix_difference_keeps_small_fraction(self):
        earlier = TimePosition.of(1_000_000)
        step = quantized32(0.0001)
        later = earlier.add(step)
        self.assertEqual(later.difference(earlier), step)
        self.assertEqual(earlier.difference(later), -step)
        self.assertEqual(later.whole, 1_000_000)
        self.assertEqual(later.fraction, step)

    def test_practical_long_signed_history_and_reentry(self):
        value = TimePosition.of(0)
        exact = Decimal(0)
        local_step = quantized32(0.0001)
        for i in range(20_000):
            step = 49 if i % 2 == 0 else -49
            value = value.add(step)
            exact += Decimal(step)
            if i % 2000 == 1999:
                before = value
                value = value.add(local_step)
                exact += Decimal.from_float(local_step)
                self.assertAlmostEqual(value.difference(before), local_step, delta=1e-15)
                self.assertLess(abs(value.fraction), 1)
                self.assertEqual(value.whole % 1, 0)
        actual = Decimal(value.whole) + Decimal.from_float(value.fraction)
        self.assertLess(abs(actual - exact), Decimal("1e-14"))


if __name__ == "__main__":
    unittest.main()
