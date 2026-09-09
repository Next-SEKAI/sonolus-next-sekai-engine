# ruff: noqa: PT009
"""Keep the dedicated timescale level simple, playable and feature-complete."""

import io
import unittest
import wave
from itertools import pairwise
from typing import cast

from sekai import timescale_test_level as demo
from sekai.level_utils import LevelBpmChange, LevelSlide
from sekai.lib.connector import ConnectorKind
from sekai.lib.ease import EaseType
from sekai.lib.note import NoteKind
from sekai.lib.timescale import TransitionStyle


class TimescaleDemoTests(unittest.TestCase):
    def test_single_continuous_evenly_spaced_tap_stream(self):
        self.assertEqual(len(demo.notes), 329)
        self.assertEqual(demo.notes[0].beat, demo.NOTE_START_BEAT)
        self.assertEqual(demo.notes[-1].beat, demo.NOTE_END_BEAT)
        self.assertTrue(all(b.beat - a.beat == demo.NOTE_STEP_BEATS for a, b in pairwise(demo.notes)))
        self.assertEqual({note.lane for note in demo.notes}, {0})
        self.assertEqual({note.kind for note in demo.notes}, {NoteKind.NORM_TAP})
        self.assertTrue(all(note.attach is None and note.segment_kind == ConnectorKind.NONE for note in demo.notes))
        self.assertFalse(any(isinstance(entity, LevelSlide) for entity in demo.entities))

    def test_both_pure_styles_have_every_ease_on_a_changing_interval(self):
        for group, style in (
            (demo.timescale_group, TransitionStyle.TIMESCALE),
            (demo.scroll_group, TransitionStyle.SCROLL),
        ):
            with self.subTest(style=style):
                self.assertTrue(all(change.transition_style == style for change in group.changes))
                moving_eases = {
                    a.timescale_ease
                    for a, b in pairwise(group.changes)
                    if a.beat < b.beat and a.timescale != b.timescale
                }
                self.assertEqual(moving_eases, set(demo.EASINGS))
                self.assertEqual(
                    moving_eases,
                    {
                        EaseType.NONE,
                        EaseType.LINEAR,
                        EaseType.IN_QUAD,
                        EaseType.OUT_QUAD,
                        EaseType.IN_OUT_QUAD,
                        EaseType.OUT_IN_QUAD,
                    },
                )

    def test_hybrid_alternation_equal_speed_switch_and_ordered_steps(self):
        changes = demo.hybrid_group.changes
        self.assertTrue(all(change.timescale > 0 and change.timescale_skip == 0 for change in changes))
        self.assertGreaterEqual(sum(a.transition_style != b.transition_style for a, b in pairwise(changes)), 6)
        self.assertTrue(
            any(a.timescale == b.timescale and a.transition_style != b.transition_style for a, b in pairwise(changes))
        )
        batch = [change for change in changes if change.beat == 124]
        self.assertEqual([change.timescale for change in batch], [2, 0.75, 1.5])
        self.assertEqual(
            [change.transition_style for change in batch],
            [TransitionStyle.TIMESCALE, TransitionStyle.SCROLL, TransitionStyle.TIMESCALE],
        )

    def test_signed_stop_reversal_and_skips_are_legacy_only(self):
        changes = demo.legacy_group.changes
        self.assertTrue(all(change.transition_style == TransitionStyle.TIMESCALE for change in changes))
        self.assertTrue(any(change.timescale < 0 for change in changes))
        self.assertTrue(
            any(
                a.timescale == 0 and a.timescale_ease == EaseType.NONE and b.beat > a.beat for a, b in pairwise(changes)
            )
        )
        self.assertTrue(any(a.timescale < 0 < b.timescale for a, b in pairwise(changes)))
        self.assertTrue(any(change.timescale_skip > 0 for change in changes))
        self.assertTrue(any(change.timescale_skip < 0 for change in changes))
        for group in demo.groups:
            if group is not demo.legacy_group:
                self.assertTrue(all(change.timescale > 0 and change.timescale_skip == 0 for change in group.changes))

    def test_sections_cover_the_stream_without_gaps(self):
        self.assertEqual(demo.sections[0].start_beat, demo.NOTE_START_BEAT)
        self.assertEqual(demo.sections[-1].end_beat, demo.NOTE_END_BEAT)
        self.assertTrue(all(a.end_beat == b.start_beat for a, b in pairwise(demo.sections)))
        for section in demo.sections:
            section_notes = [note for note in demo.notes if section.start_beat <= note.beat < section.end_beat]
            self.assertTrue(section_notes)
            self.assertTrue(all(note.timescale_group is section.group for note in section_notes))
        self.assertIs(demo.notes[-1].timescale_group, demo.legacy_group)

    def test_level_metadata_and_audio_cover_the_stream(self):
        self.assertEqual(demo.level.name, "timescale-transition-demo")
        self.assertIsNotNone(demo.level.description)
        tempos = [entity for entity in demo.entities if isinstance(entity, LevelBpmChange)]
        self.assertEqual([(tempo.beat, tempo.bpm) for tempo in tempos], [(0, demo.BPM)])
        with wave.open(io.BytesIO(cast(bytes, demo.level.bgm)), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
        self.assertEqual(duration, demo.END_BEAT * 60 / demo.BPM)
        self.assertGreater(duration, demo.NOTE_END_BEAT * 60 / demo.BPM)


if __name__ == "__main__":
    unittest.main()
