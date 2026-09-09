"""Matched tap streams demonstrating timescale and scroll transitions.

Select "Timescale and Scroll Demo" from the project's test levels. The level
description lists each section in seconds; BPM 120 makes every two beats one
second. Center notes demonstrate motion; lane-three notes provide a steady
reference. Neither stream has attachments or connectors.
"""

from dataclasses import dataclass

from sekai.level_utils import (
    LevelBpmChange,
    LevelEntities,
    LevelNote,
    LevelTimescaleChange,
    LevelTimescaleGroup,
    _build_silent_wav,
    build_level,
)
from sekai.lib.ease import EaseType
from sekai.lib.note import NoteKind
from sekai.lib.timescale import TransitionStyle

BPM = 120.0
NOTE_START_BEAT = 4.0
NOTE_END_BEAT = 208.0
NOTE_STEP_BEATS = 0.25
END_BEAT = 212.0
EASE_SECTION_BEATS = 8.0
EASINGS = (
    EaseType.NONE,
    EaseType.LINEAR,
    EaseType.IN_QUAD,
    EaseType.OUT_QUAD,
    EaseType.IN_OUT_QUAD,
    EaseType.OUT_IN_QUAD,
)
EASE_LABELS = ("Held step", "Linear", "Quad in", "Quad out", "Quad in-out", "Quad out-in")


@dataclass(frozen=True)
class DemoSection:
    label: str
    start_beat: float
    end_beat: float
    group: LevelTimescaleGroup


def change(
    beat: float,
    speed: float,
    ease: EaseType = EaseType.NONE,
    style: TransitionStyle = TransitionStyle.TIMESCALE,
    *,
    skip: float = 0.0,
) -> LevelTimescaleChange:
    return LevelTimescaleChange(
        beat=beat,
        timescale=speed,
        timescale_skip=skip,
        timescale_ease=ease,
        transition_style=style,
    )


def easing_group(start_beat: float, style: TransitionStyle) -> LevelTimescaleGroup:
    # Alternate 1->2 and 2->1 to demonstrate each easing for four seconds.
    changes = [change(0, 1, style=style)]
    changes.extend(
        change(start_beat + i * EASE_SECTION_BEATS, 1 if i % 2 == 0 else 2, ease, style)
        for i, ease in enumerate(EASINGS)
    )
    changes.append(change(start_beat + len(EASINGS) * EASE_SECTION_BEATS, 1, style=style))
    return LevelTimescaleGroup(changes=changes)


timescale_group = easing_group(4, TransitionStyle.TIMESCALE)
scroll_group = easing_group(52, TransitionStyle.SCROLL)

# Keep the three markers at beat 124 in order: each instantaneous change
# affects later note distances.
hybrid_group = LevelTimescaleGroup(
    changes=[
        change(0, 1),
        change(100, 1, EaseType.LINEAR, TransitionStyle.TIMESCALE),
        change(104, 2, EaseType.OUT_QUAD, TransitionStyle.SCROLL),
        change(108, 1, EaseType.IN_QUAD, TransitionStyle.TIMESCALE),
        change(112, 2, EaseType.IN_OUT_QUAD, TransitionStyle.SCROLL),
        change(116, 1, EaseType.NONE, TransitionStyle.TIMESCALE),
        change(120, 1, EaseType.NONE, TransitionStyle.SCROLL),
        change(124, 2, EaseType.NONE, TransitionStyle.TIMESCALE),
        change(124, 0.75, EaseType.NONE, TransitionStyle.SCROLL),
        change(124, 1.5, EaseType.NONE, TransitionStyle.TIMESCALE),
        change(128, 1.5, EaseType.LINEAR, TransitionStyle.SCROLL),
        change(132, 1),
    ]
)

# Compare signed speeds and skips using timescale transitions only.
# The stop from beats 136 to 140 lasts two seconds. Skips use beat units.
legacy_group = LevelTimescaleGroup(
    changes=[
        change(0, 1),
        change(132, 1, EaseType.LINEAR),
        change(136, 0),
        change(140, 0, EaseType.IN_QUAD),
        change(144, -1, EaseType.OUT_QUAD),
        change(148, 1),
        change(152, 1, skip=1),
        change(156, 1, EaseType.IN_OUT_QUAD, skip=-1),
        change(160, 0.5, EaseType.OUT_IN_QUAD),
        change(164, 1),
    ]
)

