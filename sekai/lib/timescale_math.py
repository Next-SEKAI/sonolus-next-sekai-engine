"""Local polynomial kernels and bounded, range-safe timescale arithmetic.

Certificates assume correctly rounded operations of at least binary32 precision,
with gradual underflow or the explicitly guarded small-term paths below. Inputs
to ``of`` are already quantized engine inputs. A four-scalar value denotes
``[(hi + lo) - error, (hi + lo) + error] * 2**exponent``.

Accurate pairs serve preprocessing, shared frame state, and refinement.
Published and native helpers handle per-note work without global scale factors.
"""

from math import floor, inf
from typing import Self

from sonolus.script.record import Record

from sekai.lib.ease import EaseType

UNIT_ROUNDOFF = 2.0**-24
ERROR_FLOOR = 2.0**-100
ALIGNMENT_LIMIT = 60
MAX_EXPONENT = 1_000_000


class _Pair(Record):
    hi: float
    lo: float


class NativeProgress(Record):
    """An ordinary scalar and absolute error, without a scaled-value contract."""

    value: float
    error: float


class _NativeExpansion(Record):
    hi: float
    lo: float
    error: float


def _two_sum(a: float, b: float) -> _Pair:
    total = a + b
    recovered = total - a
    residual = (a - (total - recovered)) + (b - recovered)
    return _Pair(total, residual)


def _two_product(a: float, b: float) -> _Pair:
    # Inputs have at most 24 significand bits; Dekker's split is exact in both
    # binary32 and binary64 arithmetic without relying on fused operations.
    product = a * b
    ca = 4097 * a
    cb = 4097 * b
    ah = ca - (ca - a)
    bh = cb - (cb - b)
    al = a - ah
    bl = b - bh
    residual = ((ah * bh - product) + ah * bl + al * bh) + al * bl
    return _Pair(product, residual)


def _outward(radius: float) -> float:
    if radius == 0:
        return 0.0
    return radius * (1 + 16 * UNIT_ROUNDOFF) + ERROR_FLOOR


def _power_two_small(exponent: int) -> float:
    """A bounded exact power, used only with exponents in [-60, 60]."""
    return 2.0**exponent


