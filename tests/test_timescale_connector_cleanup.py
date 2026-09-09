# ruff: noqa: PT009
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from sonolus.script.archetype import EntityRef
from sonolus.script.interval import Interval

from sekai.lib import timescale
from sekai.lib.connector import (
    CONNECTOR_THROUGH_JUDGE_LINE_DESPAWN_DELAY,
    ConnectorKind,
    ConnectorLayer,
    ConnectorVisualState,
    SegmentPresentation,
)
from sekai.lib.ease import EaseType
from sekai.lib.layout import StageTransform
from sekai.lib.stage import VisualMask
from sekai.play import connector
from sekai.play.timescale import TimescaleGroup
from tests.test_timescale_timeline import TimelineFixture
from tests.timescale_reference import RefMarker


class ConnectorCleanupTests(unittest.TestCase):
    def make_connector(self, group):
        def endpoint(hit):
            return SimpleNamespace(
                timescale_group=group,
                target_time=hit,
                target_position=timescale.locate_target(group, hit),
                is_attached=False,
                visual_stage_transform=lambda: +StageTransform,
                visual_mask=+VisualMask,
                visual_lane=0,
                lane=0,
                size=1,
                visual_y_offset=0,
                visual_note_alpha=1,
                head_ease_frac=0,
                tail_ease_frac=1,
                segment_alpha=1,
                segment_layer=ConnectorLayer.TOP,
                segment_presentation=SegmentPresentation.DEFAULT,
                segment_through_judge_line=True,
            )

        source = SimpleNamespace(
            head=endpoint(1),
            tail=endpoint(3),
            end_time=3 + CONNECTOR_THROUGH_JUDGE_LINE_DESPAWN_DELAY,
            despawn=False,
            active_head_ref=SimpleNamespace(index=0),
            active_tail_ref=SimpleNamespace(index=0),
            visual_active_interval=Interval(1, 3),
            draw_hitbox=Mock(),
            kind=ConnectorKind.GUIDE_NEUTRAL,
            ease_type=EaseType.NONE,
            last_visual_state=ConnectorVisualState.WAITING,
            head_trajectory_first=timescale.TrajectoryCache(0, 0),
            head_trajectory_second=timescale.TrajectoryCache(0, 0),
            tail_trajectory_first=timescale.TrajectoryCache(0, 0),
            tail_trajectory_second=timescale.TrajectoryCache(0, 0),
        )
        source.segment_head, source.segment_tail = source.head, source.tail
        return source

    def test_final_frame_skips_rendering_after_run_change(self):
        end_time = 3 + CONNECTOR_THROUGH_JUDGE_LINE_DESPAWN_DELAY
        records = [
            RefMarker(0, 1),
            RefMarker(1, 2, style=1),
            RefMarker(2, 1),
            RefMarker(end_time, 2, style=1),
        ]
        with TimelineFixture(records) as fixture:
            fixture.group.effective_preempt = 1
            group = EntityRef[TimescaleGroup](100000)
            source = self.make_connector(group)
            now = end_time - 0.01
            timescale.prepare_group(group, now)
            with patch.object(connector, "time", return_value=now), patch.object(connector, "draw_connector") as draw:
                connector.Connector.update_sequential(cast(Any, source))
                connector.Connector.update_parallel(cast(Any, source))
            self.assertFalse(source.despawn)
            draw.assert_called_once()
            self.assertAlmostEqual(
                draw.call_args.kwargs["tail_visual_progress"], 1 - float(fixture.oracle.distance(now, 3))
            )
            source.draw_hitbox.reset_mock()

            now = end_time + 0.01
            timescale.prepare_group(group, now)
            with patch.object(connector, "time", return_value=now), patch.object(connector, "draw_connector") as draw:
                connector.Connector.update_sequential(cast(Any, source))
                self.assertTrue(source.despawn)
                self.assertNotEqual(source.head_trajectory_first.run_ref, fixture.group.current_run)
                connector.Connector.update_parallel(cast(Any, source))
            source.draw_hitbox.assert_not_called()
            draw.assert_not_called()

    def test_first_frame_after_expiration_does_not_read_uninitialized_caches(self):
        with TimelineFixture([RefMarker(0, 1)]):
            group = EntityRef[TimescaleGroup](100000)
            source = self.make_connector(group)
            now = source.end_time + 1
            timescale.prepare_group(group, now)
            with (
                patch.object(connector, "time", return_value=now),
                patch.object(connector, "note_visual_progress") as progress,
            ):
                connector.Connector.update_sequential(cast(Any, source))
                connector.Connector.update_parallel(cast(Any, source))
            self.assertTrue(source.despawn)
            self.assertEqual(source.head_trajectory_first.run_ref, 0)
            source.draw_hitbox.assert_not_called()
            progress.assert_not_called()
