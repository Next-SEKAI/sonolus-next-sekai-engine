from sonolus.script import runtime
from sonolus.script.record import Record

LAYER_BACKGROUND_COVER = 0
LAYER_ACTIVE_SLIDE_CONNECTOR_UNDER = 1
LAYER_GUIDE_CONNECTOR_UNDER = 2
LAYER_STAGE = 3
LAYER_COVER = 4
LAYER_SLOT_EFFECT = 5

LAYER_BEAT_LINE = 6
LAYER_ACTIVE_SLIDE_CONNECTOR_BOTTOM = 7
LAYER_GUIDE_CONNECTOR_BOTTOM = 8
LAYER_ACTIVE_SLIDE_CONNECTOR_TOP = 9
LAYER_GUIDE_CONNECTOR_TOP = 10
LAYER_PREVIEW_COVER = 11
LAYER_SIM_LINE = 12
LAYER_TIME_LINE = 13
LAYER_BPM_LINE = 14
LAYER_TIMESCALE_LINE = 15

LAYER_NOTE_SLIM_BODY = 16
LAYER_NOTE_FLICK_BODY = 17
LAYER_NOTE_BODY = 18
LAYER_NOTE_TICK = 19
LAYER_NOTE_ARROW = 20
LAYER_SLOT_GLOW_EFFECT = 21

LAYER_ACTIVE_SLIDE_CONNECTOR_OVER = 22
LAYER_GUIDE_CONNECTOR_OVER = 23

LAYER_OVERLAY = 24


class ZIndexes(Record):
    z1: float
    z2: float
    z3: float
    z4: float

    @property
    def tuple(self) -> "tuple[float, float, float, float]":
        return self.z1, self.z2, self.z3, self.z4


def get_z(layer: int, time: float = 0.0, lane: float = 0.0, etc: int = 0, *, invert_time: bool = False) -> ZIndexes:
    return ZIndexes(
        z1=layer,
        z2=time - runtime.time() if invert_time else runtime.time() - time,
        z3=abs(lane) + (1 / 20) * (lane > 0),
        z4=etc,
    )


def get_z_alt(layer: int, sublayer: int) -> ZIndexes:
    return ZIndexes(
        z1=layer,
        z2=sublayer,
        z3=0.0,
        z4=0.0,
    )