class AccurateScalar(Record):
    hi: float
    lo: float
    exponent: int
    error: float

    @staticmethod
    def of(value: float) -> AccurateScalar:
        assert -inf < value < inf, "Timescale scalar input must be finite"
        return _normalize(value, 0.0, 0, 0.0)

    @staticmethod
    def difference(end: float, start: float) -> AccurateScalar:
        """Subtract quantized times with one normalization and an exact residual."""
        result = +AccurateScalar
        assert -inf < end < inf, "Timescale time input must be finite"
        assert -inf < start < inf, "Timescale time input must be finite"
        if abs(end) <= 2.0**120 and abs(start) <= 2.0**120:
            pair = _two_sum(end, -start)
            result @= _normalize(pair.hi, pair.lo, 0, 0.0)
        else:
            result @= AccurateScalar.of(end).sub(AccurateScalar.of(start))
        return result

    def neg(self) -> Self:
        return type(self)(-self.hi, -self.lo, self.exponent, self.error)

    def add(self, other: AccurateScalar) -> Self:
        result = +type(self)
        if self.hi == 0 and self.lo == 0 and self.error == 0:
            result @= other
        elif other.hi == 0 and other.lo == 0 and other.error == 0:
            result @= self
        else:
            larger = +self
            smaller = +other
            if self.exponent < other.exponent:
                larger @= other
                smaller @= self
            gap = larger.exponent - smaller.exponent
            if gap > ALIGNMENT_LIMIT:
                omitted = (abs(smaller.hi) + abs(smaller.lo) + smaller.error) * 2.0**-ALIGNMENT_LIMIT
                result @= _normalize(larger.hi, larger.lo, larger.exponent, _outward(larger.error + omitted))
            else:
                factor = _power_two_small(-gap)
                pair = _two_sum(larger.hi, smaller.hi * factor)
                if larger.lo == 0 and smaller.lo == 0 and larger.error == 0 and smaller.error == 0:
                    # The aligned inputs are normal exact binary scalars and
                    # TwoSum preserves their sum exactly. In particular, close
                    # quantized song times must not accrue an error proportional
                    # to their absolute timestamp at every marker.
                    result @= _normalize(pair.hi, pair.lo, larger.exponent, 0.0)
                else:
                    tail = (larger.lo + smaller.lo * factor) + pair.lo
                    combined = _two_sum(pair.hi, tail)
                    radius = larger.error + smaller.error * factor
                    # TwoSum accounts for the head sum exactly. Only the two
                    # low-tail additions round; 4u times their absolute terms
                    # bounds those operations, including a rounded partial sum.
                    radius += 4 * UNIT_ROUNDOFF * (abs(larger.lo) + abs(smaller.lo * factor) + abs(pair.lo))
                    result @= _normalize(combined.hi, combined.lo, larger.exponent, _outward(radius))
        return result

    def sub(self, other: AccurateScalar) -> Self:
        return self.add(other.neg())

    def mul(self, other: AccurateScalar) -> Self:
        result = +type(self)
        if self._is_exact_zero() or other._is_exact_zero():
            pass
        elif self._power_two_sign() != 0:
            result @= other._shift_power(self.exponent - 1, self.hi < 0)
        elif other._power_two_sign() != 0:
            result @= self._shift_power(other.exponent - 1, other.hi < 0)
        else:
            result @= self._mul_general(other)
        return result

    def _is_exact_zero(self) -> bool:
        return self.hi == 0 and self.lo == 0 and self.error == 0

    def _unit_sign(self) -> int:
        result = 0
        if abs(self.hi) == 0.5 and self.lo == 0 and self.exponent == 1 and self.error == 0:
            result = 1
            if self.hi < 0:
                result = -1
        return result

    def _power_two_sign(self) -> int:
        result = 0
        if abs(self.hi) == 0.5 and self.lo == 0 and self.error == 0:
            result = 1
            if self.hi < 0:
                result = -1
        return result

    def _shift_power(self, amount: int, negative: bool) -> Self:
        result = +self
        if not self._is_exact_zero():
            result.exponent += amount
            assert abs(result.exponent) <= MAX_EXPONENT, "Timescale scaled exponent exceeds supported range"
            if negative:
                result.hi = -result.hi
                result.lo = -result.lo
        return result

    def _mul_general(self, other: AccurateScalar) -> AccurateScalar:
        pair = _two_product(self.hi, other.hi)
        cross_left = self.hi * other.lo
        cross_right = self.lo * other.hi
        cross_low = self.lo * other.lo
        tail = pair.lo + cross_left + cross_right
        tail += cross_low
        result = _two_sum(pair.hi, tail)
        x = abs(self.hi) + abs(self.lo)
        y = abs(other.hi) + abs(other.lo)
        radius = x * other.error + y * self.error + self.error * other.error
        if self.lo != 0 or other.lo != 0:
            # Stored heads have at most 24 significand bits, so their product
            # expansion is exact under binary32 or binary64 arithmetic. Bound
            # only the three cross products and the subsequent low-tail sums.
            radius += 8 * UNIT_ROUNDOFF * (abs(pair.lo) + abs(cross_left) + abs(cross_right) + abs(cross_low))
        return _normalize(result.hi, result.lo, self.exponent + other.exponent, _outward(radius))

    def div(self, other: AccurateScalar) -> Self:
        result = +type(self)
        if other._power_two_sign() != 0:
            result @= self._shift_power(1 - other.exponent, other.hi < 0)
        else:
            result @= self._div_general(other)
        return result

    def _div_general(self, other: AccurateScalar) -> AccurateScalar:
        denominator = abs(other.hi) - abs(other.lo) - other.error
        denominator -= 4 * UNIT_ROUNDOFF * (abs(other.hi) + abs(other.lo) + other.error)
        assert denominator > 0, "Timescale division has an uncertain or zero denominator"
        quotient = self.hi / other.hi
        # Ensure the initial quotient has a binary32 significand even on clients
        # evaluating in binary64. Its product with the stored denominator head
        # then has an exact two-component expansion in either arithmetic mode.
        grid = 2.0**24
        if abs(quotient) >= 1:
            grid = 2.0**23
        quotient = floor(quotient * grid) / grid
        product = _two_product(quotient, other.hi)
        head_difference = self.hi - product.hi
        cross_low = quotient * other.lo
        remainder = (head_difference - product.lo) + self.lo - cross_low
        correction = remainder / other.hi
        result = _two_sum(quotient, correction)
        magnitude = abs(result.hi) + abs(result.lo)
        radius = (self.error + magnitude * other.error) / denominator
        residual_error = 8 * UNIT_ROUNDOFF * (abs(head_difference) + abs(product.lo) + abs(self.lo) + abs(cross_low))
        radius += (residual_error + abs(correction) * abs(other.lo)) / denominator
        radius += 2 * UNIT_ROUNDOFF * abs(correction) * abs(other.hi) / denominator
        # Exact input quotients whose exact product equals the numerator have
        # zero residual, zero correction, and therefore zero arithmetic radius.
        return _normalize(result.hi, result.lo, self.exponent - other.exponent, _outward(radius))

    def scale(self, value: float) -> Self:
        return self.mul(AccurateScalar.of(value))

    def published(self) -> Self:
        return type(self)(self.hi, 0.0, self.exponent, _outward(self.error + abs(self.lo)))

    def published_add(self, other: AccurateScalar) -> Self:
        result = +type(self)
        if self.hi == 0 and self.lo == 0 and self.error == 0:
            result @= other.published()
        elif other.hi == 0 and other.lo == 0 and other.error == 0:
            result @= self.published()
        else:
            left = self.published()
            right = other.published()
            if left.exponent < right.exponent:
                temporary = +left
                left @= right
                right @= temporary
            gap = left.exponent - right.exponent
            factor = _power_two_small(-min(gap, ALIGNMENT_LIMIT))
            shifted = right.hi * factor
            if gap > ALIGNMENT_LIMIT:
                radius = left.error + (abs(right.hi) + right.error) * factor
                result @= _normalize(left.hi, 0.0, left.exponent, _outward(radius))
            else:
                center = left.hi + shifted
                radius = left.error + right.error * factor + 2 * UNIT_ROUNDOFF * (abs(left.hi) + abs(shifted))
                result @= _normalize(center, 0.0, left.exponent, _outward(radius))
        return result

    def published_mul(self, other: AccurateScalar) -> Self:
        result = +type(self)
        if self._is_exact_zero() or other._is_exact_zero():
            pass
        elif self._unit_sign() != 0:
            result @= other.published()
            if self.hi < 0:
                result @= result.neg()
        elif other._unit_sign() != 0:
            result @= self.published()
            if other.hi < 0:
                result @= result.neg()
        else:
            result @= self._published_mul_general(other)
        return result

    def _published_mul_general(self, other: AccurateScalar) -> AccurateScalar:
        left = self.published()
        right = other.published()
        center = left.hi * right.hi
        radius = abs(left.hi) * right.error + abs(right.hi) * left.error + left.error * right.error
        radius += 2 * UNIT_ROUNDOFF * abs(center)
        return _normalize(center, 0.0, left.exponent + right.exponent, _outward(radius))

    def published_div(self, other: AccurateScalar) -> Self:
        result = +type(self)
        if other._unit_sign() != 0:
            result @= self.published()
            if other.hi < 0:
                result @= result.neg()
        else:
            result @= self._published_div_general(other)
        return result

    def _published_div_general(self, other: AccurateScalar) -> AccurateScalar:
        left = self.published()
        right = other.published()
        denominator = abs(right.hi) - right.error
        denominator -= 4 * UNIT_ROUNDOFF * (abs(right.hi) + right.error)
        assert denominator > 0, "Timescale division has an uncertain or zero denominator"
        center = left.hi / right.hi
        radius = (left.error + abs(center) * right.error) / denominator
        radius += 2 * UNIT_ROUNDOFF * abs(center)
        return _normalize(center, 0.0, left.exponent - right.exponent, _outward(radius))

    def error_at_most(self, tolerance: float) -> bool:
        """Compare an absolute radius without subtracting scaled coordinates."""
        if tolerance < 0:
            return False
        if self.error == 0:
            return True
        if tolerance == 0:
            return False
        limit = AccurateScalar.of(tolerance)
        gap = self.exponent - limit.exponent
        radius = self.error
        while gap > 60:
            if radius > limit.hi:
                return False
            radius *= 2.0**60
            gap -= 60
        if gap < -60:
            return radius <= 1
        return radius * _power_two_small(gap) <= limit.hi

    def absolute_error(self) -> AccurateScalar:
        return _normalize(self.error, 0.0, self.exponent, 0.0)

    def lower_bound(self) -> AccurateScalar:
        center = self.hi + self.lo
        rounding = 4 * UNIT_ROUNDOFF * (abs(self.hi) + abs(self.lo) + self.error)
        return _normalize(center - (self.error + rounding), 0.0, self.exponent, 0.0)

    def upper_bound(self) -> AccurateScalar:
        center = self.hi + self.lo
        rounding = 4 * UNIT_ROUNDOFF * (abs(self.hi) + abs(self.lo) + self.error)
        return _normalize(center + (self.error + rounding), 0.0, self.exponent, 0.0)

    def definitely_less(self, other: AccurateScalar) -> bool:
        return self.sub(other).upper_bound().hi < 0

    def definitely_greater(self, other: AccurateScalar) -> bool:
        return other.definitely_less(self)

    def compare(self, other: AccurateScalar) -> int:
        """Compare represented centers; use definitely_* for certification."""
        difference = self.sub(other)
        center = difference.hi + difference.lo
        if center < 0:
            return -1
        if center > 0:
            return 1
        return 0

    def hull(self, other: AccurateScalar) -> Self:
        """Outward interval hull without materializing either operand's range."""
        result = +type(self)
        if (
            self.hi == other.hi
            and self.lo == other.lo
            and self.exponent == other.exponent
            and self.error == other.error
        ):
            result @= self
        else:
            left = +self
            right = +other
            if left.exponent < right.exponent:
                left @= other
                right @= self
            gap = left.exponent - right.exponent
            factor = _power_two_small(-min(gap, ALIGNMENT_LIMIT))
            left_center = left.hi + left.lo
            left_error = left.error + 4 * UNIT_ROUNDOFF * (abs(left.hi) + abs(left.lo) + left.error)
            right_center = (right.hi + right.lo) * factor
            right_error = (right.error + 4 * UNIT_ROUNDOFF * (abs(right.hi) + abs(right.lo) + right.error)) * factor
            if gap > ALIGNMENT_LIMIT:
                right_center = 0.0
                right_error = (abs(right.hi) + abs(right.lo) + right.error) * factor
            lower = min(left_center - left_error, right_center - right_error)
            upper = max(left_center + left_error, right_center + right_error)
            center = (lower + upper) * 0.5
            radius = (upper - lower) * 0.5 + 8 * UNIT_ROUNDOFF * (abs(lower) + abs(upper))
            result @= _normalize(center, 0.0, left.exponent, _outward(radius))
        return result

    def to_float(self) -> float:
        """Materialize a proved ordinary-range center; overflow is an error."""
        assert self.exponent <= 128, "Timescale distance must be classified before scalar conversion"
        if self.exponent < -149:
            return 0.0
        value = self.hi + self.lo
        exponent = self.exponent
        while exponent > 60:
            value *= 2.0**60
            exponent -= 60
        while exponent < -60:
            value *= 2.0**-60
            exponent += 60
        value *= _power_two_small(exponent)
        assert abs(value) <= 3.4028234663852886e38, "Timescale distance exceeds the scalar range"
        return value


