from sonolus.script import runtime
from sonolus.script.record import Record


class Layer(Record):
    layer: int
    sublayer: int


class _Layers(Record):
    @property
    def background_cover(self) -> Layer:
        return Layer(0, 0)

    @property
    def active_slide_connector_under(self) -> Layer:
        return Layer(1, 0)

    @property
    def guide_connector_under(self) -> Layer:
        return Layer(2, 0)

    @property
    def stage(self) -> Layer:
        if runtime.is_preview():
            return Layer(3, 0)
        return Layer(16, -9)

    @property
    def cover(self) -> Layer:
        if runtime.is_preview():
            return Layer(4, 0)
        return Layer(16, -8)

    @property
    def slot_effect(self) -> Layer:
        if runtime.is_preview():
            return Layer(5, 0)
        return Layer(16, -7)

    @property
    def beat_line(self) -> Layer:
        return Layer(6, 0)

    @property
    def active_slide_connector_bottom(self) -> Layer:
        if runtime.is_preview():
            return Layer(7, 0)
        return Layer(16, -5)

    @property
    def guide_connector_bottom(self) -> Layer:
        if runtime.is_preview():
            return Layer(8, 0)
        return Layer(16, -4)

    @property
    def active_slide_connector_top(self) -> Layer:
        if runtime.is_preview():
            return Layer(9, 0)
        return Layer(16, -3)

    @property
    def guide_connector_top(self) -> Layer:
        if runtime.is_preview():
            return Layer(10, 0)
        return Layer(16, -2)

    @property
    def preview_cover(self) -> Layer:
        return Layer(11, 0)

    @property
    def sim_line(self) -> Layer:
        if runtime.is_preview():
            return Layer(12, 0)
        return Layer(16, -1)

    @property
    def time_line(self) -> Layer:
        return Layer(13, 0)

    @property
    def bpm_line(self) -> Layer:
        return Layer(14, 0)

    @property
    def timescale_line(self) -> Layer:
        return Layer(15, 0)

    @property
    def note(self) -> Layer:
        return Layer(16, 0)

    @property
    def note_slim_body(self) -> Layer:
        return Layer(16, 0)

    @property
    def note_flick_body(self) -> Layer:
        return Layer(16, 1)

    @property
    def note_body(self) -> Layer:
        return Layer(16, 2)

    @property
    def note_tick(self) -> Layer:
        return Layer(16, 3)

    @property
    def note_arrow(self) -> Layer:
        return Layer(16, 4)

    @property
    def slot_glow_effect(self) -> Layer:
        return Layer(16, 5)

    @property
    def active_slide_connector_over(self) -> Layer:
        return Layer(22, 0)

    @property
    def guide_connector_over(self) -> Layer:
        return Layer(23, 0)

    @property
    def overlay(self) -> Layer:
        return Layer(24, 0)


layers = _Layers()


class ZIndexes(Record):
    z1: float
    z2: float
    z3: float
    z4: float

    @property
    def tuple(self) -> "tuple[float, float, float, float]":
        return self.z1, self.z2, self.z3, self.z4


def get_z(
    layer: Layer,
    time: float = 0.0,
    lane: float = 0.0,
    etc: int = 0,
    *,
    elevation: float = 0.0,
    invert_time: bool = False,
) -> ZIndexes:
    return ZIndexes(
        z1=layer.layer,
        z2=elevation + layer.sublayer * 0.01,
        z3=time - runtime.time() if invert_time else runtime.time() - time,
        z4=abs(lane) + (1 / 20) * (lane > 0) + etc * 1e-6,
    )


def get_z_alt(layer: Layer, order: int, *, elevation: float = 0.0) -> ZIndexes:
    return ZIndexes(
        z1=layer.layer,
        z2=elevation + layer.sublayer * 0.01,
        z3=order,
        z4=0.0,
    )
