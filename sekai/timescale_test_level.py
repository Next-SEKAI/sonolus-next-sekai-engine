"""One even tap stream demonstrating timescale and scroll transition behavior.

Select "Timescale and Scroll Demo" from the project's test levels. The level
description lists each section in seconds; BPM 120 makes every two beats one
second. All notes stay in the center lane, with no attachments or connectors.
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
NOTE_END_BEAT = 168.0
NOTE_STEP_BEATS = 0.5
END_BEAT = 172.0
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
    # Alternate 1->2 and 2->1, giving each easing a full four-second example.
    # The initial hold and final tail use the same style as the entire group.
    changes = [change(0, 1, style=style)]
    changes.extend(
        change(start_beat + i * EASE_SECTION_BEATS, 1 if i % 2 == 0 else 2, ease, style)
        for i, ease in enumerate(EASINGS)
    )
    changes.append(change(start_beat + len(EASINGS) * EASE_SECTION_BEATS, 1, style=style))
    return LevelTimescaleGroup(changes=changes)


timescale_group = easing_group(4, TransitionStyle.TIMESCALE)
scroll_group = easing_group(52, TransitionStyle.SCROLL)

# Every positive transition carries its factors across the style boundary.
# At beat 124, preserve these three markers in authored order: the incoming
# scroll step, a zero-duration timescale step, then a zero-duration scroll step.
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

# Signed speeds and skips belong to a separate all-timescale group. The stop
# from beats 136..140 lasts two seconds. Skips are in the legacy beat units.
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

groups = (timescale_group, scroll_group, hybrid_group, legacy_group)
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
        DemoSection("Legacy: quadratic recovery and steady tail", 160, NOTE_END_BEAT, legacy_group),
    ]
)


def group_at_beat(beat: float) -> LevelTimescaleGroup:
    for section in sections:
        if beat < section.end_beat:
            return section.group
    return legacy_group


notes = [
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
entities: list[LevelEntities] = [LevelBpmChange(beat=0, bpm=BPM), *groups, *notes]

level = build_level(
    name="timescale-transition-demo",
    title="Timescale and Scroll Demo",
    bgm=_build_silent_wav(END_BEAT * 60 / BPM),
    entities=entities,
)
level.description = {
    "en": "A continuous center-lane tap every quarter second. Silent audio; use autoplay to inspect motion.\n\n"
    + "\n".join(
        f"{section.start_beat * 60 / BPM:g}-{section.end_beat * 60 / BPM:g}s: {section.label}" for section in sections
    )
}
