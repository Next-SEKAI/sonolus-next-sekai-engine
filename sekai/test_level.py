from sekai.level_utils import (
    LevelBpmChange,
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

ITERS = 60
mask_changes = [
    LevelStageMaskChange(
        beat=0.0,
        lane=-2.0,
        size=2.0,
        ease=EaseType.LINEAR,
    ),
    *[
        LevelStageMaskChange(
            beat=float(i) + 2.0,
            lane=-2.0 if i % 2 == 0 else 2.0,
            size=2.0,
            ease=EaseType.IN_OUT_QUAD,
        )
        for i in range(2 * ITERS + 1)
    ],
]

pivot_changes = [
    LevelStagePivotChange(
        beat=0.0,
        lane=2.0,
        division_size=2.0,
        division_parity=DivisionParity.EVEN,
        y_offset=0.0,
        ease=EaseType.LINEAR,
    ),
    *[
        LevelStagePivotChange(
            beat=float(i) + 2.0,
            lane=2.0 if i % 2 == 0 else -2.0,
            division_size=2.0,
            division_parity=DivisionParity.EVEN,
            y_offset=0.0,
            ease=EaseType.IN_OUT_QUAD,
        )
        for i in range(2 * ITERS + 1)
    ],
]

style_changes = [
    LevelStageStyleChange(
        beat=0.0,
        judge_line_color=JudgeLineColor.RED,
        left_border_style=StageBorderStyle.DEFAULT,
        right_border_style=StageBorderStyle.DEFAULT,
        alpha=0.0,
        lane_alpha=0.0,
        ease=EaseType.LINEAR,
    ),
    *[
        LevelStageStyleChange(
            beat=float(i) + 2.0,
            judge_line_color=JudgeLineColor.RED if i % 2 == 0 else JudgeLineColor.BLUE,
            left_border_style=StageBorderStyle.DEFAULT,
            right_border_style=StageBorderStyle.DEFAULT,
            alpha=1.0,
            lane_alpha=1.0,
            ease=EaseType.IN_OUT_QUAD,
        )
        for i in range(2 * ITERS + 1)
    ],
]

stage = LevelStage(
    from_start=True,
    mask_changes=mask_changes,
    pivot_changes=pivot_changes,
    style_changes=style_changes,
)

entities = [
    LevelBpmChange(beat=0.0, bpm=60.0),
    stage,
    *[
        LevelNote(beat=4.0 + i / 4.0, lane=0.0, size=1.0, kind=NoteKind.NORM_TRACE, stage=stage)
        for i in range((2 * ITERS + 2 - 4) * 4 + 1)
    ],
]

level = build_level(
    name="test",
    title="Test",
    bgm=None,
    entities=entities,
)


def load_levels():
    yield level
