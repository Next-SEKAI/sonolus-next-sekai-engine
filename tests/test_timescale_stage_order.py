# ruff: noqa: PT009
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import sekai.play.note  # noqa: F401
from sekai.lib import layout
from sekai.play import dynamic_stage as play_stage
from sekai.play.initialization import Initialization
from sekai.watch import dynamic_stage as watch_stage
from sekai.watch.initialization import WatchInitialization


class TimescaleStageOrderTests(unittest.TestCase):
    def test_feature_discovery_precedes_layout_and_derived_stage_geometry(self):
        for module, initializer, prefix in [
            (play_stage, Initialization, ""),
            (watch_stage, WatchInitialization, "Watch"),
        ]:
            with self.subTest(mode=module.__name__):
                stage = getattr(module, prefix + "DynamicStage")
                self.assertEqual(initializer.preprocess._callback_order_, -3)
                self.assertEqual(stage.preprocess._callback_order_, -1)
                for name in (
                    "CameraChange",
                    "StageTransformChange",
                    "StageMaskChange",
                    "StagePivotChange",
                    "StageStyleChange",
                ):
                    marker = getattr(module, prefix + name)
                    self.assertEqual(marker.preprocess._callback_order_, -4)
                transform = getattr(module, prefix + "StageTransformChange")
                config = SimpleNamespace(dynamic_stages=False, has_stage_transforms=False)
                options = SimpleNamespace(mirror=False, lock_stage_aspect_ratio=False, stage_cover=0.8, hidden=0.5)
                marker = SimpleNamespace(beat=4, rotate=0, x_lane_translate=0)
                with (
                    patch.object(module, "LevelConfig", config),
                    patch.object(module, "Options", options),
                    patch.object(module, "beat_to_time", return_value=2),
                    patch.object(layout, "LevelConfig", config),
                    patch.object(layout, "Options", options),
                ):
                    # These are the feature-dependent values consumed by init_layout.
                    transform.preprocess(marker)
                    self.assertTrue(layout.stage_aspect_ratio_locked())
                    self.assertEqual(layout.stage_cover_amount(), 0)
                    self.assertEqual(layout.hidden_amount(), 0)
                    self.assertTrue(config.dynamic_stages)


if __name__ == "__main__":
    unittest.main()
