"""Independent Decimal oracle for ordered binary timescale/scroll timelines.

Inputs are converted seconds and integral skips, before any optional float32
quantization. Float inputs preserve their exact binary value; strings preserve
authored decimal values. This module imports no engine code and builds no tree,
run index, accumulated clock or cached factor history. Queries compose only the
original chronological links they cross, at a caller-selected Decimal precision.
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


def ease_value(ease, u):
    return ease_pair(ease, u)[0]


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
            if self.hybrid and (marker.speed <= 0 or marker.skip != 0):
                raise ValueError(f"Hybrid marker {i} requires positive speed and zero skip")
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
            return ONE, marker.speed * (end - start)
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
        va = self._speed_in_link(index, start)
        vb = next_marker.speed if destination else self._speed_in_link(index, end)
        return va / vb, va * (end - start)

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


def reciprocal_markers(cycles=5000, *, high="7.8", step="0.05", quantize=False):
    """Four links per cycle; net R=1 and B=step*(3+1/high)."""
    high, step = decimal(high), decimal(step)
    high = quantized32(high) if quantize else high
    speeds = (ONE, high, ONE, high)
    styles = (RefStyle.SCROLL, RefStyle.TIMESCALE, RefStyle.TIMESCALE, RefStyle.SCROLL)
    result = [RefMarker(i * step, speeds[i % 4], RefEase.LINEAR, styles[i % 4]) for i in range(4 * cycles)]
    result.append(RefMarker(4 * cycles * step, ONE))
    return result


def endpoint_log_markers(cycles=5000, *, step="0.05"):
    """Non-dyadic ratios with exact a*c=b*d; defeats rounded endpoint logs."""
    speeds = tuple(map(Decimal, ("1.125", "1.375", "4.8125", "3.9375")))
    step = decimal(step)
    result = [
        RefMarker(i * step, speeds[i % 4], RefEase.LINEAR, RefStyle.SCROLL if i % 2 == 0 else RefStyle.TIMESCALE)
        for i in range(4 * cycles)
    ]
    result.append(RefMarker(4 * cycles * step, speeds[0]))
    return result


def huge_exponent_markers(cycles=10000, *, shrinking=False, step="0.05"):
    """Two links/cycle with net R=2 or 1/2; 10k cycles exceed raw float range."""
    step = decimal(step)
    first_style = RefStyle.SCROLL if shrinking else RefStyle.TIMESCALE
    second_style = RefStyle.TIMESCALE if shrinking else RefStyle.SCROLL
    result = [
        RefMarker(i * step, ONE if i % 2 == 0 else TWO, RefEase.LINEAR, first_style if i % 2 == 0 else second_style)
        for i in range(2 * cycles)
    ]
    result.append(RefMarker(2 * cycles * step, ONE))
    return result


def non_dyadic_markers(transitions=20000, *, step="0.05"):
    """Deterministic practical positive corpus covering all six easings/styles."""
    speeds = tuple(map(Decimal, ("0.05", "0.07", "0.3", "1.125", "7.8", "8", "0.2", "3.9375")))
    step = decimal(step)
    return [RefMarker(i * step, speeds[i % len(speeds)], i % 6, i % 2) for i in range(transitions + 1)]


def visibility_island_markers():
    """D(t,3)=(1+(t-1)^2)*(3-t) on [0,2], minimum 50/27 at t=4/3."""
    return [
        RefMarker(0, 2, RefEase.OUT_QUAD, RefStyle.SCROLL),
        RefMarker(1, 1, RefEase.IN_QUAD, RefStyle.SCROLL),
        RefMarker(2, 2),
    ]
