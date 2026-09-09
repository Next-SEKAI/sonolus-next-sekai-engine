"""Integrate easing curves and store cumulative distances in two parts."""

from math import trunc
from typing import Self

from sonolus.script.record import Record

from sekai.lib.ease import EaseType


class TimePosition(Record):
    """Whole scaled seconds and a signed remainder in (-1, 1).

    Binary32 stores the whole part exactly up to magnitude 2**24. Subtract
    matching parts before combining them to preserve small differences.
    Binary32 storage can round a binary64 remainder to either endpoint.
    """

    whole: float
    fraction: float

    @staticmethod
    def of(value: float) -> TimePosition:
        whole = trunc(value)
        return TimePosition(whole, value - whole)

    def add(self, value: float) -> Self:
        # Keep small negative remainders near zero instead of rounding near one.
        whole = trunc(value)
        remainder = self.fraction + (value - whole)
        carry = trunc(remainder)
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
    """Return the transition speed; NONE holds v0 until the next marker."""
    if ease == EaseType.NONE or t <= start:
        return v0
    if t >= end:
        return v1
    if v1 >= v0:
        return v0 + (v1 - v0) * _ease(ease, (t - start) / (end - start))
    return v1 + (v0 - v1) * _ease(_complement(ease), (end - t) / (end - start))


def _piece(v0: float, v1: float, ease: int, span: float, left: float, right: float, width: float) -> float:
    # Evaluate falling curves from the smaller endpoint to reduce cancellation.
    # Simpson's rule is exact for each quadratic piece.
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
    """Integrate within one event, splitting at the easing midpoint if needed."""
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
