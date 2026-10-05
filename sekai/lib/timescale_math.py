from math import asin, log, pi, sin, sqrt, trunc
from typing import Self

from sonolus.script.array import Array
from sonolus.script.easing import ease_in_out_quad, ease_out_in_quad, ease_out_quad
from sonolus.script.interval import clamp
from sonolus.script.record import Record

from sekai.lib.ease import (
    EaseFamily,
    EaseMode,
    EaseType,
    ease_complement,
    ease_family,
    ease_mode,
    is_in_step_ease,
    is_step_ease,
)
from sekai.lib.ease import ease as ease_value

SIMPSON_WEIGHTS = Array(1 / 6, 4 / 6, 1 / 6)


class TimePosition(Record):
    """Scaled time split into whole seconds and a signed fraction.

    Keeping the parts separate preserves small differences at large times.
    Whole seconds remain exact in f32 through 2**24. A stored fraction may
    round to -1 or 1.
    """

    whole: float
    fraction: float

    @staticmethod
    def of(value: float) -> TimePosition:
        whole = trunc(value)
        return TimePosition(whole, value - whole)

    def add(self, value: float) -> Self:
        # Truncate toward zero to preserve small negative fractions.
        whole = trunc(value)
        remainder = self.fraction + (value - whole)
        carry = trunc(remainder)
        return type(self)(self.whole + whole + carry, remainder - carry)

    def difference(self, other: Self) -> float:
        return (self.whole - other.whole) + (self.fraction - other.fraction)


def _in_integral(family: EaseFamily, y: float) -> float:
    """Integrate the IN form of a family from 0 to y."""
    match family:
        case EaseFamily.QUAD:
            return y**3 / 3
        case EaseFamily.SINE:
            return y - sin(y * pi / 2) * 2 / pi
        case EaseFamily.CUBIC:
            return y**4 / 4
        case EaseFamily.QUART:
            return y**5 / 5
        case EaseFamily.QUINT:
            return y**6 / 6
        case EaseFamily.EXPO:
            return (2 ** (10 * y - 10) - 2**-10) / (10 * log(2))
        case EaseFamily.CIRC:
            return y - (y * sqrt(1 - y * y) + asin(y)) / 2
        case _:
            return 0.0


def _in_integral_total(family: EaseFamily) -> float:
    match family:
        case EaseFamily.QUAD:
            return 1 / 3
        case EaseFamily.SINE:
            return 1 - 2 / pi
        case EaseFamily.CUBIC:
            return 1 / 4
        case EaseFamily.QUART:
            return 1 / 5
        case EaseFamily.QUINT:
            return 1 / 6
        case EaseFamily.EXPO:
            return (1 - 2**-10) / (10 * log(2))
        case EaseFamily.CIRC:
            return 1 - pi / 4
        case _:
            return 0.0


def _ease_integral(ease: EaseType, u: float) -> float:
    """Integrate the ease from 0 to u, holding its end values outside [0, 1]."""
    extra = max(0.0, u - 1)
    u = clamp(u, 0.0, 1.0)
    if ease == EaseType.LINEAR:
        return u * u / 2 + extra
    if ease == EaseType.NONE:
        return extra
    # Every mode scales and offsets the integral of the IN form, as in ease.
    family = ease_family(ease)
    mode = ease_mode(ease)
    base, scale, y = 0.0, 1.0, u
    if mode == EaseMode.OUT:
        base, scale, y = u - _in_integral_total(family), 1.0, 1 - u
    elif mode == EaseMode.IN_OUT:
        if u <= 0.5:
            base, scale, y = 0.0, 0.25, 2 * u
        else:
            base, scale, y = u - 0.5, 0.25, 2 - 2 * u
    elif mode == EaseMode.OUT_IN:
        if u <= 0.5:
            base, scale, y = u / 2 - _in_integral_total(family) / 4, 0.25, 1 - 2 * u
        else:
            base, scale, y = 0.25 - _in_integral_total(family) / 4 + (u - 0.5) / 2, 0.25, 2 * u - 1
    return base + scale * _in_integral(family, y) + extra


def speed_at(v0: float, v1: float, ease: int, start: float, end: float, t: float) -> float:
    if is_in_step_ease(ease) or t <= start:
        return v0
    if t >= end:
        return v1
    u = (t - start) / (end - start)
    # Evaluate falling curves from the lower speed to reduce rounding error.
    if v1 < v0:
        v0, v1 = v1, v0
        ease = ease_complement(ease)
        u = (end - t) / (end - start)
    return v0 + (v1 - v0) * ease_value(ease, u)


