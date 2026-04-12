from sekai.level_utils import (
    LevelBpmChange,
    LevelNote,
    build_level,
)
from sekai.lib.note import NoteKind

level = build_level(
    name="test",
    title="Test",
    bgm=None,
    entities=[
        LevelBpmChange(beat=0.0, bpm=120.0),
        LevelNote(beat=1.0, lane=0.0, size=1.0, kind=NoteKind.NORM_TAP),
        LevelNote(beat=2.0, lane=-2.0, size=1.0, kind=NoteKind.NORM_TAP),
        LevelNote(beat=2.0, lane=2.0, size=1.0, kind=NoteKind.NORM_FLICK),
    ],
)


def load_levels():
    yield level
