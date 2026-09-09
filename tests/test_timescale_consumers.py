# ruff: noqa: PT009
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.interval import Interval

from sekai.lib import timescale_consumer as consumer
from sekai.lib.timescale import TargetPosition, TrajectoryCache
from sekai.lib.timescale_visibility import VisibilitySource


def ref(value=None, index=0):
    return SimpleNamespace(index=index, get=lambda: value)


def basic_note(index, hit_time, group=0, stage=None):
    return SimpleNamespace(
        index=index,
        target_time=hit_time,
        target_position=+TargetPosition,
        timescale_group=ref(index=group),
        stage_ref=ref(stage, int(stage is not None)),
        is_attached=False,
        visual_y_offset=0.0,
    )


def attached_note(head, tail, hit_time):
    note = basic_note(3, hit_time, group=3)
    note.is_attached = True
    note.attach_head_ref = ref(head, head.index)
    note.attach_tail_ref = ref(tail, tail.index)
    return note


class TimescaleConsumerTests(unittest.TestCase):
    def test_inactive_attachment_endpoints_use_the_consumers_two_caches(self):
        head = basic_note(1, 1, 1)
        tail = basic_note(2, 5, 2)
        note = attached_note(head, tail, 3)
        first, second = +TrajectoryCache, +TrajectoryCache
        with patch.object(consumer, "prepare_trajectory") as prepare:
            consumer.prepare_note_trajectories(note, first, second, 0)
        self.assertEqual(prepare.call_count, 2)
        self.assertIs(prepare.call_args_list[0].args[3], first)
        self.assertIs(prepare.call_args_list[1].args[3], second)
        self.assertEqual([call.args[0].index for call in prepare.call_args_list], [1, 2])
        with patch.object(consumer, "prepare_trajectory") as prepare:
            consumer.prepare_note_trajectories(note, first, second, 2)
            prepare.assert_called_once()
            self.assertIs(prepare.call_args.args[3], second)
            prepare.reset_mock()
            consumer.prepare_note_trajectories(note, first, second, 0)
            self.assertEqual(prepare.call_count, 2)

    def test_attachment_progress_preserves_group_preempt_head_clamp_and_offset(self):
        note = attached_note(basic_note(1, 1, 1), basic_note(2, 5, 2), 3)
        note.visual_y_offset = 0.25
        first, second = +TrajectoryCache, +TrajectoryCache
        with (
            patch.object(
                consumer, "evaluate_trajectory", side_effect=lambda group, hit, target, cache, now: hit - now
            ) as evaluate,
            patch.object(consumer, "group_preempt_time", side_effect=lambda group: group.index),
        ):
            self.assertAlmostEqual(consumer.note_progress(note, first, second, 0), 1 - (1 + 5 / 2) / 2)
            self.assertIs(evaluate.call_args_list[0].args[3], first)
            self.assertIs(evaluate.call_args_list[1].args[3], second)
            evaluate.reset_mock()
            self.assertAlmostEqual(consumer.note_visual_progress(note, first, second, 2), 0.25)
            evaluate.assert_called_once()
            self.assertIs(evaluate.call_args.args[3], second)

    def test_coincident_attachment_endpoints_keep_legacy_fraction_fallback(self):
        note = attached_note(basic_note(1, 1), basic_note(2, 1), 1)
        with (
            patch.object(consumer, "evaluate_trajectory", return_value=0),
            patch.object(consumer, "group_preempt_time", return_value=1),
        ):
            self.assertEqual(consumer.note_progress(note, +TrajectoryCache, +TrajectoryCache, 1), 1)

    def test_attached_group_window_includes_hide_group_and_inactive_anchors(self):
        note = attached_note(basic_note(1, 1, 1), basic_note(2, 5, 2), 3)
        with patch.object(consumer, "register_group_window") as register:
            consumer.register_note_group_window(note, -4, 8)
        self.assertEqual([call.args[0].index for call in register.call_args_list], [3, 1, 2])
        self.assertTrue(all(call.args[1:] == (-4, 8) for call in register.call_args_list))

    def test_attachment_visibility_uses_complete_animated_offset_hull(self):
        note = attached_note(basic_note(1, 1, stage=Interval(-2, 1)), basic_note(2, 5, stage=Interval(0, 4)), 3)
        sources = +VarArray[VisibilitySource, Dim[4]]
        with (
            patch.object(consumer, "stage_y_offset_bounds", side_effect=lambda stage: stage),
            patch.object(consumer, "group_preempt_time", return_value=1),
        ):
            consumer.append_note_visibility_sources(note, sources)
        self.assertEqual(len(sources), 2)
        self.assertEqual([(source.offset_min, source.offset_max) for source in sources], [(-2, 4), (-2, 4)])
        self.assertEqual([source.clamp_after_hit for source in sources], [True, False])

    def test_connector_search_includes_all_four_basic_endpoints(self):
        first = attached_note(basic_note(1, 1), basic_note(2, 5), 2)
        second = attached_note(basic_note(4, 2), basic_note(5, 8), 6)
        observed = []

        def search(sources, latest):
            observed.extend(source.hit_time for source in sources)
            self.assertEqual(latest, 8)
            return -1

        with (
            patch.object(consumer, "get_sources_visual_spawn_time", side_effect=search),
            patch.object(consumer, "group_preempt_time", return_value=1),
        ):
            self.assertEqual(consumer.segment_visual_spawn_time(first, second, 8), -1)
        self.assertEqual(observed, [1, 5, 2, 8])


if __name__ == "__main__":
    unittest.main()
