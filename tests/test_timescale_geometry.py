# ruff: noqa: PT009
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from sonolus.script.interval import clamp

from sekai.lib import layout, stage


class Ref:
    def __init__(self, index=0):
        self.index = index

    def __pos__(self):
        return Ref(self.index)


class TimescaleGeometryTests(unittest.TestCase):
    def test_chart_envelope_contains_actual_draw_guards(self):
        for alternative in (False, True):
            for cover in (0.0, 0.5, 0.999):
                for hidden in (0.0, 0.4, 1.0):
                    for compensated in (False, True):
                        options = SimpleNamespace(alternative_approach_curve=alternative)
                        data = SimpleNamespace(
                            approach_start=0.0,
                            cover_depth=layout.APPROACH_SCALE + (1 - layout.APPROACH_SCALE) * cover,
                            cutoff_depth=(1 + (layout.APPROACH_SCALE - 1) * hidden) if hidden else 5.0,
                        )
                        cameras = {
                            1: SimpleNamespace(stage_tilt=0.0, next_ref=Ref(2)),
                            2: SimpleNamespace(stage_tilt=1.0, next_ref=Ref()),
                        }
                        initializer = SimpleNamespace(first_camera_ref=Ref(1))
                        with ExitStack() as stack:
                            stack.enter_context(patch.object(layout, "Options", options))
                            stack.enter_context(patch.object(layout, "Layout", data))
                            stack.enter_context(patch.object(layout, "is_play", return_value=True))
                            stack.enter_context(patch.object(layout, "stage_cover_amount", return_value=cover))
                            stack.enter_context(
                                patch.object(
                                    layout,
                                    "_initialization_archetype",
                                    return_value=SimpleNamespace(at=lambda _, value=initializer: value),
                                )
                            )
                            stack.enter_context(patch.object(layout, "_camera_change_archetype", return_value=None))
                            stack.enter_context(
                                patch.object(
                                    layout, "get_event_as", side_effect=lambda ref, _, values=cameras: values[ref.index]
                                )
                            )
                            if cover and compensated:
                                data.approach_start = clamp(
                                    layout.inverse_approach_curve_base(data.cover_depth), 0, 0.99
                                )
                            bounds = layout._compute_conservative_progress_bounds()
                            for index in range(201):
                                tilt = index / 200
                                vanish = max(tilt, layout.STAGE_TILT_VANISH_MIN)
                                ext = (1 - vanish) * layout.STAGE_WIDTH_MID / vanish
                                start = layout.inverse_approach_at_tilt(
                                    data.cover_depth if cover else data.cover_depth - ext, tilt
                                )
                                end = layout.inverse_approach_at_tilt(data.cutoff_depth, tilt)
                                # Empty draw intervals need not be enclosed.
                                if start <= end:
                                    self.assertLessEqual(bounds.start, start)
                                    self.assertGreaterEqual(bounds.end, end)

    def test_fixed_tilt_preserves_legacy_leniency_without_global_lookback(self):
        data = SimpleNamespace(approach_start=0.0, cover_depth=layout.APPROACH_SCALE, cutoff_depth=5.0)
        with (
            patch.object(layout, "Layout", data),
            patch.object(layout, "Options", SimpleNamespace(alternative_approach_curve=False)),
            patch.object(layout, "is_play", return_value=False),
            patch.object(layout, "is_watch", return_value=False),
            patch.object(layout, "stage_cover_amount", return_value=0.0),
        ):
            bounds = layout._compute_conservative_progress_bounds()
            self.assertLess(bounds.start, -3.0)
            self.assertGreater(bounds.start, -3.01)
            self.assertGreater(bounds.end, 6.0)
            self.assertLess(bounds.end, 6.01)

    def test_stage_offset_encloses_every_converted_pivot(self):
        pivots = {
            1: SimpleNamespace(y_offset=0.3, next_ref=Ref(2)),
            2: SimpleNamespace(y_offset=-20.0, next_ref=Ref(3)),
            3: SimpleNamespace(y_offset=8.0, next_ref=Ref()),
        }
        with (
            patch.object(stage, "_stage_pivot_change_archetype", return_value=None),
            patch.object(stage, "get_event_as", side_effect=lambda ref, _: pivots[ref.index]),
        ):
            bounds = stage.stage_y_offset_bounds(
                cast(stage.DynamicStageLike, SimpleNamespace(first_pivot_change_ref=Ref(1)))
            )
            self.assertEqual(bounds.start, -20.0)
            self.assertEqual(bounds.end, 8.0)
            empty = stage.stage_y_offset_bounds(
                cast(stage.DynamicStageLike, SimpleNamespace(first_pivot_change_ref=Ref()))
            )
            self.assertEqual(empty.start, 0.0)
            self.assertEqual(empty.end, 0.0)


if __name__ == "__main__":
    unittest.main()
