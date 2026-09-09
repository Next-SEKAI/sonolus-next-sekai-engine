"""Independent Decimal oracle for ordered binary timescale/scroll timelines.

Inputs are converted seconds and integral skips, before any optional float32
quantization. Float inputs preserve their exact binary value; strings preserve
authored decimal values. Queries compose the original chronological links
directly, independently of the engine implementation.
"""

from bisect import bisect_right
from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import IntEnum
from itertools import pairwise
from struct import pack, unpack

ZERO = Decimal(0)
ONE = Decimal(1)
TWO = Decimal(2)
SCROLL_EPSILON = Decimal.from_float(1e-4)
type DecimalInput = Decimal | int | float | str


class RefEase(IntEnum):
    NONE = 0
    LINEAR = 1
    IN_QUAD = 2
    OUT_QUAD = 3
    IN_OUT_QUAD = 4
    OUT_IN_QUAD = 5


class RefStyle(IntEnum):
    TIMESCALE = 0
    SCROLL = 1


def decimal(value):
    """Preserve exact binary float inputs; never silently round through str."""
    return value if isinstance(value, Decimal) else Decimal(value)


def quantized32(value):
    """Return the exact Decimal value of a binary32-quantized input."""
    return Decimal.from_float(unpack("f", pack("f", float(value)))[0])


def ease_pair(ease, u):
    """Return E and its separately evaluated nonnegative complement on [0,1]."""
    u = decimal(u)
    complement = ONE - u
    if ease == RefEase.NONE:
        return ZERO, ONE
    if ease == RefEase.LINEAR:
        return u, complement
    if ease == RefEase.IN_QUAD:
        return u * u, complement * (ONE + u)
    if ease == RefEase.OUT_QUAD:
        return u * (TWO - u), complement * complement
    if ease == RefEase.IN_OUT_QUAD:
        if u <= Decimal("0.5"):
            value = TWO * u * u
            return value, ONE - value
        remainder = TWO * complement * complement
        return ONE - remainder, remainder
    if ease == RefEase.OUT_IN_QUAD:
        if u <= Decimal("0.5"):
            return TWO * u * complement, Decimal("0.5") + TWO * (Decimal("0.5") - u) ** 2
        return Decimal("0.5") + TWO * (u - Decimal("0.5")) ** 2, TWO * u * complement
    raise ValueError(f"Invalid easing value: {ease}")


def speed_value(v0, v1, ease, u):
    """Local curve speed; NONE excludes the separate destination step."""
    v0, v1, u = decimal(v0), decimal(v1), decimal(u)
    if ease == RefEase.NONE or u == ZERO:
        return v0
    if u == ONE:
        return v1
    value, complement = ease_pair(ease, u)
    if v1 >= v0:
        return v0 + (v1 - v0) * value
    return v1 + (v0 - v1) * complement


def integrate_speed(v0, v1, ease, duration, left: DecimalInput = 0, right: DecimalInput | None = None):
    """Exact quadratic-piece identity, using event-local offsets and short widths.

    Decimal rounding remains; there is no quadrature approximation or subtraction
    of large primitive values. Reversing offsets returns the oriented integral.
    """
    v0, v1, duration, left = map(decimal, (v0, v1, duration, left))
    right = duration if right is None else decimal(right)
    if duration == ZERO or left == right:
        return ZERO
    if right < left:
        return -integrate_speed(v0, v1, ease, duration, right, left)
    if ease == RefEase.NONE:
        return v0 * (right - left)
    points = [left]
    midpoint = duration / TWO
    if ease in (RefEase.IN_OUT_QUAD, RefEase.OUT_IN_QUAD) and left < midpoint < right:
        points.append(midpoint)
    points.append(right)
    result = ZERO
    for a, b in pairwise(points):
        width = b - a
        middle = a + width / TWO
        values = (
            speed_value(v0, v1, ease, a / duration),
            speed_value(v0, v1, ease, middle / duration),
            speed_value(v0, v1, ease, b / duration),
        )
        result += width * (values[0] + 4 * values[1] + values[2]) / 6
    return result


@dataclass(frozen=True, init=False)
class RefMarker:
    time: Decimal
    speed: Decimal
    ease: int = RefEase.NONE
    style: int = RefStyle.TIMESCALE
    skip: Decimal = ZERO
    hide: bool = False

    def __init__(
        self,
        time: DecimalInput,
        speed: DecimalInput,
        ease: int = RefEase.NONE,
        style: int = RefStyle.TIMESCALE,
        skip: DecimalInput = ZERO,
        hide: bool = False,
    ):
        for name, value in (("time", time), ("speed", speed), ("skip", skip)):
            object.__setattr__(self, name, decimal(value))
        object.__setattr__(self, "ease", ease)
        object.__setattr__(self, "style", style)
        object.__setattr__(self, "hide", hide)


