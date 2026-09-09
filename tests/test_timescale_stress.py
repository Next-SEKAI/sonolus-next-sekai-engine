# ruff: noqa: PT009
"""Practical production timeline/certificate regressions using Python proxies.

These deliberately preprocess 20,000 original markers. Reported wall times and
tree-query counts measure Python Record/proxy execution, not Sonolus clients.
Inputs and query clocks are quantized to binary32 before the independent oracle
sees them. The actual arithmetic in this harness is Python's native arithmetic;
production error radii must nevertheless enclose the reference and meet budget.
"""

import unittest
from decimal import Decimal, localcontext
from itertools import pairwise
from time import perf_counter
from unittest.mock import patch

from sekai.lib import timescale as ts
from sekai.lib.timescale_math import AccurateScalar, native_difference_progress
from tests.test_timescale_timeline import TimelineFixture
from tests.timescale_reference import (
    RefMarker,
    RefTimeline,
    huge_exponent_markers,
    non_dyadic_markers,
    quantized32,
    reciprocal_markers,
)

MARKER_COUNT = 20000
CHART_SECONDS = 1800
MIN_PREEMPT = float(quantized32("0.0035"))
CLOCK_STEP = 2.0**-13
PROGRESS_BUDGET = Decimal("1e-4")


def practical_markers(source):
    """Fit exactly 20k original markers into 30 minutes at quantized input times."""
    return [
        RefMarker(
            quantized32(CHART_SECONDS * i / (MARKER_COUNT - 1)),
            quantized32(marker.speed),
            marker.ease,
            marker.style,
            quantized32(marker.skip),
            marker.hide,
        )
        for i, marker in enumerate(source[:MARKER_COUNT])
    ]


def signed_variation_markers():
    """980,000 skip variation + 7,200 integral variation = 987,200 total.

    Paired +49/-49 skips cancel at completed timestamp states. Speeds alternate
    between -8 and +8 through linear ramps, keeping near-boundary queries visible
    while making the accurate signed prefix/suffix machinery handle the history.
    """
    pairs = MARKER_COUNT // 2
    result = []
    for i in range(pairs):
        time = quantized32(CHART_SECONDS * i / (pairs - 1))
        speed = 8 if i % 2 == 0 else -8
        result.extend((RefMarker(time, speed, ease=1, skip=49), RefMarker(time, speed, ease=1, skip=-49)))
    return result


def scalar_interval(value):
    """Read all four production fields without materializing a huge float."""
    scale = Decimal(2) ** int(value.exponent)
    center = (Decimal.from_float(float(value.hi)) + Decimal.from_float(float(value.lo))) * scale
    radius = Decimal.from_float(float(value.error)) * scale
    return center, radius


