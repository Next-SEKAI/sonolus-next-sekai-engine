# ruff: noqa: PT009, PT027
"""Semantic golden cases for the independent Decimal timescale oracle."""

import unittest
from decimal import Decimal, localcontext
from fractions import Fraction

from tests.timescale_reference import (
    RefEase,
    RefMarker,
    RefStyle,
    RefTimeline,
    compose,
    endpoint_log_markers,
    huge_exponent_markers,
    integrate_speed,
    non_dyadic_markers,
    quantized32,
    reciprocal_markers,
    speed_value,
    visibility_island_markers,
)


class TimescaleReferenceTests(unittest.TestCase):
    def assert_decimal_close(self, actual, expected, tolerance="1e-85"):
        with localcontext() as context:
            context.prec = 100
            expected = Decimal(expected)
            self.assertLessEqual(abs(actual - expected), Decimal(tolerance) * max(1, abs(expected)))

    def test_exact_easing_averages_and_signed_integrals(self):
        averages = (Fraction(0), Fraction(1, 2), Fraction(1, 3), Fraction(2, 3), Fraction(1, 2), Fraction(1, 2))
        with localcontext() as context:
            context.prec = 100
            for ease, average in enumerate(averages):
                with self.subTest(ease=ease):
                    expected = -2 + 6 * average
                    integral = integrate_speed(-2, 4, ease, 1)
                    self.assert_decimal_close(integral, Decimal(expected.numerator) / expected.denominator)
                    self.assert_decimal_close(integrate_speed(-2, 4, ease, 1, 1, 0), -integral)

    def test_short_late_interval_uses_local_width(self):
        timeline = RefTimeline([RefMarker("1800", "0.05", RefEase.IN_QUAD), RefMarker("1801", 8)])
        time, width = Decimal("1800.5"), Decimal("1e-40")
        with localcontext() as context:
            context.prec = 100
            distance = timeline.distance(time, time + width)
            expected = width * (
                Decimal("0.05") + Decimal("7.95") * (Decimal("0.25") + Decimal("0.5") * width + width * width / 3)
            )
            self.assert_decimal_close(distance / width, expected / width)

    def test_identity_prelude_first_skip_and_final_tail(self):
        self.assertEqual(RefTimeline().distance(-20, 30), 50)
        timeline = RefTimeline([RefMarker(1, 2, skip=3), RefMarker(2, 4, skip=-1)])
        self.assertEqual(timeline.distance(-1, 1), 5)
        self.assertEqual(timeline.distance(1, 2), 1)
        self.assertEqual(timeline.distance(2, 3), 4)
        self.assertEqual(timeline.distance(1, 1), 0)
        self.assertEqual(timeline.distance(3, -1), -10)

    def test_same_time_raw_anchor_ownership_and_completed_right_state(self):
        timeline = RefTimeline(
            [RefMarker(0, 1), RefMarker(1, 2, style=RefStyle.SCROLL, hide=True), RefMarker(1, 1, hide=False)]
        )
        self.assertEqual(timeline.anchor_transfer(0, 1), (1, 1))
        self.assertEqual(timeline.anchor_transfer(1, 2), (2, 0))
        self.assertEqual(timeline.transfer(0, 1), (2, 1))
        self.assertEqual(timeline.locate_time(1), 2)
        self.assertFalse(timeline.hidden(1))
        self.assertEqual(timeline.distance(0, 2), 3)
        self.assertEqual(timeline.distance(2, 0), Decimal("-1.5"))
        self.assertEqual(timeline.distance(1, 1), 0)

    def test_multiple_same_time_signed_skips_and_zero_crossing(self):
        timeline = RefTimeline(
            [
                RefMarker(0, -2, RefEase.LINEAR, skip=5),
                RefMarker(1, 2, skip=3),
                RefMarker(1, 0, skip=-4),
                RefMarker(2, -1),
            ]
        )
        self.assertEqual(timeline.distance(0, 1), -1)
        self.assertEqual(timeline.distance(1, 2), 0)
        self.assertEqual(timeline.speed(Decimal("0.5")), 0)
        self.assertEqual(timeline.distance(-1, 0), 6)

    def test_hold_steps_and_no_speed_change_style_switch(self):
        scroll = RefTimeline([RefMarker(0, 2, style=RefStyle.SCROLL), RefMarker(1, 1)])
        timescale = RefTimeline([RefMarker(0, 2), RefMarker(1, 1)])
        self.assertEqual(scroll.distance(Decimal("0.5"), 2), 3)
        self.assertEqual(timescale.distance(Decimal("0.5"), 2), 2)
        unchanged = RefTimeline([RefMarker(0, 2, style=RefStyle.SCROLL), RefMarker(1, 2), RefMarker(2, 2)])
        self.assertEqual(unchanged.distance(0, 3), 6)

    def test_atomic_composition_is_not_commutative(self):
        self.assertEqual(compose((Decimal(2), Decimal(3)), (Decimal(5), Decimal(7))), (10, 17))
        self.assertEqual(compose((Decimal(5), Decimal(7)), (Decimal(2), Decimal(3))), (10, 22))

    def test_pure_scroll_orientation_uses_current_speed(self):
        timeline = RefTimeline([RefMarker(0, 1, RefEase.LINEAR, RefStyle.SCROLL), RefMarker(1, 3)])
        self.assertEqual(timeline.distance(0, 1), 1)
        self.assertEqual(timeline.distance(1, 0), -3)
        self.assertEqual(timeline.distance(Decimal("0.5"), 1), 1)

    def test_pure_scroll_visibility_island(self):
        timeline = RefTimeline(visibility_island_markers())
        self.assertEqual(timeline.distance(0, 3), 6)
        self.assertEqual(timeline.distance(2, 3), 2)
        with localcontext() as context:
            context.prec = 100
            self.assert_decimal_close(timeline.distance(Decimal(4) / 3, 3), Decimal(50) / 27)

    def test_validation_covers_final_markers_and_chronological_order(self):
        invalid = (
            [RefMarker(0, 0), RefMarker(1, 1, style=RefStyle.SCROLL)],
            [RefMarker(0, 1, skip=1), RefMarker(1, 1, style=RefStyle.SCROLL)],
            [RefMarker(1, 1), RefMarker(0, 1)],
            [RefMarker(0, "NaN")],
            [RefMarker(0, 1, ease=6)],
            [RefMarker(0, 1, style=2)],
        )
        for markers in invalid:
            with self.subTest(markers=markers), self.assertRaises(ValueError):
                RefTimeline(markers)

    def test_quantized_input_is_separate_from_authored_decimal(self):
        self.assertNotEqual(quantized32("7.8"), Decimal("7.8"))
        self.assertEqual(RefMarker(0, 0.1).speed, Decimal.from_float(0.1))
        self.assertEqual(speed_value(8, "0.05", RefEase.OUT_QUAD, 1), Decimal("0.05"))

    def test_twenty_thousand_reciprocal_links(self):
        markers = reciprocal_markers(quantize=True)
        self.assertEqual(len(markers), 20001)
        timeline = RefTimeline(markers)
        with localcontext() as context:
            context.prec = 100
            expected = Decimal(250) * (3 + 1 / quantized32("7.8"))
            ratio, distance = timeline.anchor_transfer(0, 20000)
            self.assert_decimal_close(ratio, 1)
            self.assert_decimal_close(distance, expected)
            self.assertEqual(timeline.distance(1000, 1001), 1)

    def test_twenty_thousand_endpoint_log_identity_links(self):
        timeline = RefTimeline(endpoint_log_markers())
        ratio, _ = timeline.anchor_transfer(0, 20000)
        self.assert_decimal_close(ratio, 1)

    def test_twenty_thousand_huge_exponent_links_and_local_queries(self):
        for shrinking in (False, True):
            with self.subTest(shrinking=shrinking), localcontext() as context:
                context.prec = 100
                timeline = RefTimeline(huge_exponent_markers(shrinking=shrinking))
                ratio, distance = timeline.anchor_transfer(0, 20000)
                expected_ratio = Decimal(2) ** (-10000 if shrinking else 10000)
                self.assert_decimal_close(ratio / expected_ratio, 1)
                expected_distance = Decimal("0.175") * (1 - expected_ratio if shrinking else expected_ratio - 1)
                self.assert_decimal_close(distance / expected_distance, 1)
                self.assertEqual(timeline.distance(1000, 1001), 1)

    def test_non_dyadic_stress_has_both_styles_all_eases_and_positive_transfers(self):
        markers = non_dyadic_markers()
        self.assertEqual(len(markers), 20001)
        self.assertEqual({marker.ease for marker in markers}, set(range(6)))
        self.assertEqual({marker.style for marker in markers}, {0, 1})
        timeline = RefTimeline(markers)
        ratio, integral = timeline.anchor_transfer(0, 20000)
        self.assertGreater(ratio, 0)
        self.assertGreater(integral, 0)


if __name__ == "__main__":
    unittest.main()
