"""Native easing and split cumulative distances for practical chart ranges."""

from math import floor, trunc
from typing import Self

from sonolus.script.record import Record

from sekai.lib.ease import EaseType


class TimePosition(Record):
    """Whole scaled seconds and a fractional remainder in [0, 1).

    The whole part stays exact in binary32 over the supported chart range.
    Subtract split prefixes before combining them to retain local differences.
    """

    whole: float
    fraction: float

    @staticmethod
    def of(value: float) -> TimePosition:
        whole = floor(value)
        return TimePosition(whole, value - whole)

    def add(self, value: float) -> Self:
        # Preserve small negative increments instead of rounding them near one.
        whole = trunc(value)
        remainder = self.fraction + (value - whole)
        carry = floor(remainder)
        return type(self)(self.whole + whole + carry, remainder - carry)

    def difference(self, other: Self) -> float:
        return (self.whole - other.whole) + (self.fraction - other.fraction)


def _ease(ease: int, u: float) -> float:
    if ease == EaseType.NONE:
        return 0.0
    if ease == EaseType.LINEAR:
        return u
    if ease == EaseType.IN_QUAD:
        return u * u
    if ease == EaseType.OUT_QUAD:
        return u * (2 - u)
    if ease == EaseType.IN_OUT_QUAD:
        if u <= 0.5:
            return 2 * u * u
        return 1 - 2 * (1 - u) * (1 - u)
    assert ease == EaseType.OUT_IN_QUAD, "Unknown timescale easing"
    if u <= 0.5:
        return 2 * u * (1 - u)
    return 0.5 + 2 * (u - 0.5) * (u - 0.5)


def _complement(ease: int) -> int:
    if ease == EaseType.IN_QUAD:
        return EaseType.OUT_QUAD
    if ease == EaseType.OUT_QUAD:
        return EaseType.IN_QUAD
    return ease


def speed_at(v0: float, v1: float, ease: int, start: float, end: float, t: float) -> float:
    """Local speed; a held transition changes only at the next marker."""
    if ease == EaseType.NONE or t <= start:
        return v0
    if t >= end:
        return v1
    if v1 >= v0:
        return v0 + (v1 - v0) * _ease(ease, (t - start) / (end - start))
    return v1 + (v0 - v1) * _ease(_complement(ease), (end - t) / (end - start))


def _piece(v0: float, v1: float, ease: int, span: float, left: float, right: float, width: float) -> float:
    # Anchor falling curves at the smaller endpoint as well. Simpson's rule is
    # exact for each quadratic piece, without subtracting two large integrals.
    if v1 < v0:
        v0, v1 = v1, v0
        ease = _complement(ease)
        left, right = span - right, span - left
    first = left / span
    middle = first + width / span * 0.5
    last = right / span
    average_ease = (_ease(ease, first) + 4 * _ease(ease, middle) + _ease(ease, last)) / 6
    return width * (v0 + (v1 - v0) * average_ease)


def integrate_times(v0: float, v1: float, ease: int, start: float, end: float, left: float, right: float) -> float:
    """Integrate inside one authored event, splitting quadratic halves once."""
    if start == end or left == right:
        return 0.0
    orientation = 1.0
    if left > right:
        left, right = right, left
        orientation = -1.0
    width = right - left
    if ease == EaseType.NONE:
        return orientation * width * v0
    span = end - start
    lo, hi = left - start, right - start
    midpoint = span * 0.5
    if ease in (EaseType.IN_OUT_QUAD, EaseType.OUT_IN_QUAD) and lo < midpoint < hi:
        first = _piece(v0, v1, ease, span, lo, midpoint, midpoint - lo)
        last = _piece(v0, v1, ease, span, midpoint, hi, hi - midpoint)
        return orientation * (first + last)
    return orientation * _piece(v0, v1, ease, span, lo, hi, width)
