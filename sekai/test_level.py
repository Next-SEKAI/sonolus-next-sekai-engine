from sekai.level_utils import (
    LevelBpmChange,
    LevelCameraChange,
    LevelNote,
    LevelStage,
    LevelStageMaskChange,
    LevelStagePivotChange,
    LevelStageStyleChange,
    build_level,
)
from sekai.lib.ease import EaseType
from sekai.lib.note import NoteKind
from sekai.lib.stage import DivisionParity, JudgeLineColor, StageBorderStyle

CYCLE_BEATS = 16
CYCLES = 8
TOTAL_BEATS = CYCLE_BEATS * CYCLES

mask_changes = [
    LevelStageMaskChange(beat=0.0, lane=0.0, size=6.0, ease=EaseType.LINEAR),
]

pivot_changes = [
    LevelStagePivotChange(
        beat=0.0,
        lane=0.0,
        division_size=2.0,
        division_parity=DivisionParity.EVEN,
        abs_y_offset=0.0,
        y_beat_offset=0.0,
        ease=EaseType.LINEAR,
    ),
]

style_changes = [
    LevelStageStyleChange(
        beat=0.0,
        judge_line_color=JudgeLineColor.PURPLE,
        left_border_style=StageBorderStyle.DEFAULT,
        right_border_style=StageBorderStyle.DEFAULT,
        alpha=1.0,
        lane_alpha=1.0,
        judge_line_alpha=1.0,
        ease=EaseType.LINEAR,
    ),
]

stage = LevelStage(
    from_start=True,
    until_end=True,
    mask_changes=mask_changes,
    pivot_changes=pivot_changes,
    style_changes=style_changes,
)

camera_changes = [
    LevelCameraChange(beat=0.0, lane=0.0, size=6.0, ease=EaseType.IN_OUT_QUAD),
]
for cycle in range(CYCLES):
    base = cycle * CYCLE_BEATS
    camera_changes.extend(
        [
            LevelCameraChange(beat=base + 4.0, lane=-3.0, size=3.0, ease=EaseType.IN_OUT_QUAD),
            LevelCameraChange(beat=base + 8.0, lane=3.0, size=3.0, ease=EaseType.IN_OUT_QUAD),
            LevelCameraChange(beat=base + 12.0, lane=0.0, size=8.0, ease=EaseType.IN_OUT_QUAD),
        ]
    )

NOTE_LANES = (-5.0, -3.0, -1.0, 1.0, 3.0, 5.0)
NOTE_START_BEAT = 4.0
NOTE_END_BEAT = TOTAL_BEATS - 4.0
NOTE_STEP_COUNT = int((NOTE_END_BEAT - NOTE_START_BEAT) * 2) + 1

notes = [
    LevelNote(
        beat=NOTE_START_BEAT + i / 2.0,
        lane=lane,
        size=1.0,
        kind=NoteKind.NORM_TAP,
        stage=stage,
    )
    for i in range(NOTE_STEP_COUNT)
    for lane in NOTE_LANES
]

entities = [
    LevelBpmChange(beat=0.0, bpm=60.0),
    stage,
    *camera_changes,
    *notes,
]

level = build_level(
    name="test",
    title="Test",
    bgm=None,
    entities=entities,
)


def load_levels():
    yield level
