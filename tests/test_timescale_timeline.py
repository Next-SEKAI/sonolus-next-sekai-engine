# ruff: noqa: PT009
"""Check linked runs and local distances against a chronological Decimal oracle."""

import random
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sekai.lib import timescale as ts
from tests.timescale_reference import RefMarker, RefTimeline


class TimelineFixture:
    def __init__(self, records, validate_oracle=True):
        self.oracle: Any = RefTimeline(records) if validate_oracle else None
        self.group: Any = SimpleNamespace(
            index=100000, first_ref=SimpleNamespace(index=1 if records else 0), force_note_speed=0, valid=False
        )
        self.markers = {
            i: SimpleNamespace(
                index=i,
                beat=float(record.time),
                timescale=float(record.speed),
                timescale_skip=float(record.skip),
                timescale_ease=int(record.ease),
                transition_style=int(record.style),
                hide_notes=record.hide,
                next_ref=SimpleNamespace(index=i + 1 if i < len(records) else 0),
                timescale_group=SimpleNamespace(index=100000),
                validation_owner=0,
            )
            for i, record in enumerate(records, 1)
        }

    def __enter__(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(ts, "_marker", side_effect=self.markers.__getitem__))
        self.stack.enter_context(patch.object(ts, "_valid_marker_ref", side_effect=lambda r: r in self.markers))
        self.stack.enter_context(
            patch.object(ts, "timescale_group_archetype", return_value=SimpleNamespace(at=lambda _: self.group))
        )
        self.stack.enter_context(patch.object(ts, "Options", SimpleNamespace(disable_timescale=False)))
        self.stack.enter_context(patch.object(ts, "beat_to_time", side_effect=lambda x: x))
        self.stack.enter_context(patch.object(ts, "beat_to_bpm", return_value=60))
        self.stack.enter_context(patch.object(ts, "preempt_time", return_value=0.0035))
        ts.initialize_timescale_group(self.group)
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


class TimescaleTimelineTests(unittest.TestCase):
    def test_prepared_target_queries_keep_the_shared_lookup_at_the_target(self):
        records = [RefMarker(0, 1, style=1), RefMarker(1, 2, style=1), RefMarker(1, 1), RefMarker(2, 2)]
        with TimelineFixture(records) as fixture:
            target = ts.locate_target(100000, 2.5)
            shared = fixture.group.lookup_ref
            ref = target.event_ref
            for now in (-1, 0, 0.5, 1, 1.5, 2, 3):
                ref = ts.locate_time_from(100000, now, ref)
                actual = ts.distance_to_target(100000, ref, now, target, 2.5)
                self.assertAlmostEqual(actual, float(fixture.oracle.distance(now, 2.5)))
                self.assertEqual(fixture.group.lookup_ref, shared)

    def test_monotone_target_flag_covers_stops_and_rejects_reversals(self):
        for speed, skip, expected in ((0, 1, True), (1, 0, True), (-1, 0, False), (1, -1, False)):
            with self.subTest(speed=speed, skip=skip), TimelineFixture([RefMarker(0, speed, skip=skip)]) as fixture:
                self.assertEqual(fixture.group.monotone_targets, expected)

    def test_distances_across_signed_skips_and_atomic_ties(self):
        for records in [
            [RefMarker(-1, 1, skip=2), RefMarker(0, -2, ease=4), RefMarker(0, 3, skip=-1), RefMarker(1, 0)],
            [RefMarker(-1, 1, ease=3), RefMarker(0, 2, style=1), RefMarker(0, 3), RefMarker(1, 0.5, style=1)],
        ]:
            with TimelineFixture(records) as fixture:
                self.assertEqual(ts.locate_time(100000, 0), 3)
                for now in [-2, -1, -0.7, 0, 0.2, 1, 2]:
                    for hit in [-2, -1, -0.4, 0, 0.7, 1, 2]:
                        actual = ts.distance_between(100000, now, hit)
                        expected = float(fixture.oracle.distance(now, hit))
                        self.assertAlmostEqual(actual, expected, delta=max(1e-9, abs(expected) * 1e-11))

    def test_random_mixed_run_distances_all_eases_and_seeks(self):
        rng = random.Random(37)
        records = [RefMarker(i / 4, rng.uniform(0.05, 8), ease=i % 6, style=(i // 5) % 2) for i in range(70)]
        with TimelineFixture(records) as fixture:
            for _ in range(150):
                now, hit = rng.uniform(-3, 20), rng.uniform(-3, 20)
                expected = float(fixture.oracle.distance(now, hit))
                self.assertAlmostEqual(
                    ts.distance_between(100000, now, hit), expected, delta=max(1e-9, abs(expected) * 1e-11)
                )

    def test_runs_coalesce_without_losing_zero_duration_boundaries(self):
        records = [RefMarker(0, 1), RefMarker(1, 2), RefMarker(1, 3, style=1), RefMarker(1, 4), RefMarker(2, 1)]
        with TimelineFixture(records) as fixture:
            self.assertEqual([m.run_first for m in fixture.markers.values()], [1, 1, 3, 4, 4])
            self.assertEqual(fixture.markers[1].run_end, 3)
            self.assertEqual(fixture.markers[3].run_end, 4)
            self.assertEqual(fixture.markers[4].prev_run, 3)
            self.assertEqual(ts.locate_time(100000, 1), 4)
            self.assertEqual(ts.locate_time(100000, 0.5), 1)

    def test_unused_groups_still_validate_bad_data(self):
        for records in [[RefMarker(0, 0, style=1)], [RefMarker(0, 1, skip=1), RefMarker(1, 1, style=1)]]:
            with TimelineFixture(records) as fixture:
                self.assertFalse(fixture.group.used)
                self.assertTrue(fixture.group.valid)
                self.assertEqual(fixture.group.error_code, ts.TimelineError.NONE)
        fixture = TimelineFixture([RefMarker(0, 1), RefMarker(1, 2)])
        fixture.markers[2].next_ref.index = 1
        with fixture:
            self.assertEqual(fixture.group.error_code, ts.TimelineError.CYCLE)

    def test_mixed_signed_skips_stops_and_zero_crossing(self):
        records = [
            RefMarker(0, -1, style=1, ease=1),
            RefMarker(1, 1, style=1, skip=-2),
            RefMarker(2, 0, skip=1),
            RefMarker(3, 0, style=1),
            RefMarker(4, -2, skip=-1),
            RefMarker(4, 2, style=1, skip=2),
            RefMarker(5, 1),
        ]
        times = [-1, 0, 0.499999, 0.5, 0.500001, 1, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6]
        with TimelineFixture(records) as fixture:
            for hit in times:
                target = ts.locate_target(100000, hit)
                cache = ts.TrajectoryCache(0, 0)
                for now in times:
                    expected = float(fixture.oracle.distance(now, hit))
                    self.assertAlmostEqual(ts.distance_between(100000, now, hit), expected, delta=1e-8)
                    ts.prepare_group(100000, now)
                    ts.prepare_trajectory(100000, hit, target, cache, now)
                    self.assertAlmostEqual(
                        ts.evaluate_trajectory(100000, hit, target, cache, now), expected, delta=1e-8
                    )

    def test_empty_identity(self):
        with TimelineFixture([]):
            self.assertEqual(ts.distance_between(100000, -2, 3), 5)
