"""Reproducible design probes; these do not exercise the Sonolus runtime.

Run: .venv/Scripts/python.exe docs/timescale_numeric_probes.py
"""

from decimal import Decimal, localcontext
from fractions import Fraction
from math import isclose, ulp
from struct import pack, unpack


def f32(value):
    return unpack("f", pack("f", value))[0]


def easing(kind, u):
    if kind == "linear":
        return u
    if kind == "in":
        return u * u
    if kind == "out":
        return 2 * u - u * u
    if kind == "inout":
        return 2 * u * u if u <= 0.5 else 1 - 2 * (1 - u) ** 2
    return 2 * u - 2 * u * u if u <= 0.5 else 0.5 + 2 * (u - 0.5) ** 2


def primitive(kind, u):
    if kind == "linear":
        return u * u / 2
    if kind == "in":
        return u**3 / 3
    if kind == "out":
        return u * u - u**3 / 3
    if kind == "inout":
        return 2 * u**3 / 3 if u <= 0.5 else u - 0.5 + 2 * (1 - u) ** 3 / 3
    return u * u - 2 * u**3 / 3 if u <= 0.5 else 1 / 6 + (u - 0.5) / 2 + 2 * (u - 0.5) ** 3 / 3


def main():
    # Simpson integrates the quadratic pieces exactly, up to roundoff. Choose
    # even subdivisions that include the midpoint join.
    worst_integral_error = 0.0
    for kind in ("linear", "in", "out", "inout", "outin"):
        for end in (0.25, 0.5, 0.75, 1.0):
            count = 600
            step = end / count
            values = [easing(kind, i * step) for i in range(count + 1)]
            integral = step / 3 * (values[0] + values[-1] + 4 * sum(values[1:-1:2]) + 2 * sum(values[2:-1:2]))
            worst_integral_error = max(worst_integral_error, abs(integral - primitive(kind, end)))
    assert worst_integral_error < 1e-12
    print(f"Quadratic primitive vs Simpson: max absolute error {worst_integral_error:.3g}")

    # Exact rational example: a visibility island with two crossings and an
    # endpoint-only test that misses both. Equality at the minimum is tangency.
    def distance(t):
        return (1 + (t - 1) ** 2) * (3 - t)

    minimum = distance(Fraction(4, 3))
    boundary = Fraction(19, 10)
    assert minimum == Fraction(50, 27)
    assert distance(0) > boundary
    assert distance(2) > boundary
    assert minimum < boundary
    print(f"Visibility island: endpoints {distance(0)}, {distance(2)}; interior minimum {minimum}")

    # Opposite-mix cycles keep authored speed between 1 and 2, but shrink T.
    # Each cycle has a one-second speed-2 hold followed by a speed-1 hold.
    prefix = f32(0)
    scale = f32(1)
    for _ in range(30):
        prefix = f32(prefix + scale)
        scale = f32(scale / 2)
        prefix = f32(prefix + scale)
    scroll = f32(1 / scale)
    collapsed_difference = f32(scroll * f32(f32(prefix + scale) - prefix))
    local_difference = f32(scroll * scale)
    assert collapsed_difference == 0
    assert local_difference == 1
    print(f"30 ordinary mixed cycles: collapsed-prefix distance={collapsed_difference}; local={local_difference}")

    # A single late-song ordinary-speed prefix already costs significant f32
    # distance precision when its high and low coordinates are collapsed.
    before = f32(1800 * 8)
    after = f32(before + 0.001 * 8)
    naive = f32(after - before)
    print(f"At 1800s, speed 8, 1ms interval: prefix delta={naive:.9g}; exact=0.008")
    clock_step = 2**-13
    assert f32(1800 + clock_step) - f32(1800) == clock_step
    print(
        f"Binary32 clock step at 1800s={clock_step:.12g}s; distance step at speed 8, lead .35={clock_step * 8 / 0.35:.6g}"
    )

    # Mixed linear ramp with m=.5: compare normalized-cell trapezoids to an
    # analytic Decimal reference, avoiding a numerical quadrature oracle.
    with localcontext() as ctx:
        ctx.prec = 60
        v0, v1 = Decimal("0.2"), Decimal(1)
        exact = Decimal(2) / 3 * (v1 * v1.sqrt() - v0 * v0.sqrt()) / (v1 - v0)
        count = 4096
        total32 = f32(0)
        ratio32 = f32(1)
        total64 = 0.0
        ratio64 = 1.0
        # Compose from the right so no full-chart prefix is ever formed.
        for i in reversed(range(count)):
            left = 0.2 + 0.8 * i / count
            right = 0.2 + 0.8 * (i + 1) / count
            f_end = (right / left) ** 0.5
            r = left * f_end / right
            b = left / count * (1 + f_end) / 2
            total64 = b + r * total64
            ratio64 = r * ratio64
            total32 = f32(f32(b) + f32(f32(r) * total32))
            ratio32 = f32(f32(r) * ratio32)
        expected = float(v0.sqrt() * exact)
        error64 = abs(total64 - expected) / expected
        error32 = abs(total32 - expected) / expected
        assert error64 < 1e-7
        assert error32 < 1e-4
        assert isclose(ratio64, float(v0.sqrt()), rel_tol=1e-12)
        print(
            f"Mixed local transfer vs 60-digit analytic integral: relative error f64={error64:.3g}, f32={error32:.3g}"
        )
        print(f"4096 sequential f32 transfer ratios: relative error={abs(ratio32 / float(v0.sqrt()) - 1):.3g}")
    print(f"Python binary64 clock spacing at 1800s={ulp(1800.0):.3g}s (not a device guarantee)")


if __name__ == "__main__":
    main()
