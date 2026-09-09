# ruff: noqa: PT009
"""Independent polynomial and boundary contracts for the local math module."""

import unittest
from decimal import Decimal, localcontext
from itertools import product

from sekai.lib.timescale_math import (
    AccurateScalar,
    AffineTransfer,
    certified_integrate_times,
    certified_speed_at,
    clamped_fraction,
    midpoint_parts,
    native_constant_progress,
    polynomial_piece_integral,
)
from tests.timescale_reference import decimal, integrate_speed, speed_value
from tests.timescale_reference import quantized32 as quantized_decimal


def quantized32(value):
    return float(quantized_decimal(value))


def interval(value):
    factor = Decimal(2) ** int(value.exponent)
    center = (decimal(float(value.hi)) + decimal(float(value.lo))) * factor
    radius = decimal(float(value.error)) * factor
    return center - radius, center + radius


class TimescaleLocalMathTests(unittest.TestCase):
    def assert_encloses(self, value, expected):
        lower, upper = interval(value)
        self.assertLessEqual(lower, expected)
        self.assertGreaterEqual(upper, expected)

    def test_all_easings_match_independent_polynomials(self):
        with localcontext() as context:
            context.prec = 100
            for ease, endpoints, u in product(
                range(6),
                ((0.05, 8.0), (8.0, 0.05), (2.0, 2.0), (-3.0, 5.0), (-8.0, -0.05), (0.0, 0.0), (1.0, 1.0 + 2**-23)),
                (0.0, 0.001, 0.25, 0.499, 0.5, 0.501, 0.75, 0.999, 1.0),
            ):
                v0, v1 = (quantized32(v) for v in endpoints)
                u = quantized32(u)
                with self.subTest(ease=ease, endpoints=endpoints, u=u):
                    expected = speed_value(v0, v1, ease, u)
                    result = certified_speed_at(v0, v1, ease, 0.0, 1.0, u)
                    self.assertAlmostEqual(result.to_float(), float(expected), delta=2e-14)
                    self.assert_encloses(result, expected)

    def test_exact_integrals_with_midpoint_and_reversed_ranges(self):
        with localcontext() as context:
            context.prec = 100
            for ease, endpoints, bounds in product(
                range(6),
                ((0.05, 8.0), (8.0, 0.05), (-8.0, 8.0)),
                ((0.0, 2.0), (0.1, 0.9), (0.9, 1.1), (1.1, 1.9), (1.9, 0.1)),
            ):
                v0, v1 = (quantized32(v) for v in endpoints)
                left, right = (quantized32(v) for v in bounds)
                with self.subTest(ease=ease, endpoints=endpoints, bounds=bounds):
                    expected = integrate_speed(v0, v1, ease, 2.0, left, right)
                    result = certified_integrate_times(v0, v1, ease, 0.0, 2.0, left, right)
                    self.assertAlmostEqual(result.to_float(), float(expected), delta=1e-13)
                    self.assert_encloses(result, expected)

    def test_none_and_zero_duration_do_not_use_destination_in_integral(self):
        self.assertEqual(certified_speed_at(2.0, 100.0, 0, 7.0, 8.0, 8.0).to_float(), 2.0)
        self.assertEqual(certified_integrate_times(2.0, 100.0, 0, 7.0, 10.0, 7.0, 10.0).to_float(), 6.0)
        for ease in range(6):
            self.assertEqual(certified_integrate_times(0.0, 4.0, ease, 7.0, 7.0, 7.0, 7.0).to_float(), 0.0)

    def test_late_song_tiny_interval_uses_identical_quantized_times(self):
        with localcontext() as context:
            context.prec = 100
            a, b = quantized32(1799.99), quantized32(1800.0)
            left, right = quantized32(1799.9996), quantized32(1799.9998)
            for ease in range(6):
                expected = integrate_speed(
                    8.0,
                    quantized32(0.05),
                    ease,
                    decimal(b) - decimal(a),
                    decimal(left) - decimal(a),
                    decimal(right) - decimal(a),
                )
                self.assert_encloses(
                    certified_integrate_times(8.0, quantized32(0.05), ease, a, b, left, right), expected
                )
                expected_speed = speed_value(
                    8.0, quantized32(0.05), ease, (decimal(left) - decimal(a)) / (decimal(b) - decimal(a))
                )
                self.assert_encloses(certified_speed_at(8.0, quantized32(0.05), ease, a, b, left), expected_speed)

    def test_clamped_fraction_preserves_fallback_and_uncertainty(self):
        for accurate in (False, True):
            for x, expected in ((-2.0, 0.0), (0.25, 0.25), (2.0, 1.0)):
                result = clamped_fraction(
                    AccurateScalar.of(0), AccurateScalar.of(1), AccurateScalar.of(x), accurate=accurate
                )
                self.assert_encloses(result, decimal(expected))
            fallback = clamped_fraction(AccurateScalar.of(1), AccurateScalar.of(1), AccurateScalar.of(0), 0.5, accurate)
            self.assertEqual(fallback.to_float(), 0.5)
            uncertain = AccurateScalar(0.5, 0, 0, 1e-7)
            result = clamped_fraction(AccurateScalar.of(0), AccurateScalar.of(1), uncertain, accurate=accurate)
            self.assert_encloses(result, decimal(0.5) - decimal(1e-7))
            self.assert_encloses(result, decimal(0.5) + decimal(1e-7))

    def test_clamped_fraction_uncertainty_crosses_epsilon_branch(self):
        # Valid values of b-a lie on both sides of the 1e-6 fallback threshold.
        # At x=b, the ordinary branch returns one while the fallback is one half.
        start = AccurateScalar(1 - 0.9e-6, 0, 0, 0.2e-6)
        end = AccurateScalar.of(1)
        for accurate in (False, True):
            with self.subTest(accurate=accurate):
                result = clamped_fraction(start, end, end, accurate=accurate)
                self.assert_encloses(result, decimal(0.5))
                self.assert_encloses(result, decimal(1))

    def test_accurate_nested_fraction_resolves_near_tail_epsilon_branches(self):
        for gap, expected in ((2**-20, 0.5), (17 * 2**-24, 1.0)):
            with self.subTest(gap=gap):
                near_tail = AccurateScalar(1 - gap, 0, 0, 2**-70)
                refined = clamped_fraction(AccurateScalar.of(0), AccurateScalar.of(1), near_tail, accurate=True)
                result = clamped_fraction(refined, AccurateScalar.of(1), AccurateScalar.of(1), accurate=True)
                self.assert_encloses(result, decimal(expected))
                self.assertTrue(result.error_at_most(1e-9))

    def test_unrepresentable_midpoint_survives_two_stored_components(self):
        a, b = 1800.0, 1800.0001220703125
        midpoint = midpoint_parts(a, b)
        self.assertEqual(decimal(midpoint.hi) + decimal(midpoint.lo), (decimal(a) + decimal(b)) / 2)
        self.assertEqual(quantized32(midpoint.hi), midpoint.hi)
        self.assertEqual(quantized32(midpoint.lo), midpoint.lo)

    def test_native_constant_progress_certificate(self):
        with localcontext() as context:
            context.prec = 100
            for hit, now, velocity, preempt, offset in (
                (1800.0, 1799.999, 8.0, 0.0035, 0.0),
                (4.0, 5.0, -3.0, 0.35, -2.0),
                (1.0, 0.99999, 1.0, 0.35, 0.75),
            ):
                h, t, v, p, o = map(quantized32, (hit, now, velocity, preempt, offset))
                result = native_constant_progress(h, t, v, p, o)
                expected = 1 - (decimal(h) - decimal(t)) * decimal(v) / decimal(p) - decimal(o)
                self.assertLessEqual(decimal(result.value) - decimal(result.error), expected)
                self.assertGreaterEqual(decimal(result.value) + decimal(result.error), expected)

    def test_quadratic_endpoint_integral_matches_analytic_moment(self):
        with localcontext() as context:
            context.prec = 100
            for first, last, curvature, width in ((1, 2, 5, 0.5), (-8, 8, -3, 2), (0.05, 0.05, 8e6, 0.0001)):
                first, last, curvature, width = map(quantized32, (first, last, curvature, width))
                expected = decimal(width) * (
                    (decimal(first) + decimal(last)) / 2 - decimal(curvature) * decimal(width) ** 2 / 6
                )
                result = polynomial_piece_integral(
                    AccurateScalar.of(first),
                    AccurateScalar.of(last),
                    AccurateScalar.of(curvature),
                    AccurateScalar.of(width),
                )
                self.assert_encloses(result, expected)

    def test_authored_partial_quadratic_pieces_match_independent_integrals(self):
        with localcontext() as context:
            context.prec = 100
            for ease, endpoints, duration in product(range(1, 6), ((0.05, 8), (8, 0.05), (-8, 8)), (4.0, 0.001)):
                v0, v1, duration = map(quantized32, (*endpoints, duration))
                pieces = ((0.0, duration),) if ease < 4 else ((0.0, duration / 2), (duration / 2, duration))
                for piece_index, (a, b) in enumerate(pieces):
                    with self.subTest(ease=ease, endpoints=endpoints, duration=duration, piece=piece_index):
                        left, right = a + (b - a) / 4, a + 7 * (b - a) / 8
                        factor = (0, 0, 1, -1, 2, -2)[ease]
                        if ease >= 4 and piece_index == 1:
                            factor = -factor
                        curvature = (
                            AccurateScalar.of(v1)
                            .sub(AccurateScalar.of(v0))
                            .scale(factor)
                            .div(AccurateScalar.of(duration).mul(AccurateScalar.of(duration)))
                        )
                        result = polynomial_piece_integral(
                            certified_speed_at(v0, v1, ease, 0.0, duration, left),
                            certified_speed_at(v0, v1, ease, 0.0, duration, right),
                            curvature,
                            AccurateScalar.difference(right, left),
                        )
                        expected = integrate_speed(v0, v1, ease, duration, left, right)
                        self.assert_encloses(result, expected)
                        self.assertAlmostEqual(result.to_float(), float(expected), delta=1e-12)

    def test_ordered_same_time_anchor_and_past_orientation(self):
        # Incoming timescale hold -> speed2; a same-time scroll -> speed1.
        timescale = AffineTransfer(AccurateScalar.of(1), AccurateScalar.of(1))
        scroll_step = AffineTransfer(AccurateScalar.of(2), AccurateScalar.of(0))
        completed = timescale.then(scroll_step)
        self.assertEqual(completed.ratio.to_float(), 2)
        self.assertEqual(completed.distance.to_float(), 1)
        self.assertEqual(completed.apply(AccurateScalar.of(3)).to_float(), 7)
        self.assertEqual(scroll_step.then(timescale).distance.to_float(), 2)
        # Post-hit distance uses -B/R and is not -B.
        self.assertEqual(completed.distance.div(completed.ratio).neg().to_float(), -0.5)

    def test_scroll_run_telescopes_without_erasing_internal_easing(self):
        times = (0.0, 0.25, 0.75, 1.0)
        speeds = (1.0, 7.8, 0.05, 2.0)
        transfer = AffineTransfer.identity()
        for index in range(3):
            link = AffineTransfer(
                AccurateScalar.of(speeds[index]).div(AccurateScalar.of(speeds[index + 1])),
                AccurateScalar.of(speeds[index]).scale(times[index + 1] - times[index]),
            )
            transfer = transfer.then(link)
        self.assertAlmostEqual(transfer.ratio.to_float(), 0.5)
        self.assertAlmostEqual(transfer.distance.to_float(), 1.0)


if __name__ == "__main__":
    unittest.main()