def _normalize(hi: float, lo: float, exponent: int, radius: float) -> AccurateScalar:
    pair = _two_sum(hi, lo)
    hi = pair.hi
    lo = pair.lo
    magnitude = max(abs(hi), abs(lo), radius)
    if magnitude == 0:
        magnitude = 0.5
        exponent = 0
    # The error dominates only for uncertain signed cancellation; normalizing it
    # too keeps the radius finite even when the center is exactly zero.
    while magnitude >= 2.0**32:
        hi *= 2.0**-32
        lo *= 2.0**-32
        radius *= 2.0**-32
        magnitude *= 2.0**-32
        exponent += 32
    while magnitude < 2.0**-32:
        hi *= 2.0**32
        lo *= 2.0**32
        radius *= 2.0**32
        magnitude *= 2.0**32
        exponent -= 32
    # Select the remaining exponent in at most six branches, then scale all
    # components once. The common path avoids a per-bit normalization loop.
    shift = 0
    if magnitude >= 1:
        if magnitude >= 2.0**16:
            magnitude *= 2.0**-16
            shift += 16
        if magnitude >= 2.0**8:
            magnitude *= 2.0**-8
            shift += 8
        if magnitude >= 2.0**4:
            magnitude *= 2.0**-4
            shift += 4
        if magnitude >= 2.0**2:
            magnitude *= 2.0**-2
            shift += 2
        if magnitude >= 2:
            shift += 1
        shift += 1
    elif magnitude < 0.5:
        if magnitude < 2.0**-16:
            magnitude *= 2.0**16
            shift -= 16
        if magnitude < 2.0**-8:
            magnitude *= 2.0**8
            shift -= 8
        if magnitude < 2.0**-4:
            magnitude *= 2.0**4
            shift -= 4
        if magnitude < 2.0**-2:
            magnitude *= 2.0**2
            shift -= 2
        if magnitude < 0.5:
            shift -= 1
    if shift != 0:
        factor = _power_two_small(-shift)
        hi *= factor
        lo *= factor
        radius *= factor
        exponent += shift
    assert abs(exponent) <= MAX_EXPONENT, "Timescale exponent exceeds the validated numerical envelope"
    # Explicitly split the published head on a binary32 grid. This also protects
    # a client that evaluates expressions in binary64 but stores entity fields
    # in binary32: rounding the head at a store cannot silently lose the tail.
    stored_hi = floor(hi * 2.0**24) * 2.0**-24
    lo = (hi - stored_hi) + lo
    hi = stored_hi
    if lo != 0:
        radius = _outward(radius + 2 * UNIT_ROUNDOFF * abs(lo))
    return AccurateScalar(hi, lo, exponent, radius)


