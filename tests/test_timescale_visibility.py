# ruff: noqa: PT009
"""Visibility tests use the independent Decimal trajectory oracle."""

import unittest
from contextlib import ExitStack
from math import inf
from types import SimpleNamespace
from unittest.mock import patch

from sonolus.script.archetype import PlayArchetype, entity_data, imported
from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.interval import Interval

from sekai.lib import timescale_visibility as visibility
from sekai.lib.timescale_math import AccurateScalar
from sekai.play.timescale import TimescaleChange, TimescaleGroup
from tests.test_timescale_timeline import TimelineFixture
from tests.timescale_reference import RefMarker, RefTimeline, visibility_island_markers
from tests.timescale_vm import compile_probe


def _identity_distance(group, now, hit):
    return AccurateScalar.of(hit).sub(AccurateScalar.of(now))


def _identity_event(group, now):
    return 0


def _identity_speed(index, time, half=0):
    return AccurateScalar.of(1.0)


def _identity_piece(source, start, latest):
    return latest


def _identity_skip(sources, start, latest, low, high):
    return start


class VisibilityProbe(PlayArchetype):
    hit: float = imported()
    earliest: float = imported()
    latest: float = imported()
    spawn_result: visibility.SpawnResult = entity_data()

    def preprocess(self):
        sources = VarArray[visibility.VisibilitySource, Dim[4]].new()
        sources.append(visibility.VisibilitySource(0, self.hit, 1.0, 0.0, 0.0, False))
        self.spawn_result = visibility.first_visible_result(sources, 0.0, 1.0, self.earliest, self.latest)


class ClockMidpointProbe(PlayArchetype):
    a: float = imported()
    b: float = imported()
    t: float = imported()
    side: int = entity_data()

    def preprocess(self):
        self.side = visibility._clock_midpoint_side(self.t, self.a, self.b)


