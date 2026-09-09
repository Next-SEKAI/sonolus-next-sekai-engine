# ruff: noqa: PT009
"""Compiled spawning must retain visible islands after signed cancellation."""

import unittest
from contextlib import ExitStack
from math import sqrt
from types import SimpleNamespace
from unittest.mock import patch

from sekai.lib import layout
from sekai.play.timescale import TimescaleChange, TimescaleGroup
from tests.test_timescale_compiled import PRECISIONS, SpawnAccuracyProbe, timeline_memory
from tests.timescale_reference import RefMarker
from tests.timescale_vm import compile_probe


class SpawnRoundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spawn = compile_probe(SpawnAccuracyProbe, archetypes=[SpawnAccuracyProbe, TimescaleGroup, TimescaleChange])

    def spawn_time(self, records, hit, precision, storage, low=-3.004, high=6.007):
        result, _ = self.spawn.run(
            precision=precision,
            entity_storage_precision=storage,
            memory=timeline_memory(records),
            instruction_limit=1_000_000,
            group_ref=1,
            hit=hit,
            preempt=0.35,
            low=low,
            high=high,
            earliest=-2,
            latest=hit,
        )
        return result["spawned"][0]

    def test_five_minute_signed_chart_spawns_before_onscreen_note(self):
        records = [RefMarker(0, 10000, ease=1), RefMarker(240, -10000), RefMarker(240, 10000)]
        # Independent integral: D(t, 300) = 10000 / 240 * (t - 120)**2.
        flat_start = -4 * layout.STAGE_WIDTH_MID / (1 - layout.APPROACH_SCALE)
        first_visible = 120 - sqrt(0.35 * (1 - flat_start) * 240 / 10000)
        for precision, storage in PRECISIONS:
            with self.subTest(precision=precision, storage=storage):
                self.assertLessEqual(self.spawn_time(records, 300, precision, storage), first_visible)

        # D=1 occurs shortly after this chart enters the flat drawing guard.
        # Verify its whole body is on-screen, not just inside a drawing guard.
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(layout, "Layout", SimpleNamespace(field_h=2, field_w=32 / 9, approach_start=0))
            )
            stack.enter_context(
                patch.object(layout, "Options", SimpleNamespace(alternative_approach_curve=False, note_margin=0))
            )
            stack.enter_context(patch.object(layout, "is_play", return_value=True))
            camera = layout.CameraInfo(
                lane=0,
                size=6,
                zoom=0.25,
                zoom_target_lane=0,
                zoom_target=layout.camera_zoom_target_at(0, 6, 0, 0, 0),
                zoom_anchor=layout.camera_zoom_anchor(layout.ZoomVerticalAlign.DEFAULT),
                rotate=0,
                stage_tilt=0,
            )
            base = layout.base_layout_transform(camera)
            transform = layout.layout_transform_at_camera(camera)
            dynamic = SimpleNamespace(
                t=transform.t,
                w_scale=transform.w_scale,
                h_scale=transform.h_scale,
                x_translate=transform.x_translate,
                rotate=0,
                stage_tilt=0,
                width_offset=layout.STAGE_WIDTH_MID,
                note_h=layout.STAGE_WIDTH_MID * base.w_scale / (2 * abs(base.h_scale)),
            )
            stack.enter_context(patch.object(layout, "DynamicLayout", dynamic))
            quad = layout.layout_regular_note_body_fallback(0, 1, layout.approach_at_tilt(1 - 1 / 0.35, 0))
            for point in (quad.bl, quad.br, quad.tl, quad.tr):
                self.assertLess(abs(point.x), 16 / 9)
                self.assertLess(abs(point.y), 1)

    def test_narrow_island_survives_completed_same_time_skip(self):
        # A positive skip raises the tangent to within 0.001 of the upper
        # distance guard, leaving a very narrow independently known island.
        ceiling = 0.35 * 4.004
        records = [
            RefMarker(0, 10000, ease=1),
            RefMarker(240, -10000),
            RefMarker(240, 10000, skip=ceiling - 0.001),
        ]
        first_visible = 120 - sqrt(0.001 * 240 / 10000)
        for precision, storage in PRECISIONS:
            with self.subTest(precision=precision, storage=storage):
                self.assertLessEqual(self.spawn_time(records, 300, precision, storage), first_visible)

    def test_common_constant_speeds_keep_local_spawn_times(self):
        for speed in (0.05, 0.1, 1, 8):
            expected = 30 - 0.35 * 4.004 / speed
            for style in (0, 1):
                records = [RefMarker(0, speed, style=style)]
                for precision, storage in PRECISIONS:
                    with self.subTest(speed=speed, style=style, precision=precision, storage=storage):
                        actual = self.spawn_time(records, 30, precision, storage)
                        self.assertLessEqual(actual, expected)
                        # Existing 0.01-distance allowance costs 0.2 seconds
                        # at 0.05x; the new rounding scale must stay negligible.
                        self.assertGreaterEqual(actual, expected - 0.23)

    def test_held_transition_does_not_use_the_next_markers_speed(self):
        expected = 30 - 0.35 * 4.004 / 0.05
        for style in (0, 1):
            records = [RefMarker(0, 0.05, style=style), RefMarker(300, 10000)]
            for precision, storage in PRECISIONS:
                with self.subTest(style=style, precision=precision, storage=storage):
                    actual = self.spawn_time(records, 30, precision, storage)
                    self.assertLessEqual(actual, expected)
                    self.assertGreaterEqual(actual, expected - 0.23)