class AffineTransfer(Record):
    ratio: AccurateScalar
    distance: AccurateScalar

    @staticmethod
    def identity() -> AffineTransfer:
        return AffineTransfer(AccurateScalar.of(1.0), AccurateScalar.of(0.0))

    def then(self, following: Self) -> Self:
        return type(self)(
            self.ratio.mul(following.ratio),
            self.distance.add(self.ratio.mul(following.distance)),
        )

    def apply(self, value: AccurateScalar) -> AccurateScalar:
        return self.ratio.mul(value).add(self.distance)

    def published_apply(self, value: AccurateScalar) -> AccurateScalar:
        return self.ratio.published_mul(value).published_add(self.distance)


def published_progress(distance: AccurateScalar, preempt: float, offset: float = 0.0) -> AccurateScalar:
    """Fuse ordinary distance/preempt/progress arithmetic into one publication."""
    result = +AccurateScalar
    assert preempt > 0, "Timescale preempt must be positive"
    if -60 <= distance.exponent <= 60 and 2.0**-30 <= preempt <= 2.0**60 and abs(offset) <= 2.0**60:
        factor = _power_two_small(distance.exponent)
        center = (distance.hi + distance.lo) * factor
        radius = (distance.error + 2 * UNIT_ROUNDOFF * (abs(distance.hi) + abs(distance.lo))) * factor
        quotient = center / preempt
        before_offset = 1 - quotient
        progress = before_offset - offset
        radius = radius / preempt + 2 * UNIT_ROUNDOFF * abs(quotient)
        radius += 2 * UNIT_ROUNDOFF * (abs(before_offset) + abs(progress))
        result @= _normalize(progress, 0.0, 0, _outward(radius))
    else:
        quotient = distance.published_div(AccurateScalar.of(preempt))
        result @= AccurateScalar.of(1.0).published_add(quotient.neg()).published_add(AccurateScalar.of(-offset))
    return result


