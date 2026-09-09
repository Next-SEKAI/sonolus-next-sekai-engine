# ruff: noqa: PT009
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.interval import Interval

from sekai.lib import timescale
from sekai.lib import timescale_consumer as consumer
from sekai.lib.timescale import CacheKind, TargetPosition, TrajectoryCache
from sekai.lib.timescale_math import AccurateScalar
from sekai.lib.timescale_visibility import VisibilitySource


def ref(value=None, index=0):
    return SimpleNamespace(index=index, get=lambda: value)


def basic_note(index, hit_time, group=0, stage=None):
    return SimpleNamespace(
        index=index,
        target_time=hit_time,
        target_position=TargetPosition(0),
        timescale_group=ref(index=group),
        stage_ref=ref(stage, index=1 if stage is not None else 0),
        is_attached=False,
        visual_y_offset=0.0,
        native_progress_certified=False,
    )


def attached_note(head, tail, hit_time):
    note = basic_note(3, hit_time, group=3)
    note.is_attached = True
    note.attach_head_ref = ref(head, head.index)
    note.attach_tail_ref = ref(tail, tail.index)
    return note


class TimescaleConsumerTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.prepare = self.stack.enter_context(patch.object(consumer, "try_prepare_trajectory", return_value=True))
        self.complete = self.stack.enter_context(patch.object(consumer, "complete_trajectory_refresh"))
        self.evaluate = self.stack.enter_context(
            patch.object(
                consumer,
                "evaluate_trajectory",
                side_effect=lambda group, hit, target, cache, now, **kwargs: AccurateScalar.of(hit - now),
            )
        )
        self.stack.enter_context(patch.object(consumer, "group_preempt_time", side_effect=lambda group: max(group.index, 1)))
        self.stack.enter_context(patch.object(consumer, "conservative_progress_bounds", return_value=Interval(-3, 6)))
        self.first = +TrajectoryCache
        self.second = +TrajectoryCache

    def test_attached_group_window_includes_hide_group_and_inactive_anchors(self):
        head = basic_note(1, 1.0, group=1)
        tail = basic_note(2, 5.0, group=2)
        note = attached_note(head, tail, 3.0)
        with patch.object(consumer, "register_group_window") as register:
            consumer.register_note_group_window(note, -4.0, 8.0)
        self.assertEqual([call.args[0].index for call in register.call_args_list], [3, 1, 2])
        self.assertTrue(all(call.args[1:] == (-4.0, 8.0) for call in register.call_args_list))

    def test_invalid_group_windows_do_not_activate_groups(self):
        note = basic_note(1, 1.0)
        note.timescale_group = 1
        with (
            patch.object(timescale, "Options", SimpleNamespace(disable_timescale=False)),
            patch.object(timescale, "_require_group") as require,
        ):
            for start, end in ((float("inf"), 2), (0, -1), (0, float("inf"))):
                consumer.register_note_group_window(note, start, end)
        require.assert_not_called()

    def test_prepare_attachment_uses_consumer_caches_and_inactive_endpoint_groups(self):
        head = basic_note(1, 1.0, group=1)
        tail = basic_note(2, 5.0, group=2)
        note = attached_note(head, tail, 3.0)

        consumer.prepare_note_trajectories(note, self.first, self.second, 0.0)

        self.assertEqual(self.prepare.call_count, 2)
        self.assertIs(self.prepare.call_args_list[0].args[3], self.first)
        self.assertIs(self.prepare.call_args_list[1].args[3], self.second)
        self.assertEqual(self.prepare.call_args_list[0].args[-1], head.index)
        self.assertEqual(self.prepare.call_args_list[1].args[-1], tail.index)
        self.complete.assert_not_called()

    def test_prepare_ordinary_hit_needs_no_cold_dispatch(self):
        consumer.prepare_note_trajectories(basic_note(1, 3.0), self.first, self.second, 0.0)
        self.assertEqual(self.prepare.call_count, 1)
        self.complete.assert_not_called()

    def test_prepare_cold_dispatch_preserves_selected_cache_and_allowance(self):
        head = basic_note(1, 1.0, group=1)
        tail = basic_note(2, 5.0, group=2)
        tail.target_position.event_ref = 22
        note = attached_note(head, tail, 3.0)
        self.prepare.side_effect = [True, False]
        self.first.valid = True
        self.first.value @= AccurateScalar.of(17)
        self.second.value.hi = 0.125

        def complete(group, hit_time, target, cache):
            self.assertEqual(group, 2)
            self.assertEqual(hit_time, 5.0)
            self.assertEqual(target.event_ref, 22)
            self.assertEqual(cache.value.hi, 0.125)
            cache.value @= AccurateScalar.of(23)
            cache.valid = True

        self.complete.side_effect = complete
        consumer.prepare_note_trajectories(note, self.first, self.second, 0.0)
        self.assertEqual(self.complete.call_count, 1)
        self.assertEqual(self.first.value.to_float(), 17)
        self.assertEqual(self.second.value.to_float(), 23)
        self.assertTrue(self.second.valid)

    def test_prepare_cold_dispatch_refreshes_both_endpoints(self):
        note = attached_note(basic_note(1, 1.0, group=1), basic_note(2, 5.0, group=2), 3.0)
        self.prepare.return_value = False

        def complete(group, hit_time, target, cache):
            cache.value @= AccurateScalar.of(hit_time)
            cache.valid = True

        self.complete.side_effect = complete
        consumer.prepare_note_trajectories(note, self.first, self.second, 0.0)
        self.assertEqual(self.complete.call_count, 2)
        self.assertEqual(self.first.value.to_float(), 1)
        self.assertEqual(self.second.value.to_float(), 5)

    def test_prepare_cold_ordinary_needs_no_attachment_metadata(self):
        self.prepare.return_value = False

        def complete(group, hit_time, target, cache):
            self.assertEqual(group, 4)
            cache.value @= AccurateScalar.of(hit_time)
            cache.valid = True

        self.complete.side_effect = complete
        consumer.prepare_note_trajectories(basic_note(1, 7.0, group=4), self.first, self.second, 0.0)
        self.assertEqual(self.complete.call_count, 1)
        self.assertEqual(self.first.value.to_float(), 7)

    def test_native_identity_draw_avoids_scaled_evaluation(self):
        note = basic_note(1, 1.25)
        self.first.valid = True
        self.first.kind = CacheKind.IDENTITY
        self.assertAlmostEqual(consumer.note_draw_progress(note, self.first, self.second, 1), 0.75)
        self.evaluate.assert_not_called()

    def test_uniform_native_certificate_uses_full_offset_and_geometry_bounds(self):
        note = basic_note(1, 100)
        with patch.object(consumer, "note_offset_bounds", return_value=Interval(-2, 3)):
            self.assertTrue(consumer.certify_note_native_progress(note))
        with patch.object(consumer, "note_offset_bounds", return_value=Interval(0, 500)):
            self.assertFalse(consumer.certify_note_native_progress(note))
        with patch.object(consumer, "conservative_progress_bounds", return_value=Interval(-300, 6)):
            self.assertFalse(consumer.certify_note_native_progress(note))

    def test_uniform_native_certificate_bypasses_per_frame_error_calculation(self):
        note = basic_note(1, 1.25)
        note.native_progress_certified = True
        self.first.valid = True
        self.first.kind = CacheKind.IDENTITY
        with patch.object(consumer, "native_constant_progress", side_effect=AssertionError("Unneeded error calculation")):
            self.assertAlmostEqual(consumer.note_draw_progress(note, self.first, self.second, 1), 0.75)
        self.evaluate.assert_not_called()

    def test_native_wide_offscreen_draw_is_culled_before_conversion(self):
        note = basic_note(1, 100000)
        self.first.valid = True
        self.first.kind = CacheKind.IDENTITY
        with patch.object(consumer, "DynamicLayout", SimpleNamespace(progress_start=-3, progress_cutoff=6)):
            self.assertEqual(consumer.note_draw_progress(note, self.first, self.second, 1), -float("inf"))
        self.evaluate.assert_not_called()

    def test_attachment_normalizes_each_group_preempt_before_interpolation(self):
        note = attached_note(basic_note(1, 1.0, 1), basic_note(2, 5.0, 2), 3.0)

        progress = consumer.note_progress_value(note, self.first, self.second, 0.0).to_float()

        self.assertAlmostEqual(progress, 1 - (1 + 5 / 2) / 2)
        self.assertIs(self.evaluate.call_args_list[0].args[3], self.first)
        self.assertIs(self.evaluate.call_args_list[1].args[3], self.second)
        self.prepare.assert_not_called()

    def test_head_hit_clamps_and_changes_attachment_fraction(self):
        note = attached_note(basic_note(1, 1.0, 1), basic_note(2, 5.0, 2), 3.0)

        progress = consumer.note_progress_value(note, self.first, self.second, 2.0).to_float()

        self.assertAlmostEqual(progress, 0.5)
        self.evaluate.assert_called_once()
        self.assertEqual(self.evaluate.call_args.args[1], 5.0)

    def test_coincident_attachment_endpoints_preserve_clamped_fraction(self):
        note = attached_note(basic_note(1, 1.0), basic_note(2, 1.0), 1.0)

        self.assertEqual(consumer.note_progress_value(note, self.first, self.second, 1.0).to_float(), 1.0)

    def test_visual_offset_applies_after_attachment_interpolation(self):
        note = attached_note(basic_note(1, 1.0, 1), basic_note(2, 5.0, 2), 3.0)
        note.visual_y_offset = 0.25

        self.assertAlmostEqual(consumer.note_visual_progress(note, self.first, self.second, 2.0), 0.25)

    def test_visible_overbudget_result_reapplies_accurate_cache_without_preparation(self):
        note = basic_note(1, 1.0, 1)
        diagnostics = +consumer.TrajectoryDiagnostics

        def evaluate(group, hit, target, cache, now, *, accurate=False):
            value = AccurateScalar.of(hit - now)
            if not accurate:
                value.error += 0.001
            return value

        self.evaluate.side_effect = evaluate

        result = consumer.note_visual_progress_value(note, self.first, self.second, 0.0, diagnostics)

        self.assertAlmostEqual(result.to_float(), 0.0)
        self.assertEqual(diagnostics.accurate_refinements, 1)
        self.assertEqual(diagnostics.uncertified_results, 0)
        self.assertEqual([call.kwargs.get("accurate", False) for call in self.evaluate.call_args_list], [False, True])
        self.prepare.assert_not_called()

    def test_attachment_fraction_rounding_triggers_certified_cancellation_path(self):
        head = basic_note(1, 0.0, 1)
        tail = basic_note(2, 3.0, 1)
        note = attached_note(head, tail, 1.0)
        diagnostics = +consumer.TrajectoryDiagnostics
        self.evaluate.side_effect = lambda group, hit, target, cache, now, **kwargs: AccurateScalar.of(
            10000 if hit == 0 else -20000
        )

        result = consumer.note_visual_progress_value(note, self.first, self.second, -1.0, diagnostics)

        self.assertAlmostEqual(result.to_float(), 1.0, delta=1e-4)
        self.assertTrue(result.error_at_most(1e-4))
        self.assertEqual(diagnostics.accurate_refinements, 1)

    def test_near_tail_attachment_refines_on_both_sides_of_epsilon(self):
        note = attached_note(basic_note(1, -2), basic_note(2, 1), 1)
        preempt = .0035
        for gap in (2.0**-20, 17 * 2.0**-24):
            with self.subTest(gap=gap), patch.object(consumer, "group_preempt_time", return_value=preempt):
                diagnostics = +consumer.TrajectoryDiagnostics
                value = consumer.note_visual_progress_value(
                    note, self.first, self.second, 1 - 3 * gap, diagnostics
                )
                fraction = .5 if gap < 1e-6 else 1.0
                expected = 1 - fraction * 3 * gap / preempt
                self.assertAlmostEqual(value.to_float(), expected, delta=1e-4)
                self.assertTrue(value.error_at_most(1e-4))
                self.assertEqual(diagnostics.accurate_refinements, 1)
                self.assertEqual(diagnostics.uncertified_results, 0)

    def test_proved_offscreen_result_does_not_refine_large_absolute_error(self):
        note = basic_note(1, 10000.0, 1)
        diagnostics = +consumer.TrajectoryDiagnostics

        def evaluate(group, hit, target, cache, now, **kwargs):
            value = AccurateScalar.of(hit - now)
            value.error += 1e-5
            return value

        self.evaluate.side_effect = evaluate
        result = consumer.note_visual_progress_value(note, self.first, self.second, 0.0, diagnostics)

        self.assertLess(result.to_float(), -1000)
        self.assertEqual(diagnostics.accurate_refinements, 0)
        self.evaluate.assert_called_once()

    def test_attachment_visibility_sources_share_complete_offset_envelope(self):
        head = basic_note(1, 1.0, 1, stage=Interval(-2, -1))
        tail = basic_note(2, 5.0, 2, stage=Interval(3, 4))
        note = attached_note(head, tail, 3.0)
        sources = +VarArray[VisibilitySource, Dim[4]]

        with patch.object(consumer, "stage_y_offset_bounds", side_effect=lambda stage: stage):
            consumer.append_note_visibility_sources(note, sources)

        self.assertEqual(len(sources), 2)
        for source in sources:
            self.assertEqual(source.offset_min, -2)
            self.assertEqual(source.offset_max, 4)
        self.assertTrue(sources[0].clamp_after_hit)
        self.assertFalse(sources[1].clamp_after_hit)

    def test_connector_expands_both_attached_endpoints_into_four_sources(self):
        first = attached_note(basic_note(1, 1.0), basic_note(2, 5.0), 2.0)
        second = attached_note(basic_note(4, 2.0), basic_note(5, 8.0), 6.0)
        observed = []

        def search(sources, latest):
            observed.extend((source.group, source.hit_time, source.clamp_after_hit) for source in sources)
            self.assertEqual(latest, 8.0)
            return -1.0

        with patch.object(consumer, "get_sources_visual_spawn_time", side_effect=search):
            self.assertEqual(consumer.segment_visual_spawn_time(first, second, 8.0), -1.0)
        self.assertEqual([item[1] for item in observed], [1.0, 5.0, 2.0, 8.0])
        self.assertEqual([item[2] for item in observed], [True, False, True, False])


if __name__ == "__main__":
    unittest.main()
