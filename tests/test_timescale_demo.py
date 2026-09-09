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
    def test_matched_continuous_evenly_spaced_tap_streams(self):
        expected_count = int((demo.NOTE_END_BEAT - demo.NOTE_START_BEAT) / demo.NOTE_STEP_BEATS) + 1
        self.assertEqual(demo.NOTE_STEP_BEATS * 60 / demo.BPM, 0.125)
        for stream, lane in ((demo.demo_notes, 0), (demo.reference_notes, 3)):
            self.assertEqual(len(stream), expected_count)
            self.assertEqual(stream[0].beat, demo.NOTE_START_BEAT)
            self.assertEqual(stream[-1].beat, demo.NOTE_END_BEAT)
            self.assertTrue(all(b.beat - a.beat == demo.NOTE_STEP_BEATS for a, b in pairwise(stream)))
            self.assertEqual({note.lane for note in stream}, {lane})
        self.assertEqual([note.beat for note in demo.demo_notes], [note.beat for note in demo.reference_notes])
        self.assertTrue(all(note.timescale_group is None for note in demo.reference_notes))
        self.assertEqual(len(demo.notes), 2 * expected_count)
        self.assertEqual({note.size for note in demo.notes}, {1})
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

    def test_pure_timescale_stop_reversal_and_skips(self):
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

    def test_mixed_signed_stops_skips_and_near_zero_scroll(self):
        changes = demo.mixed_signed_group.changes
        self.assertEqual({change.transition_style for change in changes}, set(TransitionStyle))
        scroll = [change for change in changes if change.transition_style == TransitionStyle.SCROLL]
        self.assertTrue(any(change.timescale == 0 for change in scroll))
        self.assertTrue(any(0 < abs(change.timescale) < 0.0001 for change in scroll))
        self.assertTrue(any(change.timescale < 0 for change in scroll))
        self.assertTrue(any(change.timescale_skip > 0 for change in scroll))
        self.assertTrue(any(change.timescale_skip < 0 for change in scroll))
        self.assertTrue(any(a.timescale < 0 < b.timescale for a, b in pairwise(changes)))

    def test_high_speed_bursts_are_brief_and_recover(self):
        bursts = [(a, b) for a, b in pairwise(demo.burst_group.changes) if a.timescale >= 1000]
        self.assertEqual({a.timescale for a, _ in bursts}, {1000, 10000})
        for burst, recovery in bursts:
            self.assertEqual(burst.timescale_ease, EaseType.NONE)
            self.assertEqual(burst.transition_style, TransitionStyle.TIMESCALE)
            self.assertLessEqual(recovery.beat - burst.beat, demo.NOTE_STEP_BEATS)
            self.assertEqual(recovery.timescale, 1)

    def test_sections_cover_the_stream_without_gaps(self):
        self.assertEqual(demo.sections[0].start_beat, demo.NOTE_START_BEAT)
        self.assertEqual(demo.sections[-1].end_beat, demo.NOTE_END_BEAT)
        self.assertTrue(all(a.end_beat == b.start_beat for a, b in pairwise(demo.sections)))
        for section in demo.sections:
            section_notes = [note for note in demo.demo_notes if section.start_beat <= note.beat < section.end_beat]
            self.assertTrue(section_notes)
            self.assertTrue(all(note.timescale_group is section.group for note in section_notes))
        self.assertIs(demo.demo_notes[-1].timescale_group, demo.sections[-1].group)

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