def native_constant_progress(
    hit: float, now: float, speed_value: float, preempt: float, offset: float
) -> NativeProgress:
    """Ordinary held/identity trajectory; caller proves the documented ranges.

    Requires |hit|, |now|, |speed| <= 2**30, preempt in [2**-30, 2**30],
    and |offset| <= 2**60. Inputs are quantized scalars, not uncertain caches.
    Three distance operations have relative error below 4u; the two final
    subtractions have separate absolute bounds. No scaled normalization occurs.
    """
    quotient = ((hit - now) * speed_value) / preempt
    before_offset = 1 - quotient
    value = before_offset - offset
    radius = 4 * UNIT_ROUNDOFF * abs(quotient)
    radius += 2 * UNIT_ROUNDOFF * (abs(before_offset) + abs(value))
    return NativeProgress(value, _outward(radius + ERROR_FLOOR))


def _aligned_native(value: AccurateScalar, exponent: int) -> _NativeExpansion:
    gap = exponent - value.exponent
    factor = _power_two_small(-min(gap, ALIGNMENT_LIMIT))
    result = +_NativeExpansion
    if gap > ALIGNMENT_LIMIT:
        result.error = _outward((abs(value.hi) + abs(value.lo) + value.error) * factor)
    else:
        result.hi = value.hi * factor
        result.lo = value.lo * factor
        result.error = value.error * factor
    return result


