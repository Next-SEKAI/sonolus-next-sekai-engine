# ruff: noqa: PT009
"""Check conservative spawn times across speed changes and skips."""

import unittest
from math import inf
from types import SimpleNamespace
from unittest.mock import patch

from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.interval import Interval

from sekai.lib import timescale_visibility as visibility
from sekai.lib.timescale import TargetPosition
from sekai.lib.timescale_math import TimePosition
from tests.timescale_reference import RefMarker, RefTimeline, visibility_island_markers


class VisibilityTests(unittest.TestCase):
    def timeline(self, markers=()):
        oracle = RefTimeline(markers)
        nodes = {
            i + 1: SimpleNamespace(
                timescale=float(marker.speed),
                timescale_ease=int(marker.ease),
                transition_style=int(marker.style),
                event_start=float(marker.time),
                event_end=float(markers[i + 1].time) if i + 1 < len(markers) else inf,
                next_ref=SimpleNamespace(index=i + 2 if i + 1 < len(markers) else 0),
            )
            for i, marker in enumerate(markers)
        }
        group = SimpleNamespace(
            first_ref=SimpleNamespace(index=1 if markers else 0),
            has_scroll=oracle.hybrid,
            spawn_cursor_valid=False,
            monotone_targets=all(marker.speed >= 0 and marker.skip >= 0 for marker in markers),
        )
        self.enterContext(patch.object(visibility, "Options", SimpleNamespace(disable_timescale=False)))
        self.enterContext(
            patch.object(visibility, "timescale_change_archetype", return_value=SimpleNamespace(at=nodes.get))
        )
        self.enterContext(
            patch.object(visibility, "timescale_group_archetype", return_value=SimpleNamespace(at=lambda _: group))
        )
        self.enterContext(
            patch.object(
                visibility, "locate_time_from", side_effect=lambda g, t, ref: oracle.locate_time(t) + 1 if g else 0
            )
        )
        self.enterContext(
            patch.object(
                visibility,
                "distance_to_target",
                side_effect=lambda g, ref, t, target, h: float(oracle.distance(t, h)) if g else h - t,
            )
        )
        self.enterContext(
            patch.object(
                visibility,
                "locate_target",
                side_effect=lambda g, h: TargetPosition(oracle.locate_time(h) + 1 if g else 0, TimePosition.of(h)),
            )
        )
        return oracle, group

    def sources(self, *items):
        result = VarArray[visibility.VisibilitySource, Dim[4]].new()
        for item in items:
            result.append(item)
        return result

    def source(self, group=1, hit=3.0, preempt=1.0, offset_min=0.0, offset_max=0.0, clamp=False):
        return visibility.VisibilitySource(group, hit, preempt, offset_min, offset_max, clamp)

    def search(self, source, distance_low=0.0, distance_high=1.0, earliest=-2.0, latest=3.0):
        return visibility.first_visible(self.sources(source), 1 - distance_high, 1 - distance_low, earliest, latest)

    def test_identity_and_existing_early_leniency(self):
        self.timeline()
        result = self.search(self.source(0))
        self.assertLessEqual(result, 2.0)
        self.assertGreater(result, 1.97)
        with patch.object(visibility, "conservative_progress_bounds", return_value=Interval(-3, 6)):
            result = visibility.get_sources_visual_spawn_time(self.sources(self.source(0, hit=10)), 10)
        self.assertLessEqual(result, 6.0)
        self.assertGreater(result, 5.97)

    def test_scroll_interior_island_and_tangency_are_not_missed(self):
        self.timeline(visibility_island_markers())
        for ceiling in (1.9, 50 / 27):
            result = self.search(self.source(), distance_high=ceiling, earliest=0)
            self.assertGreater(result, 1.0)
            self.assertLessEqual(result, 4 / 3)

    def test_all_eases_allow_local_subdivision_without_requerying(self):
        for easing in range(6):
            with self.subTest(easing=easing):
                oracle, _ = self.timeline([RefMarker(0, 2, ease=easing), RefMarker(2, 1)])
                with patch.object(visibility, "distance_to_target", wraps=visibility.distance_to_target) as query:
                    result = self.search(self.source(), distance_high=2, earliest=0)
                self.assertLessEqual(result, 2)
                self.assertGreater(float(oracle.distance(result, 3)), 1.9)
                self.assertLessEqual(query.call_count, 2)

    def test_signed_reversal_and_zero_speed_need_no_division(self):
        self.timeline([RefMarker(0, 1), RefMarker(1, -1), RefMarker(2, 1)])
        result = self.search(self.source(), distance_low=0.2, distance_high=0.3, earliest=0)
        self.assertLessEqual(result, 0.7)
        self.assertGreater(result, 0.67)
        self.timeline([RefMarker(0, 0), RefMarker(2, 1)])
        self.assertEqual(self.search(self.source(), earliest=0), 0)

    def test_jump_over_region_does_not_create_visibility(self):
        self.timeline([RefMarker(0, 1), RefMarker(1, 1, skip=10)])
        self.assertEqual(self.search(self.source(hit=2), distance_low=4, distance_high=5, latest=2), inf)
        result = self.search(self.source(hit=2), distance_high=1.1, latest=2)
        self.assertAlmostEqual(result, 0.99)

    def test_same_time_intermediate_scroll_state_is_not_rendered(self):
        self.timeline([RefMarker(0, 1, style=1), RefMarker(1, 0.1, style=1), RefMarker(1, 1)])
        result = self.search(self.source(hit=2), distance_low=0.45, distance_high=0.55, earliest=0, latest=2)
        self.assertGreater(result, 1.4)
        self.assertLessEqual(result, 1.45)

    def test_offsets_clamped_attachments_and_segment_interiors(self):
        self.timeline()
        shifted = self.search(self.source(0, offset_min=-2, offset_max=-2))
        self.assertLessEqual(shifted, 0)
        self.assertGreater(shifted, -0.03)
        clamped = self.source(0, hit=1, clamp=True)
        self.assertEqual(self.search(clamped, distance_low=-1, distance_high=-0.5, earliest=0, latest=3), inf)
        sources = self.sources(self.source(0, hit=-10), self.source(0, hit=10))
        self.assertEqual(visibility.first_visible(sources, 0, 1, 0, 1), 0)

    def test_positive_cursor_and_unsorted_or_changed_bounds(self):
        _, group = self.timeline([RefMarker(0, 1, style=1), RefMarker(20, 1)])
        with patch.object(visibility, "conservative_progress_bounds", return_value=Interval(0, 1)):
            with patch.object(visibility, "first_visible", wraps=visibility.first_visible) as search:
                previous = visibility.get_sources_visual_spawn_time(self.sources(self.source(hit=5)), 5)
                current = visibility.get_sources_visual_spawn_time(self.sources(self.source(hit=6)), 6)
                self.assertEqual(search.call_args.args[3], previous)
                self.assertGreaterEqual(current, previous)
                visibility.get_sources_visual_spawn_time(self.sources(self.source(hit=4)), 4)
                self.assertEqual(search.call_args.args[3], -2)
                visibility.get_sources_visual_spawn_time(self.sources(self.source(hit=7, preempt=2)), 7)
                self.assertEqual(search.call_args.args[3], -2)
            self.assertTrue(group.spawn_cursor_valid)

    def test_nonfinite_distance_starts_early(self):
        self.timeline()
        for value in (inf, -inf, float("nan")):
            with patch.object(visibility, "distance_to_target", return_value=value):
                self.assertEqual(self.search(self.source(0), earliest=0), 0)

    def test_nonnegative_timescale_cursor_excludes_negative_speeds_and_skips(self):
        for speed, skip, reusable in ((0, 1, True), (-1, 0, False), (1, -1, False)):
            with self.subTest(speed=speed, skip=skip):
                _, group = self.timeline([RefMarker(0, 1), RefMarker(2, speed, skip=skip), RefMarker(4, 1)])
                self.assertEqual(group.monotone_targets, reusable)
                with (
                    patch.object(visibility, "conservative_progress_bounds", return_value=Interval(0, 1)),
                    patch.object(visibility, "first_visible", wraps=visibility.first_visible) as search,
                ):
                    previous = visibility.get_sources_visual_spawn_time(self.sources(self.source(hit=5)), 5)
                    visibility.get_sources_visual_spawn_time(self.sources(self.source(hit=6)), 6)
                    self.assertEqual(search.call_args.args[3], previous if reusable else -2)

    def test_each_target_is_located_once_per_search(self):
        self.timeline([RefMarker(i, 1) for i in range(20)])
        with patch.object(visibility, "locate_target", wraps=visibility.locate_target) as locate:
            self.search(self.source(hit=20), earliest=0, latest=20)
        self.assertEqual(locate.call_count, 1)

    def test_capped_distances_retain_their_useful_one_sided_bound(self):
        self.timeline()
        positive = visibility._distance_bounds(self.source(0), 0, 0, visibility.DISTANCE_LIMIT, 0, 1)
        negative = visibility._distance_bounds(self.source(0), 0, 0, -visibility.DISTANCE_LIMIT, 0, 1)
        self.assertGreater(positive.start, 1)
        self.assertEqual(positive.end, inf)
        self.assertEqual(negative.start, -inf)
        self.assertLess(negative.end, -1)


if __name__ == "__main__":
    unittest.main()
