# ruff: noqa: PT009, PT027
import struct
import unittest
from unittest.mock import patch

from sekai.lib import timescale as ts
from sekai.lib.timescale_math import AccurateScalar
from tests.test_timescale_timeline import TimelineFixture
from tests.timescale_reference import RefMarker


def empty_cache():
    return ts.TrajectoryCache(0, 0, ts.CacheKind.IDENTITY, 0, AccurateScalar.of(0), False)


class TimescaleRuntimeTests(unittest.TestCase):
    def test_group_window_union_rejects_invalid_lifetimes(self):
        with TimelineFixture([RefMarker(0, 1)]) as fixture:
            with patch.object(ts.runtime, "is_preprocessing", return_value=True):
                for start, end in [(float("inf"), 2), (1, -float("inf")), (2, 1), (float("nan"), 2)]:
                    ts.register_group_window(100000, start, end)
                self.assertFalse(fixture.group.used)
                ts.register_group_window(100000, 2, 3)
                ts.register_group_window(100000, -1, 2)
                ts.register_group_window(100000, 6, 6)
            self.assertEqual(fixture.group.needed_start, -1)
            self.assertEqual(fixture.group.needed_end, 6)
            self.assertTrue(fixture.group.used)

    def test_play_group_updates_the_final_frame_after_a_large_jump(self):
        from sekai.play import timescale as play_ts

        with TimelineFixture([RefMarker(0, 1)]) as fixture:
            fixture.group.despawn = False
            with patch.object(play_ts, "time", return_value=-1):
                self.assertFalse(play_ts.TimescaleGroup.should_spawn(fixture.group))
            with patch.object(ts.runtime, "is_preprocessing", return_value=True):
                ts.register_group_window(100000, 1, 2)
            self.assertEqual(play_ts.TimescaleGroup.spawn_order(fixture.group), 1)
            for now in [1, 2, 100]:
                with patch.object(play_ts, "time", return_value=now):
                    self.assertTrue(play_ts.TimescaleGroup.should_spawn(fixture.group))
                    play_ts.TimescaleGroup.update_sequential(fixture.group)
                self.assertEqual(fixture.group.last_updated, now)
                self.assertEqual(fixture.group.despawn, now > 2)

    def test_watch_group_window_and_seek_refresh_preserve_batch_ties(self):
        from sekai.watch import timescale as watch_ts

        records = [RefMarker(0, 1), RefMarker(1, 2, style=1), RefMarker(1, 3), RefMarker(2, 1)]
        with TimelineFixture(records) as fixture:
            self.assertEqual(watch_ts.WatchTimescaleGroup.spawn_time(fixture.group), 1e8)
            self.assertEqual(watch_ts.WatchTimescaleGroup.despawn_time(fixture.group), 1e8)
            with patch.object(ts.runtime, "is_preprocessing", return_value=True):
                ts.register_group_window(100000, -.5, 1e8)
            self.assertEqual(watch_ts.WatchTimescaleGroup.spawn_time(fixture.group), -.5)
            self.assertEqual(watch_ts.WatchTimescaleGroup.despawn_time(fixture.group), 1e8)
            for now, expected_ref in [(1, 3), (.5, 1), (2, 4), (1, 3)]:
                with patch.object(watch_ts, "time", return_value=now):
                    watch_ts.WatchTimescaleGroup.update_sequential(fixture.group)
                self.assertEqual(fixture.group.last_updated, now)
                self.assertEqual(fixture.group.current_event, expected_ref)

    def test_specialized_raw_anchor_queries_match_general_transfers(self):
        cases = [
            [RefMarker(-1, 1, skip=2), RefMarker(0, -2, ease=4), RefMarker(0, 3, skip=-1), RefMarker(1, 0)],
            [RefMarker(-1, 1, ease=3), RefMarker(0, 2, style=1), RefMarker(0, 3), RefMarker(1, .5, style=1)],
        ]
        for records in cases:
            with TimelineFixture(records) as fixture:
                for anchor, marker in fixture.markers.items():
                    for hit in [-2, -1, -.7, 0, .2, 1, 2]:
                        target = ts.locate_target(100000, hit)
                        reverse = target.event_ref < anchor
                        if reverse:
                            transfer = ts._forward_transfer(fixture.group, hit, target.event_ref, marker.event_start, anchor)
                            expected = transfer.distance.neg().div(transfer.ratio)
                        else:
                            transfer = ts._forward_transfer(fixture.group, marker.event_start, anchor, hit, target.event_ref)
                            expected = transfer.distance
                        for published in [False, True]:
                            actual = ts._target_from_anchor(fixture.group, anchor, hit, target, published)
                            self.assertLessEqual(
                                abs(actual.to_float() - expected.to_float()),
                                actual.absolute_error().to_float() + expected.absolute_error().to_float() + 1e-12,
                            )

    def test_split_preparation_defers_only_cold_work(self):
        with TimelineFixture([RefMarker(0, 1), RefMarker(1, 1, style=1), RefMarker(2, 1)]):
            hit = 3
            target = ts.locate_target(100000, hit)
            cache = empty_cache()
            ts.prepare_group(100000, .1)
            with patch.object(ts, "_target_from_anchor", side_effect=AssertionError("cold work in cheap attempt")):
                self.assertFalse(ts.try_prepare_trajectory(100000, hit, target, cache, .1, 999))
            self.assertFalse(cache.valid)
            with self.assertRaisesRegex(AssertionError, "prepared by its consumer"):
                ts.evaluate_trajectory(100000, hit, target, cache, .1)
            ts.complete_trajectory_refresh(100000, hit, target, cache)
            self.assertTrue(cache.valid)
            self.assertAlmostEqual(ts.evaluate_trajectory(100000, hit, target, cache, .1).to_float(), 2.9, places=6)
            ts.prepare_group(100000, 1.1)
            with patch.object(ts, "_target_from_anchor", side_effect=AssertionError("cold work during rolling reuse")):
                self.assertTrue(ts.try_prepare_trajectory(100000, hit, target, cache, 1.1, 999))
            self.assertAlmostEqual(ts.evaluate_trajectory(100000, hit, target, cache, 1.1).to_float(), 1.9, places=6)

    def test_storage_rounded_debug_time_does_not_skip_group_update(self):
        with TimelineFixture([RefMarker(0, 1)]) as fixture:
            now = 3 + 1 / 10
            target = ts.locate_target(100000, 4)
            ts.prepare_group(100000, now)
            fixture.group.last_updated = struct.unpack("f", struct.pack("f", now))[0]
            self.assertNotEqual(fixture.group.last_updated, now)
            ts.prepare_trajectory(100000, 4, target, empty_cache(), now, 999)
            with patch.object(ts, "_locate_frame", wraps=ts._locate_frame) as locate:
                ts.prepare_group(100000, now)
                self.assertEqual(locate.call_count, 1)
            self.assertFalse(ts.prepared_time_matches(now, now + 0.001))

    def test_adjacent_run_rebase_and_certificate_reset(self):
        records = [RefMarker(i / 8, 1, style=i % 2) for i in range(301)]
        with TimelineFixture(records) as fixture:
            for hit in [-1, 19.9, 40]:
                target = ts.locate_target(100000, hit)
                cache = empty_cache()
                ts.prepare_group(100000, 0.01)
                ts.prepare_trajectory(100000, hit, target, cache, 0.01, 999)
                for step in range(1, 300):
                    now = step / 8 + 0.01
                    ts.prepare_group(100000, now)
                    with patch.object(ts, "_target_from_anchor", wraps=ts._target_from_anchor) as queries:
                        ts.prepare_trajectory(100000, hit, target, cache, now, 999)
                        self.assertEqual(queries.call_count, 0)
                    result = ts.evaluate_trajectory(100000, hit, target, cache, now, accurate=True)
                    expected = float(fixture.oracle.distance(now, hit))
                    self.assertLessEqual(abs(result.to_float() - expected), result.absolute_error().to_float() + 1e-12)
                    self.assertTrue(result.div(AccurateScalar.of(.0035)).error_at_most(1e-4))
                cache.value.error = 0.01
                ts.prepare_group(100000, 37.51)
                with patch.object(ts, "_target_from_anchor", wraps=ts._target_from_anchor) as queries:
                    ts.prepare_trajectory(100000, hit, target, cache, 37.51, 999)
                    if hit != 40:
                        self.assertGreater(queries.call_count, 0)
                self.assertTrue(cache.value.error_at_most(1e-7))

    def test_shared_curve_all_eases_and_signed_speed(self):
        for ease in range(6):
            for first, last in [(0.05, 8), (8, 0.05), (-3, 2), (0, 0)]:
                with self.subTest(ease=ease, first=first, last=last), TimelineFixture([
                    RefMarker(0.125, first, ease=ease), RefMarker(10.375, last),
                ]) as fixture:
                    hit = 10.5
                    target = ts.locate_target(100000, hit)
                    cache = empty_cache()
                    for now in [0.125, 0.126, 2, 5.249, 5.25, 5.251, 9.5, 10.374]:
                        ts.prepare_group(100000, now)
                        ts.prepare_trajectory(100000, hit, target, cache, now, 999)
                        with patch.object(ts, "_integral", side_effect=AssertionError("per-note easing")):
                            result = ts.evaluate_trajectory(100000, hit, target, cache, now)
                        expected = float(fixture.oracle.distance(now, hit))
                        self.assertAlmostEqual(result.to_float(), expected, delta=max(1e-9, abs(expected) * 1e-11))

    def test_balanced_prefix_certifies_late_near_hit(self):
        records = [RefMarker(1800 * i / 512, 1) for i in range(513)]
        with TimelineFixture(records):
            now, hit = 1799.9995, 1800.0005
            target = ts.locate_target(100000, hit)
            cache = empty_cache()
            ts.prepare_group(100000, now)
            ts.prepare_trajectory(100000, hit, target, cache, now, 999)
            result = ts.evaluate_trajectory(100000, hit, target, cache, now, accurate=True)
            self.assertAlmostEqual(result.to_float(), hit - now, places=10)
            self.assertTrue(result.div(AccurateScalar.of(0.0035)).error_at_most(1e-4))

    def test_published_cache_checks_entire_run_amplification(self):
        records = [RefMarker(0, 0.05, style=1), RefMarker(1, 8, style=1), RefMarker(2, 0.05), RefMarker(3, 1)]
        with TimelineFixture(records):
            target = ts.locate_target(100000, 4)
            cache = empty_cache()

            def query(group, anchor, hit_time, target, published=False):
                return AccurateScalar(0.5, 0, 1, 1e-8 if published else 0)

            with patch.object(ts, "_target_from_anchor", side_effect=query) as queries:
                ts.prepare_group(100000, 0)
                ts.prepare_trajectory(100000, 4, target, cache, 0, 999, distance_tolerance=1e-6)
                self.assertEqual(queries.call_count, 2)
                self.assertEqual(cache.value.error, 0)

    def test_subnormal_allowance_rejects_inexact_publication(self):
        records = [RefMarker(0, 1e-40, style=1), RefMarker(1, 1, style=1), RefMarker(2, 1e-40)]
        with TimelineFixture(records):
            target = ts.locate_target(100000, 3)
            cache = empty_cache()

            def query(group, anchor, hit_time, target, published=False):
                return AccurateScalar(0.5, 0, -200, 1e-20 if published else 0)

            ts.prepare_group(100000, 0)
            with patch.object(ts, "_target_from_anchor", side_effect=query) as queries:
                ts.prepare_trajectory(100000, 3, target, cache, 0, 999)
                self.assertEqual(queries.call_count, 2)
                self.assertEqual(cache.value.error, 0)

    def test_cached_future_same_past_and_seeks(self):
        records = [
            RefMarker(0, 1, ease=1),
            RefMarker(1, 3, ease=2),
            RefMarker(2, 2, ease=4, style=1),
            RefMarker(3, 0.5, ease=5, style=1),
            RefMarker(4, 4, ease=3),
            RefMarker(5, 1),
        ]
        with TimelineFixture(records) as fixture:
            for h in [-1, 0, 1.25, 2, 3.7, 4, 6]:
                target = ts.locate_target(100000, h)
                cache = empty_cache()
                for now in [-2, 0, 0.5, 1, 2, 2.8, 4, 6, 3.2, 0.3]:
                    ts.prepare_group(100000, now)
                    ts.prepare_trajectory(100000, h, target, cache, now, target_ref=999)
                    actual = ts.evaluate_trajectory(100000, h, target, cache, now, accurate=True).to_float()
                    expected = float(fixture.oracle.distance(now, h))
                    self.assertAlmostEqual(actual, expected, delta=max(1e-9, abs(expected) * 1e-11))

    def test_internal_markers_do_not_refresh_and_parallel_does_not_query(self):
        records = [RefMarker(i, i + 1, ease=i % 6) for i in range(8)] + [RefMarker(8, 1, style=1), RefMarker(9, 2)]
        with TimelineFixture(records):
            target = ts.locate_target(100000, 10)
            cache = empty_cache()
            ts.prepare_group(100000, 0.1)
            ts.prepare_trajectory(100000, 10, target, cache, 0.1, 999)
            with patch.object(ts, "_target_from_anchor", side_effect=AssertionError("unnecessary cache refresh")):
                for now in [0.2, 1.5, 3.1, 7.5, 1.1]:
                    ts.prepare_group(100000, now)
                    ts.prepare_trajectory(100000, 10, target, cache, now, 999)
                    with patch.object(ts, "_range_transfer", side_effect=AssertionError("parallel range query")):
                        ts.evaluate_trajectory(100000, 10, target, cache, now)

    def test_group_steady_frame_uses_current_event_and_dense_ties_seek(self):
        records = [RefMarker(0, 1), *[RefMarker(1, 1, style=i % 2) for i in range(40)], RefMarker(2, 1)]
        with TimelineFixture(records) as fixture:
            ts.prepare_group(100000, 0.1)
            with patch.object(ts, "locate_time", side_effect=AssertionError("steady-frame tree lookup")):
                ts.prepare_group(100000, 0.2)
            with patch.object(ts, "locate_time", wraps=ts.locate_time) as locate:
                ts.prepare_group(100000, 1)
                self.assertEqual(locate.call_count, 1)
                self.assertEqual(fixture.group.current_event, 41)

    def test_target_metadata_does_not_register_an_inactive_consumer(self):
        with TimelineFixture([RefMarker(0, 1)]) as fixture:
            self.assertFalse(fixture.group.used)
            target = ts.locate_target(100000, 1)
            self.assertFalse(fixture.group.used)
            with patch.object(ts.runtime, "is_preprocessing", return_value=True):
                ts.register_group_window(100000, -.5, 1)
            self.assertTrue(fixture.group.used)
            with self.assertRaisesRegex(AssertionError, "must update before"):
                ts.prepare_trajectory(100000, 1, target, empty_cache(), 0, 999)

    def test_raw_microstate_end_cache(self):
        with TimelineFixture([RefMarker(0, 1), RefMarker(1, 2, style=1), RefMarker(1, 1), RefMarker(2, 1)]) as fixture:
            target = ts.locate_target(100000, 1)
            cache = empty_cache()
            ts.prepare_group(100000, 0.5)
            ts.prepare_trajectory(100000, 1, target, cache, 0.5, 999)
            self.assertEqual(cache.anchor_ref, 2)
            self.assertAlmostEqual(
                ts.evaluate_trajectory(100000, 1, target, cache, 0.5, True).to_float(),
                float(fixture.oracle.distance(0.5, 1)),
            )

    def test_slot_ledgers(self):
        from sekai.play.timescale import TimescaleChange, TimescaleGroup
        from sekai.watch.timescale import WatchTimescaleChange, WatchTimescaleGroup

        self.assertEqual(ts.TargetPosition._size_(), 1)
        self.assertEqual(ts.TrajectoryCache._size_(), 9)
        for cls, data, shared in [
            (TimescaleChange, 32, 31),
            (WatchTimescaleChange, 32, 31),
            (TimescaleGroup, 12, 32),
            (WatchTimescaleGroup, 12, 32),
        ]:
            cls._init_fields()
            self.assertEqual(
                sum(f.type._size_() for f in [*cls._imported_fields_.values(), *cls._data_fields_.values()]), data
            )
            self.assertEqual(sum(f.type._size_() for f in cls._shared_memory_fields_.values()), shared)


if __name__ == "__main__":
    unittest.main()