def native_difference_progress(
    target: AccurateScalar, current: AccurateScalar, preempt: float, offset: float = 0.0
) -> NativeProgress:
    """Render a bounded run-coordinate difference without scaled normalization.

    Caller requires both exponents in [-60,60], preempt in [2**-30,2**30],
    and |offset|<=2**60. Cancellation is resolved in aligned high/low coordinates
    before an ordinary scalar is produced. The error includes both input radii.
    """
    exponent = max(target.exponent, current.exponent)
    first = _aligned_native(target, exponent)
    second = _aligned_native(current, exponent)
    head = _two_sum(first.hi, -second.hi)
    tail = (first.lo - second.lo) + head.lo
    center = head.hi + tail
    radius = first.error + second.error
    radius += 4 * UNIT_ROUNDOFF * (abs(first.lo) + abs(second.lo) + abs(head.lo))
    factor = _power_two_small(exponent)
    quotient = (center * factor) / preempt
    before_offset = 1 - quotient
    value = before_offset - offset
    radius = (radius * factor) / preempt + 4 * UNIT_ROUNDOFF * abs(quotient)
    radius += 2 * UNIT_ROUNDOFF * (abs(before_offset) + abs(value))
    return NativeProgress(value, _outward(radius + ERROR_FLOOR))


def _ordinary_components(value: AccurateScalar) -> NativeProgress:
    factor = _power_two_small(value.exponent)
    center = (value.hi + value.lo) * factor
    radius = value.error * factor
    if value.lo != 0:
        radius += 2 * UNIT_ROUNDOFF * (abs(value.hi) + abs(value.lo)) * factor
    return NativeProgress(center, _outward(radius))


def native_affine_progress(
    value: AccurateScalar,
    ratio: AccurateScalar,
    distance: AccurateScalar,
    preempt: float,
    offset: float = 0.0,
    past: bool = False,
) -> NativeProgress:
    """Fuse a bounded cached affine coordinate and visual progress.

    Caller proves value/distance exponents in [-60,60], ratio exponent in
    [-10,10], preempt in [2**-30,2**30], and |offset|<=2**60. Future uses
    R*C+B; past uses -(C+B)/R. An uncertain denominator returns infinite
    error so the caller can refine through the existing accurate path.
    """
    cached = _ordinary_components(value)
    coefficient = _ordinary_components(ratio)
    intercept = _ordinary_components(distance)
    result = NativeProgress(0.0, inf)
    trajectory = 0.0
    radius = 0.0
    certain = True
    if past:
        denominator = abs(coefficient.value) - coefficient.error
        denominator -= 4 * UNIT_ROUNDOFF * (abs(coefficient.value) + coefficient.error)
        if denominator <= 0:
            certain = False
        else:
            numerator = cached.value + intercept.value
            numerator_error = cached.error + intercept.error
            numerator_error += 2 * UNIT_ROUNDOFF * (abs(cached.value) + abs(intercept.value))
            trajectory = -numerator / coefficient.value
            radius = (numerator_error + abs(trajectory) * coefficient.error) / denominator
            radius += 2 * UNIT_ROUNDOFF * abs(trajectory)
    else:
        product = coefficient.value * cached.value
        trajectory = product + intercept.value
        radius = abs(coefficient.value) * cached.error + abs(cached.value) * coefficient.error
        radius += coefficient.error * cached.error + intercept.error
        radius += 2 * UNIT_ROUNDOFF * (abs(product) + abs(trajectory))
    if certain:
        quotient = trajectory / preempt
        before_offset = 1 - quotient
        result.value = before_offset - offset
        radius = _outward(radius) / preempt + 2 * UNIT_ROUNDOFF * abs(quotient)
        radius += 2 * UNIT_ROUNDOFF * (abs(before_offset) + abs(result.value))
        result.error = _outward(radius + ERROR_FLOOR)
    return result


def polynomial_piece_integral(
    vleft: AccurateScalar, vright: AccurateScalar, curvature: AccurateScalar, width: AccurateScalar
) -> AccurateScalar:
    """Integrate a quadratic from endpoint speeds and its t**2 coefficient."""
    average = vleft.add(vright).scale(0.5)
    correction = curvature.mul(width).mul(width).div(AccurateScalar.of(6.0))
    return average.sub(correction).mul(width)


def midpoint_parts(a: float, b: float) -> _Pair:
    """Two stored components for a midpoint of practical quantized song times."""
    value = AccurateScalar.difference(a * 0.5, -b * 0.5)
    hi = value.hi
    lo = value.lo
    exponent = value.exponent
    while exponent > 60:
        hi *= 2.0**60
        lo *= 2.0**60
        exponent -= 60
    while exponent < -60:
        hi *= 2.0**-60
        lo *= 2.0**-60
        exponent += 60
    factor = _power_two_small(exponent)
    return _Pair(hi * factor, lo * factor)