def _quadratic_ease(ease: int, u: float) -> float:
    if ease == EaseType.LINEAR:
        return u
    if ease == EaseType.IN_QUAD:
        # A direct square lets the optimizer combine surrounding multiplications.
        return u * u
    if ease == EaseType.OUT_QUAD:
        return ease_out_quad(u)
    if ease == EaseType.IN_OUT_QUAD:
        return ease_in_out_quad(u)
    return ease_out_in_quad(u)


def _quadratic_piece(v0: float, v1: float, ease: int, span: float, left: float, right: float, width: float) -> float:
    # Evaluate falling curves from the lower speed to reduce rounding error.
    if v1 < v0:
        v0, v1 = v1, v0
        ease = ease_complement(ease)
        left, right = span - right, span - left
    first = left / span
    middle = first + width / span * 0.5
    last = right / span
    # The 1:4:1 weights give the exact average of a quadratic, apart from rounding.
    average_ease = (_quadratic_ease(ease, first) + 4 * _quadratic_ease(ease, middle) + _quadratic_ease(ease, last)) / 6
    return width * (v0 + (v1 - v0) * average_ease)


def _piece(v0: float, v1: float, ease: int, span: float, left: float, right: float, width: float) -> float:
    # Evaluate falling curves from the lower speed to reduce rounding error.
    if v1 < v0:
        v0, v1 = v1, v0
        ease = ease_complement(ease)
        left, right = span - right, span - left
    first = left / span
    last = right / span
    average = 0.0
    # The 1:4:1 weights give the exact average of a cubic, apart from rounding. They also approximate other
    # curves well over narrow pieces, where the integral below loses precision to cancellation.
    if ease <= EaseType.OUT_IN_QUAD or EaseType.IN_CUBIC <= ease <= EaseType.OUT_IN_CUBIC or width <= span * 2**-6:
        half = (last - first) * 0.5
        for i in range(3):
            average += SIMPSON_WEIGHTS[i] * ease_value(ease, first + half * i)
    else:
        for i in range(2):
            average += (1 if i == 1 else -1) * _ease_integral(ease, last if i == 1 else first)
        average *= span / width
    return width * (v0 + (v1 - v0) * average)


def integrate_times(v0: float, v1: float, ease: int, start: float, end: float, left: float, right: float) -> float:
    if ease == EaseType.NONE or not EaseType.LINEAR <= ease <= EaseType.OUT_IN_QUAD:
        return integrate_eased_times(v0, v1, ease, start, end, left, right)
    # Inline the common linear and quadratic eases, which callers evaluate for each note.
    if start == end or left == right:
        return 0.0
    orientation = 1.0
    if left > right:
        left, right = right, left
        orientation = -1.0
    span = end - start
    lo, hi = left - start, right - start
    midpoint = span * 0.5
    if ease in (EaseType.IN_OUT_QUAD, EaseType.OUT_IN_QUAD) and lo < midpoint < hi:
        first = _quadratic_piece(v0, v1, ease, span, lo, midpoint, midpoint - lo)
        last = _quadratic_piece(v0, v1, ease, span, midpoint, hi, hi - midpoint)
        return orientation * (first + last)
    return orientation * _quadratic_piece(v0, v1, ease, span, lo, hi, hi - lo)


def integrate_eased_times(
    v0: float, v1: float, ease: int, start: float, end: float, left: float, right: float
) -> float:
    if start == end or left == right:
        return 0.0
    orientation = 1.0
    if left > right:
        left, right = right, left
        orientation = -1.0
    width = right - left
    span = end - start
    lo, hi = left - start, right - start
    midpoint = span * 0.5
    if is_step_ease(ease):
        if ease == EaseType.OUT_STEP:
            return orientation * width * v1
        if ease == EaseType.OUT_IN_STEP:
            return orientation * width * (v0 + v1) * 0.5
        if ease == EaseType.IN_OUT_STEP:
            before = max(0.0, min(hi, midpoint) - lo)
            return orientation * (before * v0 + (width - before) * v1)
        return orientation * width * v0
    # Split at the middle, where the two halves of in-out and out-in eases meet.
    split = ease_mode(ease) >= EaseMode.IN_OUT and ease != EaseType.LINEAR and lo < midpoint < hi
    total = 0.0
    for piece in range(2 if split else 1):
        piece_lo = midpoint if piece == 1 else lo
        piece_hi = midpoint if split and piece == 0 else hi
        total += _piece(v0, v1, ease, span, piece_lo, piece_hi, piece_hi - piece_lo)
    return orientation * total
