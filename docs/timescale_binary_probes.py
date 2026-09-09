"""Positive binary-mode transfer experiments, independent of the Sonolus runtime.

Run: .venv/Scripts/python.exe docs/timescale_binary_probes.py

Each transition lasts one second and chooses pure timescale or pure scroll.
Scaled mantissas and elementary arithmetic are rounded to binary32; exponents
are exact integers. Decimal references use identical quantized inputs where
specified. This demonstrates range and measures rounding, not certified bounds.
The implementation and operation counts are a Python reference, not engine cost.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from math import frexp, ldexp, log2
from struct import pack, unpack

OPERATIONS = Counter()


def f32(value):
    return unpack("f", pack("f", value))[0]


@dataclass(frozen=True)
class Scaled:
    mantissa: float
    exponent: int

    @classmethod
    def of(cls, value):
        mantissa, exponent = frexp(f32(value))
        return cls(mantissa, exponent)

    def multiply(self, other):
        OPERATIONS["scaled_multiply"] += 1
        mantissa, exponent = frexp(f32(self.mantissa * other.mantissa))
        return Scaled(mantissa, self.exponent + other.exponent + exponent)

    def add(self, other):
        OPERATIONS["scaled_add"] += 1
        if self.mantissa == 0:
            return other
        if other.mantissa == 0:
            return self
        larger, smaller = (self, other) if self.exponent >= other.exponent else (other, self)
        gap = smaller.exponent - larger.exponent
        # A term this small cannot affect nearest binary32 rounding of a
        # positive normalized mantissa. Certification would still track it.
        shifted = 0.0 if gap < -64 else f32(ldexp(smaller.mantissa, gap))
        mantissa, exponent = frexp(f32(larger.mantissa + shifted))
        return Scaled(mantissa, larger.exponent + exponent)

    def decimal(self):
        return Decimal.from_float(self.mantissa) * Decimal(2) ** self.exponent


@dataclass(frozen=True)
class Transfer:
    ratio: Scaled
    distance: Scaled

    @classmethod
    def of(cls, ratio, distance):
        return cls(Scaled.of(ratio), Scaled.of(distance))

    def then(self, other):
        return Transfer(self.ratio.multiply(other.ratio), self.distance.add(self.ratio.multiply(other.distance)))


IDENTITY = Transfer.of(1, 0)


class RangeTree:
    def __init__(self, values):
        capacity = 1
        while capacity < len(values):
            capacity *= 2
        self.capacity = capacity
        self.nodes = [IDENTITY] * (2 * capacity)
        self.nodes[capacity : capacity + len(values)] = values
        for i in range(capacity - 1, 0, -1):
            self.nodes[i] = self.nodes[2 * i].then(self.nodes[2 * i + 1])

    def query(self, start, end):
        left, right = IDENTITY, IDENTITY
        start += self.capacity
        end += self.capacity
        while start < end:
            if start % 2:
                left = left.then(self.nodes[start])
                start += 1
            if end % 2:
                end -= 1
                right = self.nodes[end].then(right)
            start //= 2
            end //= 2
        return left.then(right)


def sequential(values):
    result = IDENTITY
    for value in reversed(values):
        result = value.then(result)
    return result


def relative_error(value, expected):
    return float(abs(value.decimal() / expected - 1))


def pure_transition(v0, v1, mode, average_ease=0.5):
    """Full one-second transfer; endpoint/linear speed average is exact here."""
    v0, v1 = f32(v0), f32(v1)
    if mode == "scroll":
        return Transfer.of(f32(v0 / v1), v0)
    integral = f32(f32(v0 * f32(1 - average_ease)) + f32(v1 * f32(average_ease)))
    return Transfer.of(1, integral)


def power_of_two_cycles():
    print("Power-of-two alternating modes, one-second linear ramps plus one-second speed-1 hold")
    for shrinking_timescale in (False, True):
        if shrinking_timescale:
            pattern = [pure_transition(1, 2, "scroll"), pure_transition(2, 1, "timescale")]
            direction = "shrinking T, growing S"
        else:
            pattern = [pure_transition(1, 2, "timescale"), pure_transition(2, 1, "scroll")]
            direction = "growing T, shrinking S"
        print(direction)
        for cycles in (24, 128, 129, 1000, 10000):
            leaves = pattern * cycles + [Transfer.of(1, 1)]
            OPERATIONS.clear()
            tree = RangeTree(leaves)
            build_counts = dict(OPERATIONS)
            full = tree.query(0, 2 * cycles)
            exponent = -cycles if shrinking_timescale else cycles
            exact_ratio = Decimal(2) ** exponent
            exact_distance = Decimal("3.5") * (1 - exact_ratio if shrinking_timescale else exact_ratio - 1)
            full_error = relative_error(full.distance, exact_distance)
            ratio_error = relative_error(full.ratio, exact_ratio)
            # Query only the local hold; no whole-chart prefixes are subtracted.
            OPERATIONS.clear()
            local = tree.query(2 * cycles, 2 * cycles + 1)
            local_counts = dict(OPERATIONS)
            assert local.distance.decimal() == 1
            assert local.ratio.decimal() == 1
            # A nontrivial local suffix also ignores all earlier history.
            suffix = tree.query(2 * cycles - 2, 2 * cycles + 1)
            expected_suffix = Decimal("2.25") if shrinking_timescale else Decimal("5.5")
            assert suffix.distance.decimal() == expected_suffix
            assert full.ratio.mantissa == 0.5
            assert full.ratio.exponent == exponent + 1
            assert ratio_error < 1e-75
            assert full_error < 1e-6
            print(
                f"  n={cycles}: aggregate R=(m={full.ratio.mantissa:g}, e={full.ratio.exponent}); "
                f"B relative error={full_error:.6g}; local hold=1; last cycle+hold={expected_suffix}"
            )
            if cycles == 10000:
                print(f"  abstract build counts={build_counts}; one-leaf range query={local_counts}")


def reciprocal_drift():
    print("\nReciprocal-ratio drift: speed endpoints use the SAME binary32-rounded 7.8")
    high = f32(7.8)
    high_decimal = Decimal.from_float(high)
    # R over four transitions is exactly 1. Timescale integrations are the
    # identical linear average in both directions. Exact cycle B = 3 + 1/high.
    pattern = [
        pure_transition(1, high, "scroll"),
        pure_transition(high, 1, "timescale"),
        pure_transition(1, high, "timescale"),
        pure_transition(high, 1, "scroll"),
    ]
    rounded_ratio = f32(f32(1 / high) * high)
    print(f"quantized high speed={high:.12g}; rounded reciprocal product={rounded_ratio:.12g}; exact=1")
    for cycles in (128, 1000, 10000):
        leaves = pattern * cycles
        tree = RangeTree(leaves)
        balanced = tree.query(0, len(leaves))
        linear = sequential(leaves)
        expected = (3 + 1 / high_decimal) * cycles
        print(
            f"  n={cycles}: tree R error={relative_error(balanced.ratio, Decimal(1)):.6g}, "
            f"B error={relative_error(balanced.distance, expected):.6g}; "
            f"sequential R error={relative_error(linear.ratio, Decimal(1)):.6g}, "
            f"B error={relative_error(linear.distance, expected):.6g}"
        )
        if cycles == 10000:
            # Adjacent pure-scroll intervals can instead telescope their
            # ratios through shared endpoints. This is exact in real arithmetic.
            same_mode = [pure_transition(1, high, "scroll"), pure_transition(high, 1, "scroll")]
            raw = RangeTree(same_mode * cycles).query(0, 2 * cycles)
            coalesced = Transfer.of(1, 2 * cycles)
            print(
                f"  adjacent scroll-only cycles: raw R error={relative_error(raw.ratio, Decimal(1)):.6g}; "
                f"coalesced R=1, B={coalesced.distance.decimal():g} exactly"
            )
            # At a late local query the history itself does not accumulate error.
            local = tree.query(len(leaves) - 4, len(leaves))
            print(
                f"  last four transitions alone: R error={relative_error(local.ratio, Decimal(1)):.6g}; "
                f"B error={relative_error(local.distance, expected / cycles):.6g}"
            )


def collapsed_prefix():
    print("\nCollapsed raw prefix after 30 shrinking-timescale cycles")
    timescale, prefix = f32(1), f32(0)
    for _ in range(30):
        # Scroll 1->2 leaves T constant; timescale 2->1 then halves T.
        prefix = f32(prefix + timescale)
        prefix = f32(prefix + f32(0.75 * timescale))
        timescale = f32(timescale / 2)
    collapsed = f32(f32(1 / timescale) * f32(f32(prefix + timescale) - prefix))
    assert collapsed == 0
    print(
        f"raw prefix={prefix:g}, next one-second hold T={timescale:.6g}; "
        f"prefix-subtracted displayed distance={collapsed:g}, local transfer distance=1"
    )


def decimal_compose(left, right):
    r1, b1 = left
    r2, b2 = right
    return r1 * r2, b1 + r1 * b2


def decimal_query(nodes, capacity, start, end):
    left = right = (Decimal(1), Decimal(0))
    start += capacity
    end += capacity
    while start < end:
        if start % 2:
            left = decimal_compose(left, nodes[start])
            start += 1
        if end % 2:
            end -= 1
            right = decimal_compose(nodes[end], right)
        start //= 2
        end //= 2
    return decimal_compose(left, right)


def block_reset_and_accurate_preprocessing():
    print("\n20,000 transitions: reset 32-event blocks, then compare accurate subtree preprocessing")
    cycles, block_size = 5000, 32
    high = f32(7.8)
    exact_high = Decimal.from_float(high)
    pattern = [
        pure_transition(1, high, "scroll"),
        pure_transition(high, 1, "timescale"),
        pure_transition(1, high, "timescale"),
        pure_transition(high, 1, "scroll"),
    ]
    leaves = pattern * cycles
    full_tree = RangeTree(leaves)
    full = full_tree.query(0, len(leaves))
    # Every block begins in its own local coordinate unit. These are the same
    # affine units used at every leaf; resetting them adds no mantissa precision.
    blocks = [RangeTree(leaves[i : i + block_size]).query(0, block_size) for i in range(0, len(leaves), block_size)]
    block_result = RangeTree(blocks).query(0, len(blocks))
    assert block_result == full
    expected = cycles * (3 + 1 / exact_high)
    print(
        f"  full tree and {len(blocks)} locally reset blocks are bit-identical: "
        f"R error={relative_error(full.ratio, Decimal(1)):.9g}; "
        f"B error={relative_error(full.distance, expected):.9g}"
    )

    # Stronger assumption: 80-digit arithmetic calculates every subtree from
    # unrounded semantic leaf formulas. Every cached subtree is then rounded
    # once to binary32. Building parents from rounded cached children would
    # reproduce the original error and is deliberately NOT done here.
    exact_pattern = [
        (1 / exact_high, Decimal(1)),
        (Decimal(1), (exact_high + 1) / 2),
        (Decimal(1), (exact_high + 1) / 2),
        (exact_high, exact_high),
    ]
    capacity = full_tree.capacity
    exact_nodes = [(Decimal(1), Decimal(0))] * (2 * capacity)
    exact_nodes[capacity : capacity + len(leaves)] = exact_pattern * cycles
    for i in range(capacity - 1, 0, -1):
        exact_nodes[i] = decimal_compose(exact_nodes[2 * i], exact_nodes[2 * i + 1])
    # Reuse the range-query implementation. All values in this particular
    # example fit binary64 before binary32 storage; no large Decimal is cast.
    accurate_tree = RangeTree([])
    accurate_tree.capacity = capacity
    accurate_tree.nodes = [Transfer.of(float(r), float(b)) for r, b in exact_nodes]
    for start, end in ((0, len(leaves)), (1, len(leaves) - 1), (13, len(leaves) - 17)):
        exact_r, exact_b = decimal_query(exact_nodes, capacity, start, end)
        if start == 0 and end == len(leaves):
            # Use the algebraic full-cycle identity instead of reporting
            # the Decimal oracle's approximately 1e-76 accumulation residue.
            exact_r, exact_b = Decimal(1), expected
        OPERATIONS.clear()
        computed = accurate_tree.query(start, end)
        counts = dict(OPERATIONS)
        error_r = relative_error(computed.ratio, exact_r)
        error_b = relative_error(computed.distance, exact_b)
        assert max(error_r, error_b) < 1e-6
        print(
            f"  accurately precomputed subtree query [{start},{end}): "
            f"R error={error_r:.9g}; B error={error_b:.9g}; operations={counts}"
        )
    print(
        f"  preprocessing assumption: {capacity - 1} high-precision affine compositions; "
        "two multiplications and one addition each, plus accurate leaf divisions; "
        "runtime queries use only stored binary32 mantissas and integer exponents"
    )


def rounded_endpoint_logs():
    print("\nRounded endpoint logs, even with exact summation (20,000 transitions)")
    a, b, c, d = (1.125, 1.375, 4.8125, 3.9375)
    assert Fraction(a) * Fraction(c) == Fraction(b) * Fraction(d)

    def quantized_log(speed):
        mantissa, exponent = frexp(speed)
        # Giving the integer exponent its own exact component avoids another
        # rounding step and makes this a stronger test of the suggested fix.
        return Decimal(exponent) + Decimal.from_float(f32(log2(mantissa)))

    residual = quantized_log(a) - quantized_log(b) + quantized_log(c) - quantized_log(d)
    assert residual == Decimal("-8.1956386566162109375e-8")
    cycles = 5000
    # S,T,S,T gives R=(a/b)*(c/d)=1 exactly. Summation and exponentiation
    # below use 80-digit arithmetic: only endpoint logs have been rounded.
    ratio = Decimal(2) ** (cycles * residual)
    error = ratio - 1
    print(f"  speeds={a},{b},{c},{d}, modes=S,T,S,T; exact a*c=b*d and net R=1")
    print(f"  per-cycle stored-log residual={residual}; n={cycles}, signed R error={error:.12g}")
    assert abs(error) > Decimal("0.00028")


def stable_speed(v0, v1, kind, u, rounding=float):
    """Monotone quadratic speeds as sums/products of nonnegative quantities."""
    u = rounding(u)
    remaining = rounding(1 - u)
    if kind == "linear":
        weight = u if v1 >= v0 else remaining
    elif kind == "in":
        weight = rounding(u * u) if v1 >= v0 else rounding(remaining * rounding(1 + u))
    else:
        weight = rounding(u * rounding(2 - u)) if v1 >= v0 else rounding(remaining * remaining)
    return rounding(rounding(min(v0, v1)) + rounding(rounding(abs(v1 - v0)) * weight))


def exact_primitive(v0, v1, kind, u):
    if kind == "linear":
        ease_integral = u**2 / 2
    elif kind == "in":
        ease_integral = u**3 / 3
    else:
        ease_integral = u**2 - u**3 / 3
    return v0 * u + (v1 - v0) * ease_integral


def pure_quadratic_probes():
    print("\nPure quadratic local transfers: analytic polynomial integral, no adaptive quadrature")
    worst_time, worst_scroll, worst_ratio = 0.0, 0.0, 0.0
    for v0, v1 in ((Fraction(1, 20), Fraction(8)), (Fraction(8), Fraction(1, 20))):
        for kind in ("linear", "in", "out"):
            for a, b in (
                (Fraction(0), Fraction(1)),
                (Fraction(31, 32), Fraction(1)),
                (Fraction(4095, 4096), Fraction(1)),
                (Fraction(1, 4), Fraction(3, 4)),
            ):
                midpoint = (a + b) / 2
                va = stable_speed(float(v0), float(v1), kind, float(a), f32)
                vm = stable_speed(float(v0), float(v1), kind, float(midpoint), f32)
                vb = stable_speed(float(v0), float(v1), kind, float(b), f32)
                # This positive weighted identity integrates each quadratic
                # piece exactly in real arithmetic. Split inout/outin at joins.
                average = f32(f32(f32(va + vb) + f32(4 * vm)) / 6)
                integral = f32(f32(float(b - a)) * average)
                reference = exact_primitive(v0, v1, kind, b) - exact_primitive(v0, v1, kind, a)
                worst_time = max(worst_time, abs(integral / float(reference) - 1))
                scroll_b = f32(va * f32(float(b - a)))
                exact_va = stable_speed(v0, v1, kind, a, Fraction)
                exact_vb = stable_speed(v0, v1, kind, b, Fraction)
                worst_scroll = max(worst_scroll, abs(scroll_b / float(exact_va * (b - a)) - 1))
                ratio = f32(va / vb)
                worst_ratio = max(worst_ratio, abs(ratio / float(exact_va / exact_vb) - 1))
    print(
        f"max relative errors: timescale integral={worst_time:.6g}; "
        f"scroll local B={worst_scroll:.6g}; scroll R={worst_ratio:.6g}"
    )
    assert max(worst_time, worst_scroll, worst_ratio) < 1e-6


def main():
    with localcontext() as context:
        context.prec = 80
        power_of_two_cycles()
        reciprocal_drift()
        collapsed_prefix()
        block_reset_and_accurate_preprocessing()
        rounded_endpoint_logs()
        pure_quadratic_probes()


if __name__ == "__main__":
    main()