def _complement_ease(ease: int) -> int:
    if ease == EaseType.IN_QUAD:
        return EaseType.OUT_QUAD
    if ease == EaseType.OUT_QUAD:
        return EaseType.IN_QUAD
    return ease


def _accurate_ease(ease: int, u: AccurateScalar) -> AccurateScalar:
    one = AccurateScalar.of(1.0)
    result = +AccurateScalar
    if ease == EaseType.LINEAR:
        result @= u
    elif ease == EaseType.IN_QUAD:
        result @= u.mul(u)
    elif ease == EaseType.OUT_QUAD:
        result @= u.mul(AccurateScalar.of(2.0).sub(u))
    elif ease == EaseType.IN_OUT_QUAD:
        if u.to_float() <= 0.5:
            result @= u.mul(u).scale(2.0)
        else:
            complement = one.sub(u)
            result @= one.sub(complement.mul(complement).scale(2.0))
    elif ease == EaseType.OUT_IN_QUAD:
        if u.to_float() <= 0.5:
            result @= u.mul(one.sub(u)).scale(2.0)
        else:
            offset = u.sub(AccurateScalar.of(0.5))
            result @= AccurateScalar.of(0.5).add(offset.mul(offset).scale(2.0))
    else:
        assert ease == EaseType.NONE, "Unknown timescale easing"
    return result


def _accurate_speed(v0: float, v1: float, ease: int, u: AccurateScalar) -> AccurateScalar:
    result = +AccurateScalar
    if ease == EaseType.NONE:
        result @= AccurateScalar.of(v0)
    else:
        base = v0
        top = v1
        coordinate = +u
        if v1 < v0:
            base = v1
            top = v0
            ease = _complement_ease(ease)
            coordinate @= AccurateScalar.of(1.0).sub(u)
        increment = AccurateScalar.of(top).sub(AccurateScalar.of(base))
        result @= AccurateScalar.of(base).add(increment.mul(_accurate_ease(ease, coordinate)))
    return result


def _accurate_integral_piece(
    v0: float,
    v1: float,
    ease: int,
    span: AccurateScalar,
    left: AccurateScalar,
    right: AccurateScalar,
    width: AccurateScalar,
) -> AccurateScalar:
    u0 = left.div(span)
    u1 = right.div(span)
    um = u0.add(width.div(span).scale(0.5))
    # A bounded loop keeps one compiled copy of the compensated speed evaluator.
    # The order remains v(left), 4*v(midpoint), v(right), as in Simpson's rule.
    samples = +AccurateScalar
    coordinate = +u0
    sample_index = 0
    while sample_index < 3:
        if sample_index == 1:
            coordinate @= um
        elif sample_index == 2:
            coordinate @= u1
        sample = _accurate_speed(v0, v1, ease, coordinate)
        if sample_index == 1:
            sample @= sample.scale(4.0)
        samples @= samples.add(sample)
        sample_index += 1
    return width.mul(samples).div(AccurateScalar.of(6.0))


def _accurate_integral(
    v0: float,
    v1: float,
    ease: int,
    span: AccurateScalar,
    left: AccurateScalar,
    right: AccurateScalar,
    width: AccurateScalar,
) -> AccurateScalar:
    result = +AccurateScalar
    if ease == EaseType.NONE:
        result @= width.scale(v0)
    else:
        midpoint = span.scale(0.5)
        piece_count = 1
        if ease >= EaseType.IN_OUT_QUAD and left.compare(midpoint) < 0 and right.compare(midpoint) > 0:
            piece_count = 2
        piece_left = +left
        piece_right = +right
        piece_width = +width
        piece_index = 0
        while piece_index < piece_count:
            if piece_count == 2:
                if piece_index == 0:
                    piece_right @= midpoint
                    piece_width @= midpoint.sub(left)
                else:
                    piece_left @= midpoint
                    piece_right @= right
                    piece_width @= right.sub(midpoint)
            piece = _accurate_integral_piece(v0, v1, ease, span, piece_left, piece_right, piece_width)
            result @= result.add(piece)
            piece_index += 1
    return result


