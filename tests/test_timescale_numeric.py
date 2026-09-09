# ruff: noqa: PT009, PT027
"""Arithmetic certificates, signed cancellation and long positive histories."""

import random
import unittest
from decimal import Decimal, localcontext

from sonolus.script.archetype import PlayArchetype, entity_data, imported
from sonolus.script.internal.context import RuntimeChecks

from sekai.lib.timescale_math import (
    AccurateScalar,
    AffineTransfer,
    _normalize,
    certified_speed_at,
    native_affine_progress,
    native_difference_progress,
    native_scroll_progress,
    published_progress,
)
from tests.test_timescale_math import interval, quantized32
from tests.timescale_reference import decimal, speed_value
from tests.timescale_vm import compile_probe


class _ScalarAssertionProbe(PlayArchetype):
    value: float = imported()
    output: AccurateScalar = entity_data()
    completed: bool = entity_data()

    def preprocess(self):
        self.output = AccurateScalar.of(self.value)
        self.completed = True


class _ScalarNormalizationProbe(PlayArchetype):
    value: float = imported()
    output: AccurateScalar = entity_data()
    completed: bool = entity_data()

    def preprocess(self):
        self.output = _normalize(self.value, 0.0, 0, 0.0)
        self.completed = True


class TimescaleNumericTests(unittest.TestCase):
    def assert_encloses(self, value, expected):
        lower, upper = interval(value)
        self.assertLessEqual(lower, expected)
        self.assertGreaterEqual(upper, expected)

    def test_internal_assertions_strip_from_production_instructions(self):
        production = compile_probe(_ScalarAssertionProbe)
        unchecked = compile_probe(_ScalarNormalizationProbe)
        checked = compile_probe(_ScalarAssertionProbe, runtime_checks=RuntimeChecks.TERMINATE)
        self.assertEqual(production.node, unchecked.node)
        valid, production_vm = production.run(value=0.375)
        checked_valid, checked_vm = checked.run(value=0.375)
        self.assertEqual(valid, checked_valid)
        self.assertLess(production_vm.steps, checked_vm.steps)
        for value in (float("nan"), float("inf"), float("-inf")):
            result, _ = checked.run(value=value)
            self.assertEqual(result["completed"], (0.0,))
            with self.assertRaises(AssertionError):
                AccurateScalar.of(value)

    def test_seeded_operations_enclose_exact_quantized_inputs(self):
        randomizer = random.Random(72193)
        with localcontext() as context:
            context.prec = 100
            for _ in range(250):
                a = quantized32(randomizer.uniform(-8, 8))
                b = quantized32(randomizer.uniform(0.05, 8))
                left, right = AccurateScalar.of(a), AccurateScalar.of(b)
                for result, expected in (
                    (left.add(right), decimal(a) + decimal(b)),
                    (left.sub(right), decimal(a) - decimal(b)),
                    (left.mul(right), decimal(a) * decimal(b)),
                    (left.div(right), decimal(a) / decimal(b)),
                    (left.published_add(right), decimal(a) + decimal(b)),
                    (left.published_mul(right), decimal(a) * decimal(b)),
                    (left.published_div(right), decimal(a) / decimal(b)),
                ):
                    self.assert_encloses(result, expected)
                    self.assert_encloses(result.published(), expected)

    def test_signed_cancellation_preserves_a_certificate(self):
        with localcontext() as context:
            context.prec = 100
            total = AccurateScalar.of(1_000_000).add(AccurateScalar.of(0.00001))
            result = total.sub(AccurateScalar.of(1_000_000))
            self.assert_encloses(result, decimal(0.00001))
            self.assertTrue(result.definitely_greater(AccurateScalar.of(0)))
            self.assertTrue(result.error_at_most(1e-5))

    def test_exact_identities_do_not_accumulate_ratio_uncertainty(self):
        one = AccurateScalar.of(1)
        zero = AccurateScalar.of(0)
        value = AccurateScalar.of(quantized32(7.8)).div(AccurateScalar.of(3))
        for operation in (value.mul(one), one.mul(value), value.div(one)):
            self.assertEqual(
                (operation.hi, operation.lo, operation.exponent, operation.error),
                (value.hi, value.lo, value.exponent, value.error),
            )
        self.assertEqual(one.mul(one).error, 0)
        self.assertEqual(zero.mul(value).error, 0)
        self.assertEqual(value.mul(one.neg()).to_float(), -value.to_float())
        transfer = AffineTransfer.identity()
        for _ in range(100):
            transfer = transfer.then(AffineTransfer(one, one))
        self.assertEqual(transfer.ratio.error, 0)

    def test_direct_difference_and_varied_bpm_division_certificates(self):
        with localcontext() as context:
            context.prec = 100
            a, b = quantized32(1800.0), quantized32(1800.001)
            difference = AccurateScalar.difference(b, a)
            self.assertEqual(difference.error, 0)
            self.assert_encloses(difference, decimal(b) - decimal(a))
            numerator = AccurateScalar.of(49).scale(60)
            self.assertEqual(numerator.error, 0)
            for bpm in (30, 50, 60, 75, 120, 137, 180, 240):
                quotient = numerator.div(AccurateScalar.of(bpm))
                self.assert_encloses(quotient, Decimal(49 * 60) / Decimal(bpm))
                if bpm in (30, 60, 120, 240):
                    self.assertEqual(quotient.error, 0)

    def test_exact_power_two_scaling_preserves_significands_and_certificates(self):
        value = AccurateScalar.of(quantized32(0.7)).div(AccurateScalar.of(3))
        for exponent in (-10000, -30, -1, 0, 1, 30, 10000):
            for sign in (-1, 1):
                power = AccurateScalar(sign * 0.5, 0.0, exponent + 1, 0.0)
                multiplied = value.mul(power)
                divided = value.div(power)
                for result, shift in ((multiplied, exponent), (divided, -exponent)):
                    self.assertEqual(result.hi, sign * value.hi)
                    self.assertEqual(result.lo, sign * value.lo)
                    self.assertEqual(result.error, value.error)
                    self.assertEqual(result.exponent, value.exponent + shift)
                recovered = multiplied.div(power)
                self.assertEqual(recovered.hi, value.hi)
                self.assertEqual(recovered.lo, value.lo)
                self.assertEqual(recovered.error, value.error)
                self.assertEqual(recovered.exponent, value.exponent)

    def test_native_affine_progress_encloses_future_and_past(self):
        randomizer = random.Random(38961)
        with localcontext() as context:
            context.prec = 100
            preempt = quantized32(0.0035)
            for _ in range(100):
                raw_value = quantized32(randomizer.uniform(-2, 2))
                raw_ratio = quantized32(randomizer.uniform(0.05, 8))
                raw_distance = quantized32(randomizer.uniform(-2, 2))
                offset = quantized32(randomizer.uniform(-0.5, 0.5))
                value = AccurateScalar.of(raw_value).div(AccurateScalar.of(3))
                ratio = AccurateScalar.of(raw_ratio).div(AccurateScalar.of(7))
                distance = AccurateScalar.of(raw_distance)
                exact_value, exact_ratio = decimal(raw_value) / 3, decimal(raw_ratio) / 7
                for past in (False, True):
                    result = native_affine_progress(value, ratio, distance, preempt, offset, past)
                    trajectory = (
                        -(exact_value + decimal(raw_distance)) / exact_ratio
                        if past else exact_ratio * exact_value + decimal(raw_distance)
                    )
                    expected = 1 - trajectory / decimal(preempt) - decimal(offset)
                    self.assertLessEqual(decimal(result.value) - decimal(result.error), expected)
                    self.assertGreaterEqual(decimal(result.value) + decimal(result.error), expected)
            uncertain = AccurateScalar(0.5, 0.0, 1, 0.5)
            result = native_affine_progress(AccurateScalar.of(1), uncertain, AccurateScalar.of(1), 1, past=True)
            self.assertEqual(result.error, float("inf"))

    def test_native_scroll_progress_uses_current_speed_across_target_markers(self):
        with localcontext() as context:
            context.prec = 100
            first, last = quantized32(8), quantized32(0.05)
            start, end = quantized32(1800), quantized32(1801)
            preempt, offset = quantized32(0.0035), quantized32(0.2)
            for ease in range(6):
                for now in (start, quantized32(1800.1), quantized32(1800.5), quantized32(1800.9), end):
                    speed = certified_speed_at(first, last, ease, start, end, now)
                    u = (decimal(now) - decimal(start)) / (decimal(end) - decimal(start))
                    exact_speed = speed_value(first, last, ease, u)
                    for hit in (quantized32(now - 0.0002), now, quantized32(now + 0.0002), quantized32(1802)):
                        result = native_scroll_progress(hit, now, speed, preempt, offset)
                        expected = 1 - exact_speed * (decimal(hit) - decimal(now)) / decimal(preempt) - decimal(offset)
                        self.assertLessEqual(decimal(result.value) - decimal(result.error), expected)
                        self.assertGreaterEqual(decimal(result.value) + decimal(result.error), expected)
                        if abs(hit - now) < 0.001:
                            self.assertLessEqual(result.error, 1e-4)
            outside = native_scroll_progress(2.0**31, 0, AccurateScalar.of(1), 1)
            self.assertEqual(outside.error, float("inf"))

    def test_native_prefix_difference_resolves_small_visible_cancellation(self):
        with localcontext() as context:
            context.prec = 100
            current = AccurateScalar.of(1_000_000)
            for distance in (-0.001, 0.0, 0.001):
                target = current.add(AccurateScalar.of(distance))
                result = native_difference_progress(target, current, 0.0035)
                expected = 1 - decimal(distance) / decimal(0.0035)
                self.assertLessEqual(decimal(result.value) - decimal(result.error), expected)
                self.assertGreaterEqual(decimal(result.value) + decimal(result.error), expected)
                self.assertLessEqual(result.error, 1e-4)


    def test_huge_true_range_and_ordinary_quotient(self):
        value = AccurateScalar.of(1)
        factor = AccurateScalar.of(2)
        for _ in range(10_000):
            value = value.mul(factor)
        self.assertEqual(value.exponent, 10_001)
        self.assertEqual(value.hi, 0.5)
        with self.assertRaises(AssertionError):
            value.to_float()
        with localcontext() as context:
            context.prec = 100
            self.assert_encloses(value.div(value), Decimal(1))
        self.assertTrue(value.definitely_greater(AccurateScalar.of(1e30)))

    def test_omitted_tiny_terms_are_never_declared_exact(self):
        tiny = AccurateScalar(0.5, 0.0, -10_000, 0.0)
        value = AccurateScalar.of(1).add(tiny)
        self.assertGreater(value.error, 0)
        with localcontext() as context:
            context.prec = 100
            difference = value.sub(AccurateScalar.of(1))
            self.assert_encloses(difference, Decimal(2) ** -10_001)
        self.assertFalse(difference.definitely_less(AccurateScalar.of(0)))

    def test_twenty_thousand_nondyadic_links_and_published_query(self):
        # S1->q,Tq->q,Sq->1,T1->1: each full cycle has R=1,B=4.
        one = AccurateScalar.of(1)
        high = AccurateScalar.of(quantized32(7.8))
        pattern = (
            AffineTransfer(one.div(high), one),
            AffineTransfer(one, high),
            AffineTransfer(high, high),
            AffineTransfer(one, one),
        )
        nodes = list(pattern) * 5000
        while len(nodes) > 1:
            nodes = [
                nodes[index].then(nodes[index + 1]) if index + 1 < len(nodes) else nodes[index]
                for index in range(0, len(nodes), 2)
            ]
        result = nodes[0]
        with localcontext() as context:
            context.prec = 100
            self.assert_encloses(result.ratio, Decimal(1))
            self.assert_encloses(result.distance, Decimal(20_000))
            self.assert_encloses(result.published_apply(AccurateScalar.of(0)), Decimal(20_000))
        self.assertLess(abs(result.ratio.to_float() - 1), 1e-10)
        self.assertLess(result.ratio.error, 1e-7)

    def test_error_budget_checks_across_exponents(self):
        for exponent in (-10_000, -100, -10, 0, 10, 100, 10_000):
            value = AccurateScalar(0.5, 0.0, exponent, 2.0**-40)
            with localcontext() as context:
                context.prec = 100
                radius = Decimal(2) ** (exponent - 40)
                for tolerance in (0.0, 1e-10, 1e-4, 1.0, 1e30):
                    self.assertEqual(value.error_at_most(tolerance), radius <= decimal(tolerance))

    def test_hull_contains_signed_endpoints_across_enormous_ranges(self):
        with localcontext() as context:
            context.prec = 100
            for a, b in (
                (AccurateScalar.of(-2), AccurateScalar.of(3)),
                (AccurateScalar(0.75, 0, 10_000, 1e-8), AccurateScalar(-0.5, 0, 10_000, 2e-8)),
                (AccurateScalar(0.5, 0, 10_000, 0), AccurateScalar(0.5, 0, -10_000, 0)),
            ):
                result = a.hull(b)
                for endpoint in (*interval(a), *interval(b)):
                    self.assert_encloses(result, endpoint)

    def test_fused_progress_encloses_both_uncertain_distance_endpoints(self):
        with localcontext() as context:
            context.prec = 100
            for preempt in (0.0035, 0.35, 8.0):
                for offset in (0.0, 0.75, -2.0):
                    for exponent in (-10, 0, 10, 10_000):
                        value = AccurateScalar(0.75, 0.0, exponent, 1e-8)
                        result = published_progress(value, preempt, offset)
                        for endpoint in interval(value):
                            self.assert_encloses(result, Decimal(1) - endpoint / decimal(preempt) - decimal(offset))

    def test_uncertain_divisor_is_rejected(self):
        with self.assertRaises(AssertionError):
            AccurateScalar.of(1).div(AccurateScalar(0.5, 0, 0, 0.5))
        with self.assertRaises(AssertionError):
            AccurateScalar.of(1).published_div(AccurateScalar.of(0))


if __name__ == "__main__":
    unittest.main()
