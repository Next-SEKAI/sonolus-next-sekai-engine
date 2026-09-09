# ruff: noqa: PT009, PT027
import unittest
from math import inf
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from sonolus.script.interval import Interval

from sekai.lib import timescale_consumer as consumer
from sekai.lib import timescale_visibility as visibility
from sekai.lib.connector import ConnectorKind
from sekai.lib.ease import EaseType
from sekai.lib.note import NoteKind
from sekai.lib.timescale import TargetPosition
from sekai.lib.timescale_math import TimePosition
from sekai.watch import connector, note, sim_line


class WatchVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(note, "Options", SimpleNamespace(mirror=False)))
        self.enterContext(patch.object(note, "map_note_kind", side_effect=lambda kind: kind))
        self.enterContext(patch.object(note, "get_note_effect_kind", return_value=0))
        self.enterContext(patch.object(note, "get_note_bucket", return_value=0))
        self.enterContext(patch.object(note, "beat_to_time", side_effect=lambda beat: beat))
        self.enterContext(patch.object(note, "is_replay", return_value=False))
        self.enterContext(patch.object(sim_line, "is_replay", return_value=False))
        self.enterContext(patch.object(note, "get_stage_props", return_value=SimpleNamespace(pivot_lane=0)))
        self.enterContext(patch.object(consumer, "group_preempt_time", return_value=4))
        self.enterContext(patch.object(consumer, "stage_y_offset_bounds", side_effect=lambda stage: stage))
        self.enterContext(
            patch.object(visibility, "conservative_progress_bounds", return_value=Interval(-3.004, 6.007))
        )
        for module in (note, visibility):
            self.enterContext(
                patch.object(
                    module, "locate_target", side_effect=lambda group, hit: TargetPosition(0, TimePosition.of(hit))
                )
            )
        self.enterContext(patch.object(visibility, "locate_time_from", return_value=0))
        self.enterContext(
            patch.object(visibility, "distance_to_target", side_effect=lambda group, ref, now, target, hit: hit - now)
        )

    def anchor(self, hit, offset):
        source = SimpleNamespace(
            data_init_done=False,
            key=NoteKind.ANCHOR,
            effect_kind=0,
            beat=hit,
            lane=0,
            size=1,
            timescale_group=SimpleNamespace(index=0),
            stage_ref=SimpleNamespace(index=1, get=lambda: Interval(offset, offset)),
            next_ref=SimpleNamespace(index=0),
            result=SimpleNamespace(),
            is_attached=False,
            is_scored=False,
            connector_ease=EaseType.NONE,
            segment_kind=ConnectorKind.GUIDE_NEUTRAL,
            segment_through_judge_line=False,
            _basic_y_offset_at=lambda t, **kwargs: offset,
            extend_stage_windows=Mock(),
            despawn_time=lambda: hit,
        )
        source.init_data = lambda: note.WatchBaseNote.init_data(cast(Any, source))
        note.WatchBaseNote.preprocess(cast(Any, source))
        source.init_data()
        self.assertTrue(source.preprocess_done)
        return source

    def make_connector(self, head, tail):
        return SimpleNamespace(
            head=head,
            tail=tail,
            segment_head=head,
            segment_tail=tail,
            active_head_ref=SimpleNamespace(index=0),
            active_tail_ref=SimpleNamespace(index=0),
            head_ref=SimpleNamespace(index=1),
            visual_active_interval=Interval(0, 0),
            schedule_sfx=Mock(),
        )

    def test_visible_connector_can_use_individually_invisible_anchors(self):
        for offsets in ((5, -7), (5, 0), (0, -7)):
            with self.subTest(offsets=offsets):
                head, tail = self.anchor(1, offsets[0]), self.anchor(3, offsets[1])
                self.assertTrue(head.preprocess_done and tail.preprocess_done)
                self.assertTrue(inf in (head.start_time, tail.start_time))
                source = self.make_connector(head, tail)
                with (
                    patch.object(connector, "register_note_group_window") as register,
                    patch.object(connector, "register_group_window"),
                ):
                    connector.WatchConnector.preprocess(cast(Any, source))
                self.assertEqual(source.start_time, -2)
                self.assertEqual(source.end_time, 3)
                source.schedule_sfx.assert_called_once()
                self.assertEqual([call.args for call in register.call_args_list], [(head, -2, 3), (tail, -2, 3)])
                head.extend_stage_windows.assert_called_with(-3, 4)
                tail.extend_stage_windows.assert_called_with(-3, 4)

    def test_sim_line_preprocess_uses_segment_visibility_with_invisible_endpoints(self):
        head, tail = self.anchor(1, 5), self.anchor(1, -7)
        source = SimpleNamespace(left=head, right=tail)
        with patch.object(sim_line, "register_note_group_window") as register:
            sim_line.WatchSimLine.preprocess(cast(Any, source))
        self.assertEqual(source.start_time, -2)
        self.assertEqual(source.end_time, 1)
        self.assertEqual([call.args for call in register.call_args_list], [(head, -2, 1), (tail, -2, 1)])

    def test_invisible_active_endpoints_still_schedule_the_slide_manager(self):
        head, tail = self.anchor(1, 5), self.anchor(3, -7)
        source = self.make_connector(head, tail)
        source.active_head_ref = SimpleNamespace(index=1)
        source.active_tail_ref = SimpleNamespace(index=2)
        source.active_head, source.active_tail = head, tail
        with (
            patch.object(connector, "register_note_group_window"),
            patch.object(connector, "register_group_window"),
            patch.object(connector.WatchSlideManager, "spawn") as spawn_manager,
        ):
            connector.WatchConnector.preprocess(cast(Any, source))
        self.assertEqual(source.start_time, -2)
        source.schedule_sfx.assert_called_once()
        spawn_manager.assert_called_once_with(
            active_head_ref=source.active_head_ref, active_tail_ref=source.active_tail_ref
        )

    def test_failed_attachment_preprocess_does_not_publish_ready_metadata(self):
        source = self.anchor(1, 0)
        source.is_attached = True
        source.attach_head_ref = SimpleNamespace(
            get=lambda: SimpleNamespace(init_data=Mock(side_effect=RuntimeError("bad group")))
        )
        source.attach_tail_ref = SimpleNamespace(get=lambda: source)
        with self.assertRaisesRegex(RuntimeError, "bad group"):
            note.WatchBaseNote.preprocess(cast(Any, source))
        self.assertTrue(source.data_init_done)
        self.assertFalse(source.preprocess_done)
        other = self.anchor(3, 0)
        dependent = self.make_connector(source, other)
        with patch.object(connector, "segment_visual_spawn_time") as search:
            connector.WatchConnector.preprocess(cast(Any, dependent))
        self.assertEqual(dependent.start_time, inf)
        search.assert_not_called()
        line = SimpleNamespace(left=source, right=other)
        with patch.object(sim_line, "segment_visual_spawn_time") as search:
            sim_line.WatchSimLine.preprocess(cast(Any, line))
        self.assertEqual(line.start_time, inf)
        search.assert_not_called()
