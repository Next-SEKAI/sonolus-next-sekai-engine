"""Native polynomial kernels against the independent Decimal oracle."""
# ruff: noqa: PT009

import unittest
from decimal import localcontext
from itertools import product

from sekai.lib.timescale_math import integrate_times, speed_at
from tests.timescale_reference import decimal, integrate_speed, speed_value
from tests.timescale_reference import quantized32 as quantized_decimal


def quantized32(value):
    return float(quantized_decimal(value))


class TimescaleLocalMathTests(unittest.TestCase):
    def test_all_easings_and_endpoint_directions(self):
        with localcontext() as context:
            context.prec = 80
            for ease, endpoints, u in product(
                range(6),
                ((0.05, 8), (8, 0.05), (-8, 8), (2, 2)),
                (0, 0.001, 0.25, 0.499, 0.5, 0.501, 0.999, 1),
            ):
                v0, v1 = map(quantized32, endpoints)
                u = quantized32(u)
                expected = speed_value(v0, v1, ease, u)
                self.assertAlmostEqual(speed_at(v0, v1, ease, 0, 1, u), float(expected), delta=2e-12)

    def test_integrals_split_midpoint_and_preserve_orientation(self):
        with localcontext() as context:
            context.prec = 80
            for ease, endpoints, bounds in product(
                range(6),
                ((0.05, 8), (8, 0.05), (-8, 8)),
                ((0, 2), (0.1, 0.9), (0.9, 1.1), (1.1, 1.9), (1.9, 0.1)),
            ):
                v0, v1 = map(quantized32, endpoints)
                left, right = map(quantized32, bounds)
                expected = integrate_speed(v0, v1, ease, 2, left, right)
                self.assertAlmostEqual(integrate_times(v0, v1, ease, 0, 2, left, right), float(expected), delta=2e-12)

    def test_short_intervals_late_in_song(self):
        with localcontext() as context:
            context.prec = 80
            a, b = quantized32(1799.99), quantized32(1800)
            left, right = quantized32(1799.9996), quantized32(1799.9998)
            for ease in range(6):
                last = quantized32(0.05)
                expected = integrate_speed(
                    8, last, ease, decimal(b) - decimal(a), decimal(left) - decimal(a), decimal(right) - decimal(a)
                )
                actual = integrate_times(8, last, ease, a, b, left, right)
                self.assertAlmostEqual(actual, float(expected), delta=2e-12)
                expected_speed = speed_value(8, last, ease, (decimal(left) - decimal(a)) / (decimal(b) - decimal(a)))
                self.assertAlmostEqual(speed_at(8, last, ease, a, b, left), float(expected_speed), delta=2e-12)

    def test_held_endpoint_and_zero_duration(self):
        self.assertEqual(speed_at(2, 100, 0, 0, 3, 3), 2)
        self.assertEqual(integrate_times(2, 100, 0, 0, 3, 0, 3), 6)
        for ease in range(6):
            self.assertEqual(integrate_times(0, 4, ease, 1, 1, 1, 1), 0)
            self.assertEqual(integrate_times(0, 4, ease, 0, 2, 1, 1), 0)


if __name__ == "__main__":
    unittest.main()
