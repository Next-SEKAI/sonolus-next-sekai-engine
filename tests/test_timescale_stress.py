# ruff: noqa: PT009
"""Practical 30-minute charts against the independent chronological oracle.

Marker values and query clocks are binary32 inputs. This exercises production
Python proxies, whose arithmetic is binary64, not a Sonolus client benchmark.
Compiled arithmetic coverage belongs to the small compiled-kernel tests.
"""

import unittest
from decimal import Decimal
from time import perf_counter
from unittest.mock import patch

from sekai.lib import timescale as ts
from tests.test_timescale_timeline import TimelineFixture
from tests.timescale_reference import RefMarker, quantized32

MARKER_COUNT = 20_000
CHART_SECONDS = 1800
MIN_PREEMPT = float(quantized32("0.0035"))
CLOCK_STEP = 2**-13
POSITION_TOLERANCE = 1e-3
GROUP = 100000


def native(value):
    return float(quantized32(value))


def practical_markers(*, hybrid=False, signed=False):
    speeds = (0, 8, 2, -8, -0.05, 0.5) if signed else (1, 0.05, 8, 0.3, 2, 1.1)
    result = []
    for i in range(MARKER_COUNT):
        # Each scroll run begins and ends at speed one, so the positive chart
        # repeats ordinary behavior instead of accumulating exponential gain.
        style = (i // 120) % 2 if hybrid else 0
        skip = (0.25 if (i // 97) % 2 else -0.25) if signed and i % 97 == 0 else 0
        result.append(
            RefMarker(
                native(CHART_SECONDS * i / (MARKER_COUNT - 1)),
                native(speeds[i % len(speeds)]),
                ease=i % 6,
                style=style,
                skip=skip,
            )
        )
    return result


class TimescaleStressTests(unittest.TestCase):
    def assert_position(self, fixture, actual_distance, now, hit, preempt):
        expected_distance = fixture.oracle.distance(now, hit)
        expected = float(1 - expected_distance / Decimal.from_float(preempt))
        actual = 1 - actual_distance / preempt
        error = abs(actual - expected)
        self.assertLessEqual(error, POSITION_TOLERANCE, f"now={now}, hit={hit}, preempt={preempt}")
        return error

    def run_chart(self, name, records):
        self.assertEqual(len(records), MARKER_COUNT)
        self.assertEqual(records[-1].time, CHART_SECONDS)
        started = perf_counter()
        with TimelineFixture(records) as fixture:
            load_seconds = perf_counter() - started
            self.assertTrue(fixture.group.valid)
            largest_error = 0.0
            # All easings near the end of a long accumulated history, plus the
            # middle of the chart, style boundaries and the final held tail.
            indices = [*range(19800, 19806), 9960, 10080, 19400, MARKER_COUNT - 1]
            for index in indices:
                boundary = float(records[index].time)
                before, after = native(boundary - CLOCK_STEP), native(boundary + CLOCK_STEP)
                for now, hit in ((before, after), (after, before), (boundary, boundary)):
                    with self.subTest(chart=name, marker=index, now=now, hit=hit):
                        distance = ts.distance_between(GROUP, now, hit)
                        largest_error = max(
                            largest_error, self.assert_position(fixture, distance, now, hit, MIN_PREEMPT)
                        )

            # Longer normal-preempt queries cross several markers and a style
            # boundary in both directions. One wide range checks stored sums.
            boundary = float(records[10080].time)
            pairs = [
                (native(boundary - 0.2), native(boundary + 0.2)),
                (native(boundary + 0.2), native(boundary - 0.2)),
                (native(1.234), native(1798.765)),
                (native(1798.765), native(1.234)),
            ]
            for now, hit in pairs:
                with self.subTest(chart=name, now=now, hit=hit):
                    largest_error = max(
                        largest_error,
                        self.assert_position(fixture, ts.distance_between(GROUP, now, hit), now, hit, 1.5),
                    )

            # Reuse one note's cache through ordinary frames and explicit seeks.
            hit = native(boundary + CLOCK_STEP)
            target = ts.locate_target(GROUP, hit)
            cache = ts.TrajectoryCache(0, 0.0)
            frames = [native(boundary + offset) for offset in (-0.2, -0.1, -CLOCK_STEP, 0, CLOCK_STEP, 0.1, -0.1)]
            for now in frames:
                ts.prepare_group(GROUP, now)
                previous_run, previous_distance = cache.run_ref, cache.boundary_distance
                with patch.object(ts, "_distance_from", wraps=ts._distance_from) as queries:
                    ts.prepare_trajectory(GROUP, hit, target, cache, now)
                    if previous_run == cache.run_ref:
                        self.assertEqual(queries.call_count, 0)
                        self.assertEqual(cache.boundary_distance, previous_distance)
                with patch.object(ts, "_distance_from", side_effect=AssertionError("hot-path run query")):
                    distance = ts.evaluate_trajectory(GROUP, hit, target, cache, now)
                largest_error = max(largest_error, self.assert_position(fixture, distance, now, hit, MIN_PREEMPT))
            print(f"\n{name}: 20k markers; Python load {load_seconds:.3f}s; max position error {largest_error:.3g}")

    def test_positive_timescale_30_minutes(self):
        self.run_chart("positive timescale", practical_markers())

    def test_mixed_styles_30_minutes(self):
        self.run_chart("mixed positive styles", practical_markers(hybrid=True))

    def test_signed_timescale_30_minutes(self):
        self.run_chart("signed timescale with skips", practical_markers(signed=True))


if __name__ == "__main__":
    unittest.main()
