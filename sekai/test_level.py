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
        beat=float(i),
        lane=-2.0 if i % 2 == 0 else 2.0,
        size=2.0,
        ease=EaseType.IN_OUT_QUAD,
    )
    for i in range(2 * ITERS + 1)
]

pivot_changes = [
    LevelStagePivotChange(
        beat=0.0,
        lane=0.0,
        division_size=1.0,
        division_parity=DivisionParity.EVEN,
        y_offset=0.0,
        ease=EaseType.LINEAR,
    ),
]

style_changes = [
    LevelStageStyleChange(
        beat=0.0,
        judge_line_color=JudgeLineColor.NEUTRAL,
        left_border_style=StageBorderStyle.DEFAULT,
        right_border_style=StageBorderStyle.DEFAULT,
        alpha=1.0,
        lane_alpha=1.0,
        ease=EaseType.LINEAR,
    ),
]

stage = LevelStage(
    from_start=False,
    mask_changes=mask_changes,
    pivot_changes=pivot_changes,
    style_changes=style_changes,
)

entities = [
    LevelBpmChange(beat=0.0, bpm=60.0),
    stage,
    LevelNote(beat=60.0, lane=0.0, size=1.0, kind=NoteKind.NORM_TAP),
]

level = build_level(
    name="test",
    title="Test",
    bgm=None,
    entities=entities,
)


def load_levels():
    yield level
