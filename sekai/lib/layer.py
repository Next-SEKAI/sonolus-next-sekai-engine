from sonolus.script import runtime
from sonolus.script.numtools import make_comparable_float, quantize_to_step

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


def get_z(layer: int, time: float = 0.0, lane: float = 0.0, etc: int = 0, *, invert_time: bool = False) -> float:
    quantized_time = (runtime.time() * 256) // 256
    return make_comparable_float(
        quantize_to_step(layer, start=0, stop=25, step=1),
        quantize_to_step(
            time - quantized_time if invert_time else quantized_time - time, start=-30, stop=30, step=1 / 256
        ),
        quantize_to_step(abs(lane) + (1 / 20) * (lane > 0), start=0, stop=20, step=1 / 20),
        quantize_to_step(etc, start=0, stop=12, step=1),
    )


def get_z_alt(layer: int, sublayer: int) -> float:
    return make_comparable_float(
        quantize_to_step(layer, start=0, stop=25, step=1),
        quantize_to_step(sublayer, start=0, stop=73728000, step=1),
    )