def scroll_speed(value):
    return min(value, -SCROLL_EPSILON) if value < ZERO else max(value, SCROLL_EPSILON)


def compose(left, right):
    """Chronological affine transfer composition: left happens before right."""
    r1, b1 = left
    r2, b2 = right
    return r1 * r2, b1 + r1 * b2


class RefTimeline:
    def __init__(self, markers=(), *, precision=100):
        self.markers = tuple(markers)
        self.times = tuple(marker.time for marker in self.markers)
        self.precision = precision
        self.hybrid = any(marker.style == RefStyle.SCROLL for marker in self.markers)
        previous = None
        for i, marker in enumerate(self.markers):
            if not all(value.is_finite() for value in (marker.time, marker.speed, marker.skip)):
                raise ValueError(f"Marker {i} has a nonfinite time, speed or skip")
            if marker.ease not in tuple(RefEase) or marker.style not in tuple(RefStyle):
                raise ValueError(f"Marker {i} has an invalid easing or style")
            if previous is not None and marker.time < previous:
                raise ValueError(f"Marker {i} goes backward in time; preserve chronological chain order")
            previous = marker.time

    def locate_time(self, time):
        """Last original marker at or before time; -1 denotes the prelude."""
        return bisect_right(self.times, decimal(time)) - 1

    def _speed_in_link(self, index, time):
        marker = self.markers[index]
        if index + 1 == len(self.markers):
            return marker.speed
        next_marker = self.markers[index + 1]
        duration = next_marker.time - marker.time
        if duration == 0:
            return marker.speed
        return speed_value(marker.speed, next_marker.speed, marker.ease, (time - marker.time) / duration)

    def speed(self, time):
        time = decimal(time)
        with localcontext() as context:
            context.prec = self.precision
            index = self.locate_time(time)
            return ONE if index < 0 else self._speed_in_link(index, time)

    def hidden(self, time):
        index = self.locate_time(time)
        return index >= 0 and self.markers[index].hide

    def _partial_link(self, index, start, end, *, destination):
        if index < 0:
            return ONE, end - start + (self.markers[0].skip if destination else ZERO)
        marker = self.markers[index]
        if index + 1 == len(self.markers):
            speed = scroll_speed(marker.speed) if marker.style == RefStyle.SCROLL else marker.speed
            return ONE, speed * (end - start)
        next_marker = self.markers[index + 1]
        if marker.style == RefStyle.TIMESCALE:
            integral = integrate_speed(
                marker.speed,
                next_marker.speed,
                marker.ease,
                next_marker.time - marker.time,
                start - marker.time,
                end - marker.time,
            )
            return ONE, integral + (next_marker.skip if destination else ZERO)
        va = scroll_speed(self._speed_in_link(index, start))
        vb = scroll_speed(next_marker.speed if destination else self._speed_in_link(index, end))
        # A completed marker skip is measured in its outgoing local distance units.
        jump = next_marker.skip / vb if destination else ZERO
        return va / vb, va * (end - start + jump)

    def anchor_transfer(self, first, last):
        """Transfer between raw ordered marker states, retaining same-time links."""
        if not 0 <= first <= last < len(self.markers):
            raise ValueError("Expected ordered marker indices 0 <= first <= last < marker count")
        with localcontext() as context:
            context.prec = self.precision
            result = (ONE, ZERO)
            for index in range(first, last):
                result = compose(
                    result,
                    self._partial_link(index, self.markers[index].time, self.markers[index + 1].time, destination=True),
                )
            return result

    def transfer(self, start, end):
        """Chronological transfer between completed public timestamp states."""
        start, end = decimal(start), decimal(end)
        if end < start:
            raise ValueError("transfer requires start <= end; use distance for oriented queries")
        with localcontext() as context:
            context.prec = self.precision
            index, final = self.locate_time(start), self.locate_time(end)
            cursor, result = start, (ONE, ZERO)
            while index < final:
                destination = self.markers[index + 1].time
                result = compose(result, self._partial_link(index, cursor, destination, destination=True))
                cursor = destination
                index += 1
            if cursor < end:
                result = compose(result, self._partial_link(index, cursor, end, destination=False))
            return result

    def distance(self, time, hit_time):
        time, hit_time = decimal(time), decimal(hit_time)
        with localcontext() as context:
            context.prec = self.precision
            if time <= hit_time:
                return self.transfer(time, hit_time)[1]
            ratio, integral = self.transfer(hit_time, time)
            return -integral / ratio


def visibility_island_markers():
    """D(t,3)=(1+(t-1)^2)*(3-t) on [0,2], minimum 50/27 at t=4/3."""
    return [
        RefMarker(0, 2, RefEase.OUT_QUAD, RefStyle.SCROLL),
        RefMarker(1, 1, RefEase.IN_QUAD, RefStyle.SCROLL),
        RefMarker(2, 2),
    ]