def certified_speed_at(v0: float, v1: float, ease: int, a: float, b: float, t: float) -> AccurateScalar:
    """Evaluate at engine times without losing bits in normalized offsets."""
    result = +AccurateScalar
    if ease == EaseType.NONE or t <= a:
        result @= AccurateScalar.of(v0)
    elif t >= b:
        result @= AccurateScalar.of(v1)
    else:
        duration = AccurateScalar.of(b).sub(AccurateScalar.of(a))
        offset = AccurateScalar.of(t).sub(AccurateScalar.of(a))
        result @= _accurate_speed(v0, v1, ease, offset.div(duration))
    return result


def certified_integrate_times(
    v0: float, v1: float, ease: int, a: float, b: float, left: float, right: float
) -> AccurateScalar:
    """Integrate at quantized absolute times using accurate time differences."""
    result = +AccurateScalar
    if a != b and left != right:
        orientation = 1.0
        if left > right:
            left, right = right, left
            orientation = -1.0
        width = AccurateScalar.of(right).sub(AccurateScalar.of(left))
        if ease == EaseType.NONE:
            result @= width.scale(orientation * v0)
        else:
            start = AccurateScalar.of(a)
            span = AccurateScalar.of(b).sub(start)
            lo = AccurateScalar.of(left).sub(start)
            hi = AccurateScalar.of(right).sub(start)
            result @= _accurate_integral(v0, v1, ease, span, lo, hi, width).scale(orientation)
    return result


def clamped_fraction(
    a: AccurateScalar, b: AccurateScalar, x: AccurateScalar, fallback: float = 0.5, accurate: bool = False
) -> AccurateScalar:
    """Enclose both epsilon branches when uncertain endpoints can select either."""
    result = +AccurateScalar
    start = a.to_float()
    end = b.to_float()
    width = abs(end - start)
    ambiguous = False
    if a.error != 0 or b.error != 0:
        denominator = b.sub(a)
        width = abs(denominator.to_float())
        radius = denominator.absolute_error().to_float()
        radius += 2 * UNIT_ROUNDOFF * width
        radius = _outward(radius)
        ambiguous = width - radius < 1e-6 and width + radius >= 1e-6
    if ambiguous:
        result @= AccurateScalar(0.5, 0.0, 0, 0.5).hull(AccurateScalar.of(fallback))
    elif width < 1e-6:
        result @= AccurateScalar.of(fallback)
    else:
        ratio = +AccurateScalar
        if accurate:
            ratio @= x.sub(a).div(b.sub(a))
        else:
            # Close absolute song times need compensated subtraction even when
            # the subsequent ratio uses the inexpensive published arithmetic.
            ratio @= x.sub(a).published_div(b.sub(a))
        zero = AccurateScalar.of(0.0)
        one = AccurateScalar.of(1.0)
        if ratio.definitely_less(zero):
            result @= zero
        elif ratio.definitely_greater(one):
            result @= one
        elif ratio.compare(zero) >= 0 and ratio.compare(one) <= 0:
            # Clamping an interval around an in-range center cannot increase its
            # error. Keep its low component rather than scalarizing the fraction.
            result @= ratio
        elif ratio.error_at_most(1.0):
            center = 0.0
            if ratio.compare(one) > 0:
                center = 1.0
            radius = ratio.absolute_error().to_float()
            result @= _normalize(center, 0.0, 0, _outward(radius))
        else:
            result @= AccurateScalar(0.5, 0.0, 0, 0.5)
    return result


def native_scroll_progress(
    hit: float,
    now: float,
    certified_speed: AccurateScalar,
    preempt: float,
    offset: float = 0.0,
) -> NativeProgress:
    """Render D(t,h)=v(t)*(h-t) throughout one SCROLL run.

    The current speed's complete certificate is retained when its expansion is
    materialized. Endpoint marker crossings within the run need no query.
    Unsupported ordinary ranges return infinite error for accurate fallback.
    """
    result = NativeProgress(0.0, inf)
    if (
        abs(hit) <= 2.0**30
        and abs(now) <= 2.0**30
        and -30 <= certified_speed.exponent <= 30
        and 2.0**-30 <= preempt <= 2.0**30
        and abs(offset) <= 2.0**60
    ):
        current_speed = _ordinary_components(certified_speed)
        width = hit - now
        quotient = (width * current_speed.value) / preempt
        before_offset = 1 - quotient
        result.value = before_offset - offset
        radius = abs(width / preempt) * current_speed.error * (1 + 4 * UNIT_ROUNDOFF)
        radius += 4 * UNIT_ROUNDOFF * abs(quotient)
        radius += 2 * UNIT_ROUNDOFF * (abs(before_offset) + abs(result.value))
        result.error = _outward(radius + ERROR_FLOOR)
    return result