mixed_signed_group = LevelTimescaleGroup(
    changes=[
        change(0, 1),
        change(168, 1, EaseType.OUT_QUAD, TransitionStyle.SCROLL),
        change(172, 0, style=TransitionStyle.SCROLL),
        change(174, 0.00001, style=TransitionStyle.SCROLL),
        change(176, -0.5, EaseType.LINEAR, TransitionStyle.SCROLL),
        change(180, 1, EaseType.IN_QUAD, skip=0.5),
        change(184, -1, EaseType.OUT_QUAD, TransitionStyle.SCROLL, skip=-0.5),
        change(188, 1, style=TransitionStyle.SCROLL, skip=0.5),
        change(190, 1, skip=-0.5),
        change(192, 1),
    ]
)

burst_group = LevelTimescaleGroup(
    changes=[
        change(0, 1),
        change(192, 1),
        change(194, 1000),
        change(194.25, 1),
        change(196, 0.05, EaseType.IN_OUT_QUAD, TransitionStyle.SCROLL),
        change(200, 1),
        change(202, 10000),
        change(202.25, 1),
        change(204, 0.5, EaseType.OUT_IN_QUAD),
        change(206, 1),
    ]
)

groups = (timescale_group, scroll_group, hybrid_group, legacy_group, mixed_signed_group, burst_group)
sections = [
    DemoSection(
        f"{style_label}: {ease_label}", start + i * EASE_SECTION_BEATS, start + (i + 1) * EASE_SECTION_BEATS, group
    )
    for style_label, start, group in (("Timescale", 4, timescale_group), ("Scroll", 52, scroll_group))
    for i, ease_label in enumerate(EASE_LABELS)
]
sections.extend(
    [
        DemoSection("Alternating timescale and scroll", 100, 116, hybrid_group),
        DemoSection("Equal-speed style change, then held scroll step", 116, 124, hybrid_group),
        DemoSection("Ordered instantaneous steps at 62 seconds", 124, 128, hybrid_group),
        DemoSection("Scroll recovery", 128, 132, hybrid_group),
        DemoSection("Legacy: slow to a stop and hold", 132, 140, legacy_group),
        DemoSection("Legacy: reverse, then cross back through zero", 140, 148, legacy_group),
        DemoSection("Legacy: positive and negative skips", 148, 160, legacy_group),
        DemoSection("Timescale: quadratic recovery", 160, 168, legacy_group),
        DemoSection("Mixed: scroll slows to a stop", 168, 174, mixed_signed_group),
        DemoSection("Mixed: near-zero scroll, reverse and return", 174, 180, mixed_signed_group),
        DemoSection("Mixed: positive skip, reverse and negative skip", 180, 188, mixed_signed_group),
        DemoSection("Mixed: skips across a style change", 188, 192, mixed_signed_group),
        DemoSection("Brief 1000x burst and recovery", 192, 196, burst_group),
        DemoSection("Slow scroll returns to normal", 196, 200, burst_group),
        DemoSection("Brief 10000x burst and recovery", 200, 204, burst_group),
        DemoSection("Smooth recovery and steady finish", 204, NOTE_END_BEAT, burst_group),
    ]
)


def group_at_beat(beat: float) -> LevelTimescaleGroup:
    for section in sections:
        if beat < section.end_beat:
            return section.group
    return sections[-1].group


demo_notes = [
    LevelNote(
        beat=beat,
        lane=0,
        size=1,
        kind=NoteKind.NORM_TAP,
        timescale_group=group_at_beat(beat),
    )
    for i in range(int((NOTE_END_BEAT - NOTE_START_BEAT) / NOTE_STEP_BEATS) + 1)
    for beat in (NOTE_START_BEAT + i * NOTE_STEP_BEATS,)
]
reference_notes = [
    LevelNote(beat=note.beat, lane=3, size=1, kind=NoteKind.NORM_TAP, timescale_group=None) for note in demo_notes
]
notes = [note for pair in zip(demo_notes, reference_notes, strict=True) for note in pair]
entities: list[LevelEntities] = [LevelBpmChange(beat=0, bpm=BPM), *groups, *notes]

level = build_level(
    name="timescale-transition-demo",
    title="Timescale and Scroll Demo",
    bgm=_build_silent_wav(END_BEAT * 60 / BPM),
    entities=entities,
)
level.description = {
    "en": "Matched taps every eighth second: center follows each transition; right stays at normal speed. "
    "Silent audio; use autoplay to compare motion.\n\n"
    + "\n".join(
        f"{section.start_beat * 60 / BPM:g}-{section.end_beat * 60 / BPM:g}s: {section.label}" for section in sections
    )
}
