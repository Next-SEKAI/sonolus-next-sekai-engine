# ruff: noqa: PT009
"""Check the comparison's timing, visible separation, and transition behavior."""

import gzip
import io
import json
import unittest
import wave
from typing import cast

from sekai import timescale_comparison_level as demo
from tests.timescale_reference import RefMarker, RefTimeline


class TimescaleComparisonDemoTests(unittest.TestCase):
    def test_identical_streams_fit_five_separate_stages_and_five_seconds(self):
        for index, (stream, stage) in enumerate(zip(demo.streams, demo.stages, strict=True)):
            self.assertEqual([note.beat for note in stream], [i / 8 for i in range(1, 41)])
            self.assertTrue(all(note.stage is stage and note.lane == 0 for note in stream))
            expected_group = None if index == 0 else demo.groups[index - 1]
            self.assertTrue(all(note.timescale_group is expected_group for note in stream))
            mask = stage.mask_changes[0]
            self.assertEqual(mask.lane, stage.pivot_changes[0].lane)
            self.assertTrue(all(note.size < mask.size for note in stream))
            self.assertLessEqual(abs(mask.lane) + mask.size, 6)
            if index:
                previous = demo.stages[index - 1].mask_changes[0]
                self.assertLess(previous.lane + previous.size, mask.lane - mask.size)
        with wave.open(io.BytesIO(cast(bytes, demo.level.bgm)), "rb") as audio:
            self.assertEqual(audio.getnframes() / audio.getframerate(), 5)

    def test_shared_speed_pattern_and_distinct_ramp_styles(self):
        for group, expected_up, expected_down in zip(
            demo.groups, (0.4, 0.3, 0.4, 0.3), (0.2, 0.3, 0.3, 0.2), strict=True
        ):
            timeline = RefTimeline(
                [RefMarker(c.beat, c.timescale, c.timescale_ease, c.transition_style) for c in group.changes]
            )
            for time, speed in ((0.5, 0.2), (1.5, 0.6), (2.5, 1), (3.5, 0.6), (4.5, 0.2)):
                self.assertAlmostEqual(float(timeline.speed(time)), speed)
            self.assertAlmostEqual(float(timeline.distance(1.5, 2)), expected_up)
            self.assertAlmostEqual(float(timeline.distance(3.5, 4)), expected_down)

    def test_serialized_level_keeps_all_taps_without_cross_stage_lines(self):
        exported = demo.level.export("next-sekai")
        data = json.loads(gzip.decompress(exported.data))
        names = [entity["archetype"] for entity in data["entities"]]
        self.assertEqual(names.count("NormalTapNote"), 200)
        self.assertNotIn("SimLine", names)


if __name__ == "__main__":
    unittest.main()