class VisibilityTests(unittest.TestCase):
    def production_context(self, records):
        fixture = self.enterContext(TimelineFixture(records))
        self.enterContext(
            patch.object(
                visibility, "timescale_change_archetype", return_value=SimpleNamespace(at=fixture.markers.__getitem__)
            )
        )
        self.enterContext(
            patch.object(
                visibility, "timescale_group_archetype", return_value=SimpleNamespace(at=lambda _: fixture.group)
            )
        )
        self.enterContext(patch.object(visibility, "Options", SimpleNamespace(disable_timescale=False)))
        return fixture

    def timeline_context(self, timelines):
        stack = ExitStack()
        self.addCleanup(stack.close)
        nodes = {}
        for group, timeline in timelines.items():
            for i, marker in enumerate(timeline.markers):
                index = group * 100_000 + i + 1
                next_index = index + 1 if i + 1 < len(timeline.markers) else 0
                nodes[index] = SimpleNamespace(
                    timescale=float(marker.speed),
                    timescale_ease=int(marker.ease),
                    transition_style=int(marker.style),
                    event_start=float(marker.time),
                    event_end=float(timeline.markers[i + 1].time) if next_index else inf,
                    next_ref=SimpleNamespace(index=next_index),
                    ordinal=i,
                )

        def locate(group, t):
            if group == 0:
                return 0
            local = timelines[group].locate_time(t)
            return group * 100_000 + local + 1 if local >= 0 else 0

        def distance(group, t, h):
            result = h - t if group == 0 else float(timelines[group].distance(t, h))
            return AccurateScalar.of(result)

        groups = {
            group: SimpleNamespace(
                first_ref=SimpleNamespace(index=group * 100_000 + 1 if timeline.markers else 0),
                root=0,
                mode=int(timeline.hybrid),
            )
            for group, timeline in timelines.items()
        }
        stack.enter_context(patch.object(visibility, "locate_time", side_effect=locate))
        stack.enter_context(patch.object(visibility, "distance_between", side_effect=distance))
        stack.enter_context(
            patch.object(visibility, "timescale_change_archetype", return_value=SimpleNamespace(at=nodes.get))
        )
        stack.enter_context(
            patch.object(visibility, "timescale_group_archetype", return_value=SimpleNamespace(at=groups.get))
        )
        stack.enter_context(patch.object(visibility, "Options", SimpleNamespace(disable_timescale=False)))
        return nodes, groups

    def sources(self, *items):
        result = VarArray[visibility.VisibilitySource, Dim[4]].new()
        for item in items:
            result.append(item)
        return result

    def source(self, group=1, hit=3.0, preempt=1.0, offset_min=0.0, offset_max=0.0, clamp=False):
        return visibility.VisibilitySource(group, hit, preempt, offset_min, offset_max, clamp)

    def search(self, source, low=0.0, high=1.0, earliest=-2.0, latest=3.0):
        return visibility.first_visible(self.sources(source), 1.0 - high, 1.0 - low, earliest, latest)

    def test_identity_first_entry(self):
        self.timeline_context({})
        actual = self.search(self.source(0), high=1.0)
        self.assertLessEqual(actual, 2.0)
        self.assertGreaterEqual(actual, 2.0 - 0.00025)

    def test_interior_visibility_island_precedes_endpoint_entry(self):
        timeline = RefTimeline(visibility_island_markers())
        self.timeline_context({1: timeline})
        actual = self.search(self.source(), high=1.9, earliest=0.0)
        self.assertGreater(actual, 1.0)
        self.assertLess(actual, 4.0 / 3.0)
        self.assertGreaterEqual(float(timeline.distance(actual, 3.0)), 1.9 - 1e-8)
        self.assertLessEqual(float(timeline.distance(actual + 0.00025, 3.0)), 1.9 + 1e-7)

    def test_tangency_is_not_missed(self):
        self.timeline_context({1: RefTimeline(visibility_island_markers())})
        actual = self.search(self.source(), high=50.0 / 27.0, earliest=0.0)
        self.assertLessEqual(actual, 4.0 / 3.0)
        self.assertGreaterEqual(actual, 4.0 / 3.0 - 0.001)

    def test_skip_over_region_does_not_manufacture_a_crossing(self):
        self.timeline_context({1: RefTimeline([RefMarker(0, 1), RefMarker(1, 1, skip=10)])})
        self.assertEqual(self.search(self.source(hit=2.0), low=4.0, high=5.0, latest=2.0), inf)

    def test_skip_into_region_tests_completed_right_state(self):
        self.timeline_context({1: RefTimeline([RefMarker(0, 1), RefMarker(1, 1, skip=10)])})
        self.assertEqual(self.search(self.source(hit=2.0), high=1.1, latest=2.0), 1.0)

    def test_same_time_scroll_intermediate_state_is_not_visible(self):
        self.timeline_context(
            {
                1: RefTimeline(
                    [
                        RefMarker(0, 1, style=1),
                        RefMarker(1, 0.1, style=1),
                        RefMarker(1, 1),
                    ]
                )
            }
        )
        actual = self.search(self.source(), high=0.5)
        self.assertLessEqual(actual, 2.5)
        self.assertGreaterEqual(actual, 2.5 - 0.00025)

    def test_signed_quadratic_reversal_uses_interior_hull(self):
        timeline = RefTimeline([RefMarker(0, 2, ease=2), RefMarker(2, -2)])
        self.timeline_context({1: timeline})
        source = self.source(hit=3.0)
        actual = self.search(source, low=-1.0, high=-0.9, earliest=0.0)
        self.assertNotEqual(actual, inf)
        self.assertLessEqual(float(timeline.distance(actual + 0.00025, 3.0)), -0.9 + 1e-6)

    def test_opposite_side_endpoints_spawn_segment_interior(self):
        self.timeline_context({})
        sources = self.sources(self.source(0, hit=-10.0), self.source(0, hit=10.0))
        self.assertEqual(visibility.first_visible(sources, 0.0, 1.0, -2.0, 3.0), -2.0)

    def test_offsets_expand_the_actual_progress_region(self):
        self.timeline_context({})
        actual = self.search(self.source(0, offset_min=-2.0, offset_max=-2.0), high=1.0)
        self.assertLessEqual(actual, 0.0)
        self.assertGreaterEqual(actual, -0.00025)

    def test_noop_final_event_and_stop(self):
        self.timeline_context({1: RefTimeline([RefMarker(-3, 0)])})
        self.assertEqual(self.search(self.source(), high=1.0), -2.0)

    def test_head_clamp_partitions_hit_boundary(self):
        self.timeline_context({})
        source = self.source(0, hit=1.0, clamp=True)
        self.assertEqual(self.search(source, low=-1.0, high=-0.5, earliest=0.0, latest=3.0), inf)

    def test_result_distinguishes_interior_from_resolution_bracket(self):
        self.timeline_context({})
        sources = self.sources(self.source(0))
        interior = visibility.first_visible_result(sources, 0.0, 1.0, 2.5, 3.0)
        self.assertEqual(interior.status, visibility.SpawnStatus.VERIFIED_ENTRY)
        self.assertEqual(interior.reason, visibility.SpawnReason.INTERIOR_POINT)
        crossing = visibility.first_visible_result(sources, 0.0, 1.0, 0.0, 3.0)
        self.assertEqual(crossing.status, visibility.SpawnStatus.POSSIBLE_ENTRY)
        self.assertEqual(crossing.reason, visibility.SpawnReason.TIME_RESOLUTION)
        self.assertLessEqual(crossing.bracket.start, 2.0)
        self.assertGreaterEqual(crossing.bracket.end, 2.0)

    def test_outward_search_margin_does_not_verify_entry(self):
        self.timeline_context({})
        for hit in (0.90000001, 0.09999999):
            with self.subTest(hit=hit):
                self.assertFalse(0.1 <= 1.0 - hit <= 0.9)
                result = visibility.first_visible_result(self.sources(self.source(0, hit=hit)), 0.1, 0.9, 0.0, 0.0)
                self.assertEqual(result.time, 0.0)
                self.assertEqual(result.status, visibility.SpawnStatus.POSSIBLE_ENTRY)
                self.assertEqual(result.reason, visibility.SpawnReason.HULL_OR_ROUNDING)

    def test_work_limit_returns_current_unexcluded_bracket(self):
        self.timeline_context({})
        with patch.object(visibility, "MAX_CELL_REFINEMENTS", 0):
            result = visibility.first_visible_result(self.sources(self.source(0)), 0.0, 1.0, 1.0, 3.0)
        self.assertEqual(result.time, 1.0)
        self.assertEqual(result.status, visibility.SpawnStatus.POSSIBLE_ENTRY)
        self.assertEqual(result.reason, visibility.SpawnReason.WORK_LIMIT)
        self.assertEqual(result.bracket.end, 3.0)

    def test_subdivision_does_not_repeat_timeline_distance_queries(self):
        self.timeline_context({})
        with patch.object(visibility, "distance_between", wraps=visibility.distance_between) as query:
            self.search(self.source(0), high=1.0)
        self.assertLessEqual(query.call_count, 1)

    def test_signed_subtree_skips_only_proved_offscreen_history(self):
        timeline = RefTimeline([RefMarker(0, 1), RefMarker(1, 1), RefMarker(2, 1), RefMarker(3, 1)])
        nodes, groups = self.timeline_context({1: timeline})
        for i in range(4):
            node = nodes[100_001 + i]
            node.tree_left = 0
            node.tree_right = 0
            node.suffix_r_min = AccurateScalar.of(-1.0)
            node.suffix_r_max = AccurateScalar.of(1.0)
            node.suffix_b_max = AccurateScalar.of(1.0)
        groups[1].root = 100_002
        root = nodes[100_002]
        root.tree_left = 100_001
        root.tree_right = 100_003
        root.suffix_r_min = AccurateScalar.of(-3.0)
        root.suffix_r_max = AccurateScalar.of(3.0)
        sources = self.sources(self.source(hit=10.0))
        self.assertEqual(visibility._skip_excluded_subtree(sources, 0.0, 10.0, 0.0, 1.0), 3.0)

    def test_subtree_does_not_use_incomplete_same_time_endpoint(self):
        timeline = RefTimeline([RefMarker(0, 1), RefMarker(1, 1, skip=10), RefMarker(1, 1, skip=-10)])
        nodes, groups = self.timeline_context({1: timeline})
        groups[1].root = 100_001
        root = nodes[100_001]
        root.tree_left = 0
        root.tree_right = 0
        root.suffix_r_min = AccurateScalar.of(-11)
        root.suffix_r_max = AccurateScalar.of(11)
        root.suffix_b_max = AccurateScalar.of(11)
        self.assertEqual(
            visibility._skip_excluded_subtree(self.sources(self.source(hit=100)), 0.0, 100.0, 0.0, 1.0), 0.0
        )

    def test_compiled_identity_search_preserves_record_branches(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(visibility, "distance_between", _identity_distance))
            stack.enter_context(patch.object(visibility, "locate_time", _identity_event))
            stack.enter_context(patch.object(visibility, "_speed_at", _identity_speed))
            stack.enter_context(patch.object(visibility, "_next_piece_end", _identity_piece))
            stack.enter_context(patch.object(visibility, "_skip_excluded_subtree", _identity_skip))
            probe = compile_probe(VisibilityProbe, archetypes=[VisibilityProbe, TimescaleGroup, TimescaleChange])
        for precision in ("binary32", "binary64"):
            result, _ = probe.run(precision=precision, hit=3.0, earliest=2.5, latest=3.0, instruction_limit=5_000_000)
            self.assertEqual(result["spawn_result"][0], 2.5)
            self.assertEqual(result["spawn_result"][1], visibility.SpawnStatus.VERIFIED_ENTRY)
            crossing, _ = probe.run(precision=precision, hit=3.0, earliest=0.0, latest=3.0, instruction_limit=5_000_000)
            self.assertLessEqual(crossing["spawn_result"][0], 2.0)
            self.assertGreaterEqual(crossing["spawn_result"][0], 1.999)
            self.assertEqual(crossing["spawn_result"][1], visibility.SpawnStatus.POSSIBLE_ENTRY)
            outside, _ = probe.run(precision=precision, hit=1.0 + 2.0**-23, earliest=0.0, latest=0.0)
            self.assertEqual(outside["spawn_result"][0], 0.0)
            self.assertEqual(outside["spawn_result"][1], visibility.SpawnStatus.POSSIBLE_ENTRY)
            self.assertEqual(outside["spawn_result"][4], visibility.SpawnReason.HULL_OR_ROUNDING)

    def test_unrepresentable_ease_midpoint_encloses_both_continuations(self):
        tick = 2.0**-13
        a = 1800.0
        b = a + 9 * tick
        left = a + 4 * tick
        right = a + 5 * tick
        for style in (0, 1):
            for easing in (4, 5):
                with self.subTest(style=style, easing=easing):
                    timeline = RefTimeline([RefMarker(a, 8.0, ease=easing, style=style), RefMarker(b, 0.05)])
                    self.timeline_context({1: timeline})
                    controls = visibility._source_controls(self.source(hit=b + 1), left, right)
                    for i in range(17):
                        fraction = AccurateScalar.of(i / 16)
                        p01 = visibility._mix(controls.b0, controls.b1, fraction)
                        p12 = visibility._mix(controls.b1, controls.b2, fraction)
                        p23 = visibility._mix(controls.b2, controls.b3, fraction)
                        p012 = visibility._mix(p01, p12, fraction)
                        p123 = visibility._mix(p12, p23, fraction)
                        value = visibility._mix(p012, p123, fraction)
                        actual = float(timeline.distance(left + (right - left) * i / 16, b + 1))
                        self.assertLessEqual(value.lower_bound().to_float(), actual)
                        self.assertGreaterEqual(value.upper_bound().to_float(), actual)

    def test_compiled_midpoint_comparison_retains_half_clock_tick(self):
        probe = compile_probe(ClockMidpointProbe)
        tick = 2.0**-13
        for offset, side in ((4, -1), (5, 1)):
            result, _ = probe.run(precision="binary32", a=1800.0, b=1800.0 + 9 * tick, t=1800.0 + offset * tick)
            self.assertEqual(result["side"], (side,))

    def test_production_positive_tree_prunes_chronological_history(self):
        self.production_context([RefMarker(i, 1, style=i % 2) for i in range(128)])
        with patch.object(visibility, "distance_between", wraps=visibility.distance_between) as query:
            result = visibility.first_visible_result(self.sources(self.source(100000, hit=127.0)), 0, 1, -2, 127)
        self.assertLessEqual(result.time, 126.0)
        self.assertGreaterEqual(result.time, 125.998)
        self.assertLess(result.cells, 20)
        self.assertLess(query.call_count, 40)

    def test_huge_hybrid_distance_is_pruned_without_scalar_conversion(self):
        self.production_context([RefMarker(i, 1 if i % 2 == 0 else 2, style=i % 2) for i in range(301)])
        self.assertGreater(visibility.distance_between(100000, 0, 301).exponent, 128)
        result = visibility.first_visible_result(self.sources(self.source(100000, hit=301.0)), 0, 1, -2, 301)
        self.assertLessEqual(result.time, 300.0)
        self.assertGreaterEqual(result.time, 299.998)

    def test_positive_spawn_cursor_handles_sorted_unsorted_and_changed_bounds(self):
        fixture = self.production_context([RefMarker(i, 1, style=1) for i in range(12)])
        with (
            patch.object(visibility, "conservative_progress_bounds", return_value=Interval(0.0, 1.0)),
            patch.object(visibility, "first_visible_result", wraps=visibility.first_visible_result) as search,
        ):
            first = visibility.get_sources_visual_spawn_time(self.sources(self.source(100000, hit=5.0)), 5.0)
            self.assertEqual(search.call_args.args[3], -2.0)
            visibility.get_sources_visual_spawn_time(self.sources(self.source(100000, hit=6.0)), 6.0)
            self.assertEqual(search.call_args.args[3], first)
            visibility.get_sources_visual_spawn_time(self.sources(self.source(100000, hit=4.0)), 4.0)
            self.assertEqual(search.call_args.args[3], -2.0)
            enlarged = visibility.get_sources_visual_spawn_time(
                self.sources(self.source(100000, hit=7.0, preempt=2.0)), 7.0
            )
            self.assertEqual(search.call_args.args[3], -2.0)
            visibility.get_sources_visual_spawn_time(self.sources(self.source(100000, hit=8.0, preempt=0.5)), 8.0)
            self.assertEqual(search.call_args.args[3], enlarged)
            previous_target = fixture.group.last_spawn_target
            absent = visibility.get_sources_visual_spawn_time(self.sources(self.source(100000, hit=10.0)), -3.0)
            self.assertEqual(absent, inf)
            self.assertEqual(fixture.group.last_spawn_target, previous_target)

    def test_all_quadratic_piece_controls_enclose_oracle(self):
        for style in (0, 1):
            for easing in range(6):
                with self.subTest(style=style, easing=easing):
                    timeline = RefTimeline([RefMarker(0, 3, ease=easing, style=style), RefMarker(2, 1)])
                    self.timeline_context({1: timeline})
                    source = self.source()
                    for start, end in ((0.0, 1.0), (1.0, 2.0)):
                        controls = visibility._source_controls(source, start, end)
                        values = [
                            controls.b0.to_float(),
                            controls.b1.to_float(),
                            controls.b2.to_float(),
                            controls.b3.to_float(),
                        ]
                        for i in range(17):
                            t = start + (end - start) * i / 16
                            # NONE ends with a separate scroll jump, not its continuous extension.
                            if i == 16 and end == 2.0 and easing == 0 and style == 1:
                                continue
                            distance = float(timeline.distance(t, 3.0))
                            self.assertGreaterEqual(distance, min(values) - 1e-9)
                            self.assertLessEqual(distance, max(values) + 1e-9)


if __name__ == "__main__":
    unittest.main()
