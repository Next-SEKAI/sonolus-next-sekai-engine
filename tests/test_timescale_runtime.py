# ruff: noqa: PT009
import unittest
from unittest.mock import patch

from sekai.lib import timescale as ts
from tests.test_timescale_timeline import TimelineFixture
from tests.timescale_reference import RefMarker


def empty_cache():
    return ts.TrajectoryCache(0, 0)


class TimescaleRuntimeTests(unittest.TestCase):
    def test_cache_matches_oracle_across_runs_and_seeks(self):
        records = [
            RefMarker(0, 1, ease=1),
            RefMarker(1, 3, ease=2),
            RefMarker(2, 2, ease=4, style=1),
            RefMarker(3, 0.5, ease=5, style=1),
            RefMarker(4, 4, ease=3),
            RefMarker(5, 1),
        ]
        with TimelineFixture(records) as fixture:
            for hit in [-1, 0, 1.25, 2, 3.7, 4, 6]:
                target, cache = ts.locate_target(100000, hit), empty_cache()
                for now in [-2, 0, 0.5, 1, 2, 2.8, 4, 6, 3.2, 0.3]:
                    ts.prepare_group(100000, now)
                    ts.prepare_trajectory(100000, hit, target, cache, now)
                    expected = float(fixture.oracle.distance(now, hit))
                    self.assertAlmostEqual(
                        ts.evaluate_trajectory(100000, hit, target, cache, now),
                        expected,
                        delta=max(1e-9, abs(expected) * 1e-11),
                    )

    def test_cache_does_not_refresh_at_internal_markers(self):
        records = [RefMarker(i, i + 1, ease=i % 6) for i in range(8)] + [RefMarker(8, 1, style=1), RefMarker(9, 2)]
        with TimelineFixture(records):
            target, cache = ts.locate_target(100000, 10), empty_cache()
            ts.prepare_group(100000, 0.1)
            ts.prepare_trajectory(100000, 10, target, cache, 0.1)
            value = cache.boundary_distance
            with patch.object(ts, "_distance_from", side_effect=AssertionError("unnecessary cold query")):
                for now in [0.2, 1.5, 3.1, 7.5, 1.1]:
                    ts.prepare_group(100000, now)
                    ts.prepare_trajectory(100000, 10, target, cache, now)
                    ts.evaluate_trajectory(100000, 10, target, cache, now)
                    self.assertEqual(cache.boundary_distance, value)

    def test_capped_far_target_can_reenter_after_run_changes(self):
        records = [RefMarker(i / 10, 2 if i % 2 == 0 else 1, style=1 if i % 2 == 0 else 0) for i in range(301)]
        with TimelineFixture(records) as fixture:
            hit = 30.1
            target, cache = ts.locate_target(100000, hit), empty_cache()
            ts.prepare_group(100000, 0)
            ts.prepare_trajectory(100000, hit, target, cache, 0)
            self.assertEqual(cache.boundary_distance, ts.DISTANCE_LIMIT)
            for now in [29.81, 29.95, 30.09, 30.11]:
                ts.prepare_group(100000, now)
                ts.prepare_trajectory(100000, hit, target, cache, now)
                self.assertAlmostEqual(
                    ts.evaluate_trajectory(100000, hit, target, cache, now),
                    float(fixture.oracle.distance(now, hit)),
                    places=10,
                )

    def test_near_hit_at_end_of_long_event_stays_local(self):
        for ease in range(6):
            with TimelineFixture([RefMarker(0, 0.05, ease=ease), RefMarker(1800, 8)]) as fixture:
                hit, now = 1800.0005, 1799.9995
                target, cache = ts.locate_target(100000, hit), empty_cache()
                ts.prepare_group(100000, now)
                ts.prepare_trajectory(100000, hit, target, cache, now)
                expected = float(fixture.oracle.distance(now, hit))
                self.assertAlmostEqual(ts.evaluate_trajectory(100000, hit, target, cache, now), expected, delta=1e-8)

    def test_lifetime_union_and_final_play_cleanup_frame(self):
        from sekai.play import timescale as play_ts
        from sekai.watch import timescale as watch_ts

        with TimelineFixture([RefMarker(0, 1)]) as fixture:
            self.assertFalse(fixture.group.used)
            ts.locate_target(100000, 2)
            self.assertFalse(fixture.group.used)
            with patch.object(ts.runtime, "is_preprocessing", return_value=True):
                ts.register_group_window(100000, float("inf"), 2)
                self.assertFalse(fixture.group.used)
                ts.register_group_window(100000, 1, 2)
            self.assertEqual(watch_ts.WatchTimescaleGroup.spawn_time(fixture.group), 1)
            self.assertEqual(watch_ts.WatchTimescaleGroup.despawn_time(fixture.group), 2)
            fixture.group.despawn = False
            with patch.object(play_ts, "time", return_value=100):
                self.assertTrue(play_ts.TimescaleGroup.should_spawn(fixture.group))
                play_ts.TimescaleGroup.update_sequential(fixture.group)
            self.assertTrue(fixture.group.despawn)
            self.assertEqual(fixture.group.last_updated, 100)

    def test_compact_slot_ledgers(self):
        from sekai.play.timescale import TimescaleChange, TimescaleGroup
        from sekai.watch.timescale import WatchTimescaleChange, WatchTimescaleGroup

        self.assertEqual(ts.TargetPosition._size_(), 3)
        self.assertEqual(ts.TrajectoryCache._size_(), 2)
        for cls, data, shared in [
            (TimescaleChange, 26, 0),
            (WatchTimescaleChange, 26, 0),
            (TimescaleGroup, 10, 24),
            (WatchTimescaleGroup, 10, 24),
        ]:
            cls._init_fields()
            self.assertEqual(
                max((field.offset + field.type._size_() for field in cls._data_fields_.values()), default=0), data
            )
            self.assertEqual(
                max((field.offset + field.type._size_() for field in cls._shared_memory_fields_.values()), default=0),
                shared,
            )