class TimescaleStressTests(unittest.TestCase):
    def assert_encloses(self, value, expected, description):
        with localcontext() as context:
            # Exact power-of-two production results may correctly have radius
            # zero. Materialize their dyadic Decimal centers exactly instead of
            # introducing a 100-digit oracle-rounding error into the comparison.
            context.prec = max(100, abs(int(value.exponent)) + 128)
            center, radius = scalar_interval(value)
            self.assertGreaterEqual(radius, 0, description)
            self.assertLessEqual(abs(center - expected), radius, f"{description}: oracle outside certificate")
            return center, radius

    def assert_native_same(self, fixture, cache, expected_progress, name):
        if cache.kind != ts.CacheKind.SAME or fixture.markers[fixture.group.current_event].transition_style != 0:
            return Decimal(0)
        native = native_difference_progress(cache.value, fixture.group.past_distance, MIN_PREEMPT)
        radius = Decimal.from_float(float(native.error))
        actual_error = abs(Decimal.from_float(float(native.value)) - expected_progress)
        self.assertLessEqual(actual_error, radius, f"{name}: native final progress outside certificate")
        self.assertLessEqual(radius, PROGRESS_BUDGET, f"{name}: native final progress certificate exceeds budget")
        return radius

    def run_case(self, name, records, *, minimum_ratio_exponent=0):
        self.assertEqual(len(records), MARKER_COUNT)
        self.assertEqual(records[0].time, 0)
        self.assertEqual(records[-1].time, CHART_SECONDS)
        print(f"\nTimescale stress {name}: preprocessing {len(records)} markers", flush=True)
        fixture = TimelineFixture(records)
        started = perf_counter()
        with fixture:
            preprocessing_seconds = perf_counter() - started
            oracle = fixture.oracle
            assert oracle is not None
            if minimum_ratio_exponent:
                # Twenty thousand dyadic links have at most ten thousand binary
                # ratio exponent steps. This precision also retains every input
                # time bit and the full terminating decimal expansion of 2^-n.
                oracle.precision = MARKER_COUNT // 2 + 256
            self.assertTrue(fixture.group.valid, name)
            self.assertEqual(fixture.group.marker_count, MARKER_COUNT)
            root = fixture.markers[fixture.group.root]
            with localcontext() as context:
                context.prec = oracle.precision
                reference_ratio, reference_distance = oracle.anchor_transfer(0, MARKER_COUNT - 1)
                if minimum_ratio_exponent:
                    binary_exponent = sum(
                        1 if left.speed > right.speed else -1 for left, right in pairwise(records) if left.style == 1
                    )
                    self.assertEqual(reference_ratio, Decimal(2) ** binary_exponent)
                self.assert_encloses(root.aggregate.ratio, reference_ratio, f"{name} root R")
                self.assert_encloses(root.aggregate.distance, reference_distance, f"{name} root B")
            if minimum_ratio_exponent:
                self.assertGreater(abs(root.aggregate.ratio.exponent), minimum_ratio_exponent)

            largest_radius = Decimal(0)
            largest_actual_error = Decimal(0)
            largest_native_radius = Decimal(0)
            prepare_queries = 0
            direct_queries = 0
            cache_kinds = set()
            # Include interior and final-marker crossings. All gaps straddle a
            # real marker and remain within visibility at speeds up to eight.
            boundaries = sorted(
                {float(records[i].time) for i in (MARKER_COUNT // 2, MARKER_COUNT - 4, MARKER_COUNT - 1)}
            )
            for boundary in boundaries:
                before = float(quantized32(boundary - CLOCK_STEP))
                after = float(quantized32(boundary + CLOCK_STEP))
                for now, hit in ((before, after), (after, before)):
                    with self.subTest(case=name, now=now, hit=hit), localcontext() as context:
                        context.prec = 100
                        self.assertNotEqual(ts.locate_time(100000, now), ts.locate_time(100000, hit))
                        expected = oracle.distance(now, hit)
                        with patch.object(ts, "_range_transfer", wraps=ts._range_transfer) as queries:
                            direct = ts.distance_between(100000, now, hit)
                            direct_queries += queries.call_count
                        self.assert_encloses(direct, expected, f"{name} direct distance")
                        target = ts.locate_target(100000, hit)
                        cache = ts.TrajectoryCache(0, 0, ts.CacheKind.IDENTITY, 0, AccurateScalar.of(0), False)
                        ts.prepare_group(100000, now)
                        with patch.object(ts, "_range_transfer", wraps=ts._range_transfer) as queries:
                            ts.prepare_trajectory(
                                100000, hit, target, cache, now, 999, distance_tolerance=MIN_PREEMPT * 2e-5
                            )
                            prepare_queries += queries.call_count
                        cache_kinds.add(int(cache.kind))
                        # This is the ordinary published evaluation, with no
                        # accurate=True substitution or hot-path reconstruction.
                        with patch.object(ts, "_range_transfer", side_effect=AssertionError("hot-path tree query")):
                            distance = ts.evaluate_trajectory(100000, hit, target, cache, now)
                        self.assert_encloses(distance, expected, f"{name} cached distance")
                        progress = AccurateScalar.of(1).published_add(
                            distance.published_div(AccurateScalar.of(MIN_PREEMPT)).neg()
                        )
                        expected_progress = 1 - expected / Decimal.from_float(MIN_PREEMPT)
                        center, radius = self.assert_encloses(progress, expected_progress, f"{name} progress")
                        largest_radius = max(largest_radius, radius)
                        largest_actual_error = max(largest_actual_error, abs(center - expected_progress))
                        self.assertLessEqual(radius, PROGRESS_BUDGET, f"{name}: uncertified visible progress")
                        self.assertTrue(progress.error_at_most(float(PROGRESS_BUDGET)))
                        largest_native_radius = max(
                            largest_native_radius, self.assert_native_same(fixture, cache, expected_progress, name)
                        )
            # A broad unaligned range exercises actual hierarchy queries. Huge
            # offscreen results must remain enclosed without float conversion;
            # signed cancellation can make this same long range visible again.
            now = float(quantized32(float(records[13].time) + CLOCK_STEP))
            hit = float(quantized32(float(records[-17].time) + CLOCK_STEP))
            with self.subTest(case=name, span="long"), localcontext() as context:
                context.prec = 100
                expected = oracle.distance(now, hit)
                with patch.object(ts, "_range_transfer", wraps=ts._range_transfer) as queries:
                    direct = ts.distance_between(100000, now, hit)
                    direct_queries += queries.call_count
                self.assert_encloses(direct, expected, f"{name} long direct distance")
                target = ts.locate_target(100000, hit)
                cache = ts.TrajectoryCache(0, 0, ts.CacheKind.IDENTITY, 0, AccurateScalar.of(0), False)
                ts.prepare_group(100000, now)
                with patch.object(ts, "_range_transfer", wraps=ts._range_transfer) as queries:
                    ts.prepare_trajectory(100000, hit, target, cache, now, 999, distance_tolerance=MIN_PREEMPT * 2e-5)
                    prepare_queries += queries.call_count
                with patch.object(ts, "_range_transfer", side_effect=AssertionError("hot-path tree query")):
                    distance = ts.evaluate_trajectory(100000, hit, target, cache, now)
                self.assert_encloses(distance, expected, f"{name} long cached distance")
                if abs(expected / Decimal.from_float(MIN_PREEMPT)) <= 1:
                    progress = AccurateScalar.of(1).published_add(
                        distance.published_div(AccurateScalar.of(MIN_PREEMPT)).neg()
                    )
                    expected_progress = 1 - expected / Decimal.from_float(MIN_PREEMPT)
                    center, radius = self.assert_encloses(progress, expected_progress, f"{name} long visible progress")
                    largest_radius = max(largest_radius, radius)
                    largest_actual_error = max(largest_actual_error, abs(center - expected_progress))
                    self.assertLessEqual(radius, PROGRESS_BUDGET, f"{name}: uncertified long visible progress")
                    self.assertTrue(progress.error_at_most(float(PROGRESS_BUDGET)))
                    largest_native_radius = max(
                        largest_native_radius, self.assert_native_same(fixture, cache, expected_progress, name)
                    )
            print(
                f"Timescale stress {name}: preprocess={preprocessing_seconds:.3f}s; "
                f"cold prepare tree queries={prepare_queries}; direct query tree calls={direct_queries}; "
                f"hot tree queries=0; cache kinds={sorted(cache_kinds)}; "
                f"max progress radius={largest_radius:.6g}; max actual error={largest_actual_error:.6g}; "
                f"max native SAME radius={largest_native_radius:.6g}",
                flush=True,
            )

    def test_dense_pure_timescale_certificates(self):
        self.run_case("dense timescale", practical_markers([RefMarker(i, 1) for i in range(MARKER_COUNT)]))

    def test_reciprocal_hybrid_certificates(self):
        self.run_case("reciprocal hybrid", practical_markers(reciprocal_markers(quantize=True)))

    def test_non_dyadic_hybrid_certificates(self):
        self.run_case("non-dyadic hybrid", practical_markers(non_dyadic_markers()))

    def test_growing_huge_exponent_certificates(self):
        self.run_case("growing exponent", practical_markers(huge_exponent_markers()), minimum_ratio_exponent=9000)

    def test_shrinking_huge_exponent_certificates(self):
        self.run_case(
            "shrinking exponent", practical_markers(huge_exponent_markers(shrinking=True)), minimum_ratio_exponent=9000
        )

    def test_signed_variation_near_one_million_certificates(self):
        records = signed_variation_markers()
        self.assertEqual(sum(abs(marker.skip) for marker in records) + 4 * CHART_SECONDS, 987200)
        self.run_case("signed variation 987200", records)

    def test_long_non_dyadic_rolling_sequence_and_seeks(self):
        # Unlike the unit rebase test, speeds change, all quadratic easings are
        # present, and exact reciprocal cycles prevent an accidental huge-gauge
        # fixture from forcing every otherwise ordinary frame through cold work.
        source = reciprocal_markers(cycles=256, high="1.1", step="0.015625", quantize=True)
        records = [
            RefMarker(quantized32(marker.time), marker.speed, i % 6, marker.style) for i, marker in enumerate(source)
        ]
        hit = float(quantized32(float(records[769].time) + CLOCK_STEP))
        regular = {float(quantized32(i / 128 + CLOCK_STEP)) for i in range(2049)}
        regular.update((hit - CLOCK_STEP, hit, hit + CLOCK_STEP))
        frames = [(now, False) for now in sorted(regular)]
        seeks = (0.25, 13.25, 5.125, hit - CLOCK_STEP, hit, hit + CLOCK_STEP, 15.5, 1.0)
        frames.extend((float(quantized32(now + step / 128)), step == 0) for now in seeks for step in range(3))
        started = perf_counter()
        with TimelineFixture(records) as fixture:
            preprocessing_seconds = perf_counter() - started
            oracle = fixture.oracle
            assert oracle is not None
            fixture.group.effective_preempt = MIN_PREEMPT
            target = ts.locate_target(100000, hit)
            cache = ts.TrajectoryCache(0, 0, ts.CacheKind.IDENTITY, 0, AccurateScalar.of(0), False)
            cold_frames = 0
            cold_seek_frames = 0
            adjacent_transitions = 0
            adjacent_resets = 0
            visible_checks = 0
            largest_radius = Decimal(0)
            largest_error = Decimal(0)
            largest_native_radius = Decimal(0)
            with patch.object(ts, "_target_from_anchor", wraps=ts._target_from_anchor) as cold_queries:
                for frame, (now, seek) in enumerate(frames):
                    with self.subTest(frame=frame, now=now, seek=seek), localcontext() as context:
                        context.prec = 100
                        previous_run = cache.run_ref
                        ts.prepare_group(100000, now)
                        adjacent = (
                            cache.valid
                            and previous_run > 0
                            and previous_run != fixture.group.current_run
                            and fixture.markers[previous_run].run_end == fixture.group.current_run
                        )
                        before = cold_queries.call_count
                        ts.prepare_trajectory(100000, hit, target, cache, now, 999)
                        cold = cold_queries.call_count != before
                        cold_frames += int(cold)
                        cold_seek_frames += int(cold and seek)
                        adjacent_transitions += int(adjacent)
                        adjacent_resets += int(adjacent and cold)
                        with patch.object(
                            ts, "_range_transfer", side_effect=AssertionError("rolling hot-path tree query")
                        ):
                            distance = ts.evaluate_trajectory(100000, hit, target, cache, now)
                        expected = oracle.distance(now, hit)
                        self.assert_encloses(distance, expected, "rolling/seek distance")
                        if abs(expected / Decimal.from_float(MIN_PREEMPT)) <= 1:
                            visible_checks += 1
                            progress = AccurateScalar.of(1).published_add(
                                distance.published_div(AccurateScalar.of(MIN_PREEMPT)).neg()
                            )
                            expected_progress = 1 - expected / Decimal.from_float(MIN_PREEMPT)
                            center, radius = self.assert_encloses(
                                progress, expected_progress, "rolling visible progress"
                            )
                            largest_radius = max(largest_radius, radius)
                            largest_error = max(largest_error, abs(center - expected_progress))
                            largest_native_radius = max(
                                largest_native_radius,
                                self.assert_native_same(fixture, cache, expected_progress, "rolling"),
                            )
                            self.assertLessEqual(radius, PROGRESS_BUDGET)
                            self.assertTrue(progress.error_at_most(float(PROGRESS_BUDGET)))
                anchor_query_calls = cold_queries.call_count
            self.assertGreater(visible_checks, 3)
            self.assertGreater(adjacent_transitions - adjacent_resets, 0)
            self.assertGreater(cold_seek_frames, 0)
            print(
                f"\nTimescale rolling stress: markers={len(records)}; frames={len(frames)}; "
                f"preprocess={preprocessing_seconds:.3f}s; adjacent run crossings={adjacent_transitions}; "
                f"adjacent cold resets={adjacent_resets}; cold frames={cold_frames}; "
                f"seek cold frames={cold_seek_frames}; anchor query calls={anchor_query_calls}; hot tree queries=0; "
                f"visible checks={visible_checks}; max progress radius={largest_radius:.6g}; "
                f"max actual error={largest_error:.6g}; max native SAME radius={largest_native_radius:.6g}",
                flush=True,
            )

    def test_non_sixty_bpm_signed_conversion_and_visible_certificates(self):
        # A bounded companion to the full 987,200-variation case: native marker
        # times are already converted seconds, but authored skips still undergo
        # the production BPM conversion. The oracle receives integral skips.
        initialize = ts.initialize_timescale_group
        for bpm in (120.0, 137.0, float(quantized32("189.7"))):
            records = []
            for i in range(512):
                time = quantized32(1672 + i / 4)
                speed = 8 if i % 2 == 0 else -8
                records.extend((RefMarker(time, speed, ease=1, skip=49), RefMarker(time, speed, ease=1, skip=-49)))
            with localcontext() as context:
                context.prec = 100
                converted = [
                    RefMarker(
                        marker.time, marker.speed, marker.ease, marker.style, marker.skip * 60 / Decimal.from_float(bpm)
                    )
                    for marker in records
                ]
            oracle = RefTimeline(converted)

            def initialize_at_bpm(group, selected_bpm=bpm):
                # TimelineFixture establishes its default patches before this
                # call; override only the native BPM source during preprocessing.
                with patch.object(ts, "beat_to_bpm", return_value=selected_bpm):
                    initialize(group)

            with (
                self.subTest(bpm=bpm),
                patch.object(ts, "initialize_timescale_group", side_effect=initialize_at_bpm),
                TimelineFixture(records) as fixture,
                localcontext() as context,
            ):
                context.prec = 100
                self.assertTrue(fixture.group.valid)
                self.assert_encloses(fixture.markers[1].converted_skip, converted[0].skip, "converted skip")
                boundary = float(records[-1].time)
                now, hit = boundary - CLOCK_STEP, boundary + CLOCK_STEP
                target = ts.locate_target(100000, hit)
                cache = ts.TrajectoryCache(0, 0, ts.CacheKind.IDENTITY, 0, AccurateScalar.of(0), False)
                ts.prepare_group(100000, now)
                ts.prepare_trajectory(100000, hit, target, cache, now, 999, distance_tolerance=MIN_PREEMPT * 2e-5)
                with patch.object(ts, "_range_transfer", side_effect=AssertionError("general-BPM hot tree query")):
                    distance = ts.evaluate_trajectory(100000, hit, target, cache, now)
                expected = oracle.distance(now, hit)
                self.assert_encloses(distance, expected, "general-BPM signed distance")
                progress = AccurateScalar.of(1).published_add(
                    distance.published_div(AccurateScalar.of(MIN_PREEMPT)).neg()
                )
                expected_progress = 1 - expected / Decimal.from_float(MIN_PREEMPT)
                _, radius = self.assert_encloses(progress, expected_progress, "general-BPM signed progress")
                self.assertLessEqual(radius, PROGRESS_BUDGET)
                native_radius = self.assert_native_same(fixture, cache, expected_progress, "general-BPM")
                print(
                    f"\nTimescale signed conversion: BPM={bpm:.9g}; markers={len(records)}; "
                    f"max progress radius={radius:.6g}; native SAME radius={native_radius:.6g}",
                    flush=True,
                )


if __name__ == "__main__":
    unittest.main()
