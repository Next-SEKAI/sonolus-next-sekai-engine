# ruff: noqa: PT009, PT027
import math
import unittest
from typing import cast

from sonolus.script.timing import TimescaleEase

from sekai.level_utils import LevelTimescaleChange, LevelTimescaleGroup, _build_timescale_group
from sekai.lib.ease import EaseType
from sekai.lib.timescale import TransitionStyle
from sekai.play.timescale import TimescaleChange


class TimescaleAuthoringTests(unittest.TestCase):
    def test_existing_positional_arguments_and_default_style(self):
        change = LevelTimescaleChange(4, -2, 0.5, TimescaleEase.LINEAR, True)
        self.assertEqual(change.timescale_ease, EaseType.LINEAR)
        self.assertTrue(change.hide_notes)
        self.assertEqual(change.transition_style, TransitionStyle.TIMESCALE)
        _, entities = _build_timescale_group(LevelTimescaleGroup([change]))
        self.assertEqual(cast(TimescaleChange, entities[1]).timescale, -2)
        self.assertEqual(cast(TimescaleChange, entities[1]).timescale_skip, 0.5)
        self.assertEqual(cast(TimescaleChange, entities[1]).transition_style, TransitionStyle.TIMESCALE)

    def test_all_eases_and_styles_preserve_stable_tie_order(self):
        changes = [
            LevelTimescaleChange(2, 3, timescale_ease=EaseType.OUT_IN_QUAD),
            LevelTimescaleChange(0, 1, timescale_ease=EaseType.IN_QUAD, transition_style=TransitionStyle.SCROLL),
            LevelTimescaleChange(0, 2, timescale_ease=EaseType.OUT_QUAD),
        ]
        _, entities = _build_timescale_group(LevelTimescaleGroup(changes))
        markers = cast(list[TimescaleChange], entities[1:])
        self.assertEqual([marker.timescale for marker in markers], [1, 2, 3])
        self.assertEqual([marker.timescale_ease for marker in markers], [2, 3, 5])
        self.assertEqual(markers[0].transition_style, TransitionStyle.SCROLL)
        for easing in EaseType:
            for style in TransitionStyle:
                with self.subTest(easing=easing, style=style):
                    _, result = _build_timescale_group(
                        LevelTimescaleGroup(
                            [
                                LevelTimescaleChange(0, 1, timescale_ease=easing, transition_style=style),
                            ]
                        )
                    )
                    self.assertEqual(cast(TimescaleChange, result[1]).timescale_ease, easing)
                    self.assertEqual(cast(TimescaleChange, result[1]).transition_style, style)

    def test_scroll_groups_accept_stops_reversals_and_skips(self):
        for speed, skip in [(0, 0), (-1, 0), (1, 0.25), (1, -0.25)]:
            with self.subTest(speed=speed, skip=skip):
                _, entities = _build_timescale_group(
                    LevelTimescaleGroup(
                        [
                            LevelTimescaleChange(0, speed, skip),
                            LevelTimescaleChange(1, 1, transition_style=TransitionStyle.SCROLL),
                        ]
                    )
                )
                marker = cast(TimescaleChange, entities[1])
                self.assertEqual(marker.timescale, speed)
                self.assertEqual(marker.timescale_skip, skip)

    def test_invalid_numeric_and_enum_inputs(self):
        for field in ("beat", "timescale", "timescale_skip"):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(field=field, value=value):
                    change = LevelTimescaleChange(0, 1)
                    setattr(change, field, value)
                    with self.assertRaisesRegex(ValueError, "finite"):
                        _build_timescale_group(LevelTimescaleGroup([change]))
        for field, value in [("transition_style", 2), ("timescale_ease", 6), ("timescale_ease", 0.5)]:
            change = LevelTimescaleChange(0, 1)
            setattr(change, field, value)
            with self.assertRaisesRegex(ValueError, "unknown easing or transition style"):
                _build_timescale_group(LevelTimescaleGroup([change]))
        with self.assertRaisesRegex(ValueError, "force_note_speed must be finite"):
            _build_timescale_group(LevelTimescaleGroup([LevelTimescaleChange(0, 1)], math.inf))
        with self.assertRaisesRegex(ValueError, "at least one change"):
            _build_timescale_group(LevelTimescaleGroup())


if __name__ == "__main__":
    unittest.main()
