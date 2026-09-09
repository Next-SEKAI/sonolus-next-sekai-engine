# ruff: noqa: PT009, PT027
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from sonolus.script.interval import Interval

from sekai.lib import timescale
from sekai.lib import timescale_consumer as consumer
from sekai.lib.connector import ConnectorKind
from sekai.lib.ease import EaseType
from sekai.lib.note import NoteKind
from sekai.play import connector as play_connector
from sekai.play import note as play_note
from sekai.play import sim_line as play_sim_line
from sekai.watch import connector as watch_connector
from sekai.watch import note as watch_note
from sekai.watch import sim_line as watch_sim_line


def endpoint(hit_time, lane, offset):
    return SimpleNamespace(
        target_time=hit_time,
        size=1.0,
        connector_ease=EaseType.LINEAR,
        init_data=Mock(),
        _basic_visual_lane_at=lambda t: lane,
        _basic_y_offset_at=lambda t, **kwargs: offset,
    )


class TimescaleNotePreprocessTests(unittest.TestCase):
    def test_expired_play_sim_line_keeps_groups_for_its_cleanup_frame(self):
        left = SimpleNamespace(start_time=2, target_time=1, extend_stage_windows=Mock())
        right = SimpleNamespace(start_time=3, target_time=3, extend_stage_windows=Mock())
        source = SimpleNamespace(left=left, right=right)
        with (
            patch.object(play_sim_line, "segment_visual_spawn_time", return_value=float("inf")),
            patch.object(play_sim_line, "register_note_group_window") as register,
        ):
            play_sim_line.SimLine.preprocess(cast(Any, source))
        self.assertEqual(source.spawn_time, 2)
        self.assertEqual([call.args for call in register.call_args_list], [(left, 2, 2), (right, 2, 2)])

    def test_connector_window_covers_endpoint_and_distinct_segment_hide_groups(self):
        for module, cls in (
            (play_connector, play_connector.Connector),
            (watch_connector, watch_connector.WatchConnector),
        ):
            with self.subTest(mode=module.__name__), ExitStack() as stack:
                head = SimpleNamespace(
                    start_time=-2,
                    target_time=1,
                    connector_ease=EaseType.NONE,
                    timescale_group=1,
                    is_attached=False,
                    extend_stage_windows=Mock(),
                )
                tail = SimpleNamespace(
                    start_time=-1, target_time=3, timescale_group=2, is_attached=False, extend_stage_windows=Mock()
                )
                segment = SimpleNamespace(
                    start_time=-1,
                    timescale_group=3,
                    segment_kind=ConnectorKind.GUIDE_NEUTRAL,
                    segment_through_judge_line=False,
                )
                source = SimpleNamespace(
                    head=head,
                    tail=tail,
                    segment_head=segment,
                    segment_tail=segment,
                    active_head_ref=SimpleNamespace(index=0),
                    active_tail_ref=SimpleNamespace(index=0),
                    head_ref=SimpleNamespace(index=1),
                    visual_active_interval=Interval(0, 0),
                    schedule_sfx=Mock(),
                )
                stack.enter_context(patch.object(module, "Options", SimpleNamespace(auto_sfx=False)))
                stack.enter_context(patch.object(module, "segment_visual_spawn_time", return_value=-3))
                if module is play_connector:
                    stack.enter_context(patch.object(module, "input_offset", return_value=0))
                register = stack.enter_context(patch.object(consumer, "register_group_window"))
                stack.enter_context(patch.object(module, "register_group_window", register))
                cls.preprocess(cast(Any, source))
                self.assertEqual(source.start_time, -3)
                self.assertEqual([call.args for call in register.call_args_list], [(1, -3, 3), (2, -3, 3), (3, -3, 3)])

    def test_malformed_group_cannot_publish_note_or_dependent_spawn(self):
        for module, note_class in ((play_note, play_note.BaseNote), (watch_note, watch_note.WatchBaseNote)):
            with self.subTest(mode=module.__name__), ExitStack() as stack:
                source = SimpleNamespace(
                    data_init_done=False,
                    key=0,
                    effect_kind=0,
                    beat=1,
                    timescale_group=1,
                    result=SimpleNamespace(),
                )
                source.init_data = lambda note_class=note_class, source=source: note_class.init_data(cast(Any, source))
                stack.enter_context(patch.object(module, "DISABLE_NOTES", False))
                stack.enter_context(patch.object(module, "Options", SimpleNamespace(mirror=False)))
                stack.enter_context(patch.object(module, "map_note_kind", return_value=NoteKind.HIDE_TICK))
                stack.enter_context(patch.object(module, "get_note_effect_kind", return_value=0))
                stack.enter_context(patch.object(module, "beat_to_time", return_value=1.0))
                if module is play_note:
                    stack.enter_context(
                        patch.object(module, "get_note_window", return_value=SimpleNamespace(bad=Interval(-0.1, 0.1)))
                    )
                    stack.enter_context(patch.object(module, "input_offset", return_value=0.0))
                stack.enter_context(patch.object(timescale, "Options", SimpleNamespace(disable_timescale=False)))
                stack.enter_context(patch.object(timescale.runtime, "is_preprocessing", return_value=True))
                stack.enter_context(
                    patch.object(
                        timescale,
                        "timescale_group_archetype",
                        return_value=SimpleNamespace(at=lambda index: SimpleNamespace(valid=False)),
                    )
                )

                with self.assertRaisesRegex(RuntimeError, "Invalid timescale group"):
                    note_class.preprocess(cast(Any, source))
                self.assertEqual(source.start_time, float("inf"))
                self.assertFalse(source.data_init_done)
                # Attachment initialization must not reuse partially completed
                # metadata after the original callback was terminated.
                with self.assertRaisesRegex(RuntimeError, "Invalid timescale group"):
                    source.init_data()

                dependencies = (
                    (play_connector, play_connector.Connector, "start_time"),
                    (watch_connector, watch_connector.WatchConnector, "start_time"),
                    (play_sim_line, play_sim_line.SimLine, "spawn_time"),
                    (watch_sim_line, watch_sim_line.WatchSimLine, "start_time"),
                )
                for dependency_module, dependency_class, spawn_field in dependencies:
                    other = SimpleNamespace(start_time=0.0)
                    dependent = SimpleNamespace(head=source, tail=other, left=source, right=other)
                    with patch.object(dependency_module, "segment_visual_spawn_time") as search:
                        dependency_class.preprocess(cast(Any, dependent))
                    self.assertEqual(getattr(dependent, spawn_field), float("inf"))
                    search.assert_not_called()

    def test_attached_spawn_runs_once_after_geometry_and_propagates_stage_window(self):
        for module, note_class in ((play_note, play_note.BaseNote), (watch_note, watch_note.WatchBaseNote)):
            with self.subTest(mode=module.__name__), ExitStack() as stack:
                head = endpoint(1.0, 1.0, 0.5)
                tail = endpoint(3.0, 3.0, 2.5)
                source = SimpleNamespace(
                    init_data=Mock(),
                    kind=NoteKind.HIDE_TICK,
                    is_attached=True,
                    is_scored=False,
                    target_time=2.0,
                    input_interval=Interval(1.8, 2.2),
                    result=SimpleNamespace(),
                    active_connector_info=SimpleNamespace(),
                    attach_head_ref=SimpleNamespace(get=lambda head=head: head),
                    attach_tail_ref=SimpleNamespace(get=lambda tail=tail: tail),
                    despawn_time=lambda: 2.2,
                    extend_stage_windows=Mock(),
                )

                def spawn(note, latest):
                    self.assertEqual(note.lane, 2.0)
                    self.assertEqual(note.size, 1.0)
                    self.assertEqual(note.target_y_offset, 1.5)
                    self.assertEqual(latest, 2.2)
                    return -1.5

                stack.enter_context(patch.object(module, "DISABLE_NOTES", False))
                stack.enter_context(patch.object(module, "get_note_bucket", return_value=0))
                register = stack.enter_context(patch.object(module, "register_note_group_window"))
                search = stack.enter_context(patch.object(module, "note_visual_spawn_time", side_effect=spawn))
                if module is watch_note:
                    stack.enter_context(patch.object(module, "is_replay", return_value=False))

                note_class.preprocess(cast(Any, source))

                search.assert_called_once()
                self.assertEqual(source.start_time, -1.5)
                register.assert_called_once_with(source, -1.5, 2.2)
                source.extend_stage_windows.assert_called_once_with(-2.5, 3.2)
                head.init_data.assert_called_once()
                tail.init_data.assert_called_once()


if __name__ == "__main__":
    unittest.main()
