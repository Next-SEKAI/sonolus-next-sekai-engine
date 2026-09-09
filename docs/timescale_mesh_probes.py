"""Standalone design experiment; Python results are not a Sonolus client guarantee.

Run: .venv/Scripts/python.exe docs/timescale_mesh_probes.py

All transitions last one normalized second. Mesh bounds are scale invariant in
duration. Input speeds are positive; all easing pieces are monotone quadratics.
Bounds below are analytic in real arithmetic, evaluated here with binary64 (not
outward-rounded interval arithmetic). Sampled errors complement those bounds;
they are not certifications. Binary32 operations are individually rounded and
pow is assumed correctly rounded. No production implementation is exercised.
"""

from dataclasses import dataclass
from itertools import pairwise
from math import sqrt
from statistics import median
from struct import pack, unpack


def f32(value):
    return unpack("f", pack("f", value))[0]


def horner(coefficients, x, rounding=float):
    value = rounding(coefficients[-1])
    for coefficient in reversed(coefficients[:-1]):
        value = rounding(rounding(value * x) + rounding(coefficient))
    return value


@dataclass(frozen=True)
class Piece:
    a: float
    b: float
    c: float
    d: float
    e: float

    def value(self, t):
        x = t - self.a
        return self.c + x * (self.d + x * self.e)

    def derivative(self, t):
        return self.d + 2 * self.e * (t - self.a)


def pieces(v0, v1, kind):
    delta = v1 - v0
    if kind == "linear":
        return [Piece(0, 1, v0, delta, 0)]
    if kind == "in":
        return [Piece(0, 1, v0, 0, delta)]
    if kind == "out":
        return [Piece(0, 1, v0, 2 * delta, -delta)]
    middle = (v0 + v1) / 2
    if kind == "inout":
        return [Piece(0, 0.5, v0, 0, 2 * delta), Piece(0.5, 1, middle, 2 * delta, -2 * delta)]
    return [Piece(0, 0.5, v0, 2 * delta, -2 * delta), Piece(0.5, 1, middle, 0, 2 * delta)]


def relative_bound(piece, a, b, q, degree):
    """Lagrange/Hermite remainder divided by minimum exact positive share."""
    low = min(piece.value(a), piece.value(b))
    width = b - a
    second = 2 * piece.e
    deriv = max(abs(piece.derivative(a)), abs(piece.derivative(b)))
    if degree == 1:
        # N = v*v'' + (q-1)*v'^2, N' = (2*q-1)*v'*v''.
        # v' has constant sign on each supported piece, hence endpoints bound N.
        numerator = max(abs(piece.value(t) * second + (q - 1) * piece.derivative(t) ** 2) for t in (a, b))
        return q * numerator / low**2 * width**2 / 8
    if degree == 2:
        third = q * (1 - q) * ((2 - q) * deriv**3 / low**3 + 3 * deriv * abs(second) / low**2)
        # max |x*(x-1/2)*(x-1)| / 3! = 1/(72*sqrt(3)).
        return third * width**3 / (72 * sqrt(3))
    fourth = (
        q
        * (1 - q)
        * (
            (2 - q) * (3 - q) * deriv**4 / low**4
            + 6 * (2 - q) * deriv**2 * abs(second) / low**3
            + 3 * second**2 / low**2
        )
    )
    return fourth * width**4 / 384


def mesh(v0, v1, kind, mix, epsilon, degree=1, *, quadrature=False):
    cells = []
    for piece in pieces(v0, v1, kind):
        pending = [(piece.a, piece.b)]
        while pending:
            a, b = pending.pop()
            error = relative_bound(piece, a, b, 1 - mix, degree)
            if quadrature:
                assert degree == 3
                # Integral Hermite remainder M4*h^5/720 divided by
                # h*min(f), versus pointwise remainder M4*h^4/384.
                error *= 384 / 720
            if error <= epsilon:
                cells.append((piece, a, b))
            else:
                middle = (a + b) / 2
                pending.extend(((middle, b), (a, middle)))
    return cells


def share_coefficients(piece, a, b, q, degree):
    width = b - a
    va, vb = piece.value(a), piece.value(b)
    end = (vb / va) ** q
    if degree == 1:
        return (1.0, end - 1)
    if degree == 2:
        middle = (piece.value((a + b) / 2) / va) ** q
        return (1.0, 4 * middle - end - 3, 2 * end + 2 - 4 * middle)
    left_deriv = width * q * piece.derivative(a) / va
    right_deriv = width * q * end * piece.derivative(b) / vb
    return (1.0, left_deriv, 3 * (end - 1) - 2 * left_deriv - right_deriv, 2 * (1 - end) + left_deriv + right_deriv)


def transfer(cell, q, degree):
    piece, a, b = cell
    coefficients = share_coefficients(piece, a, b, q, degree)
    va, vb = piece.value(a), piece.value(b)
    end = (vb / va) ** q
    return va * end / vb, va * (b - a) * sum(c / (i + 1) for i, c in enumerate(coefficients))


def compose(left, right, rounding=float):
    r1, b1 = left
    r2, b2 = right
    return rounding(r1 * r2), rounding(b1 + rounding(r1 * b2))


def accumulate(transfers, rounding=float, balanced=False):
    values = [(rounding(r), rounding(b)) for r, b in transfers]
    if balanced:
        while len(values) > 1:
            values = [
                compose(values[i], values[i + 1], rounding) if i + 1 < len(values) else values[i]
                for i in range(0, len(values), 2)
            ]
        return values[0]
    value = (1.0, 0.0)
    for transfer_value in reversed(values):
        value = compose(transfer_value, value, rounding)
    return value


def simpson(function, a, b, tolerance=1e-12, depth=30):
    """Adaptive binary64 Simpson oracle, checked against analytic linear cases."""
    middle = (a + b) / 2
    fa, fm, fb = function(a), function(middle), function(b)
    initial = (b - a) * (fa + 4 * fm + fb) / 6

    def refine(a, b, fa, fm, fb, previous, tolerance, remaining):
        middle = (a + b) / 2
        fl, fr = function((a + middle) / 2), function((middle + b) / 2)
        left = (middle - a) * (fa + 4 * fl + fm) / 6
        right = (b - middle) * (fm + 4 * fr + fb) / 6
        error = left + right - previous
        if abs(error) <= 15 * tolerance:
            return left + right + error / 15
        assert remaining > 0
        return refine(a, middle, fa, fl, fm, left, tolerance / 2, remaining - 1) + refine(
            middle, b, fm, fr, fb, right, tolerance / 2, remaining - 1
        )

    return refine(a, b, fa, fm, fb, initial, tolerance, depth)


def probe(cells, v0, v1, q, degree):
    share_error = 0.0
    coefficient_error = 0.0
    endpoint_error = 0.0
    line_speed_error = 0.0
    derivative_jump = 0.0
    previous_log_deriv = None
    for piece, a, b in cells:
        coefficients = share_coefficients(piece, a, b, q, degree)
        va = piece.value(a)
        width = b - a
        speed_coefficients = (va, piece.derivative(a) * width, piece.e * width**2)
        for i in range(17):
            x = i / 16
            exact = (piece.value(a + width * x) / va) ** q
            estimated = horner(coefficients, x)
            rounded = horner(coefficients, f32(x), f32)
            share_error = max(share_error, abs(estimated / exact - 1))
            coefficient_error = max(coefficient_error, abs(rounded / exact - 1))
            speed = horner(speed_coefficients, f32(x), f32)
            # Include S=v/f then S*f rounding, the proposed product evaluation.
            product = f32(f32(speed / rounded) * rounded)
            line_speed_error = max(line_speed_error, abs(product / piece.value(a + width * x) - 1))
        endpoint_error = max(endpoint_error, abs(horner(coefficients, 1, f32) / horner(coefficients, 1) - 1))
        left_log_deriv = coefficients[1] / width
        if previous_log_deriv is not None:
            derivative_jump = max(derivative_jump, abs(left_log_deriv - previous_log_deriv))
        previous_log_deriv = sum(i * c for i, c in enumerate(coefficients)) / width / sum(coefficients)
    transfers = [transfer(cell, q, degree) for cell in cells]
    r64, b64 = accumulate(transfers)
    r32, b32 = accumulate(transfers, f32)
    rt32, bt32 = accumulate(transfers, f32, balanced=True)
    unique_pieces = list(dict.fromkeys(cell[0] for cell in cells))
    reference = v0 ** (1 - q) * sum(
        simpson(lambda t, piece=piece: piece.value(t) ** q, piece.a, piece.b) for piece in unique_pieces
    )
    exact_ratio = (v0 / v1) ** (1 - q)
    assert abs(r64 / exact_ratio - 1) < 1e-10
    return {
        "share64": share_error,
        "share32": coefficient_error,
        "endpoint32": endpoint_error,
        "line32": line_speed_error,
        "jump": derivative_jump,
        "distance64": abs(b64 / reference - 1),
        "distance32": abs(b32 / reference - 1),
        "distance_tree32": abs(bt32 / reference - 1),
        "ratio32": abs(r32 / exact_ratio - 1),
        "ratio_tree32": abs(rt32 / exact_ratio - 1),
    }


def probe_computed32_transfers(cells, v0, v1, q):
    """Linear transfers constructed with rounded endpoints, pow and arithmetic."""
    stored = [transfer(cell, q, 1) for cell in cells]
    computed = []
    for piece, a, b in cells:
        va, vb = f32(piece.value(a)), f32(piece.value(b))
        end = f32(f32(vb / va) ** f32(q))
        ratio = f32(f32(va * end) / vb)
        integral = f32(f32(va * f32(b - a)) * f32(f32(1 + end) / 2))
        computed.append((ratio, integral))
    _, b64 = accumulate(stored)
    exact_ratio = (v0 / v1) ** (1 - q)
    for balanced in (False, True):
        r32, b32 = accumulate(computed, f32, balanced=balanced)
        print(
            f"  constructed32 balanced={balanced}: ratio relative error={abs(r32 / exact_ratio - 1):.6g}; "
            f"distance relative error vs unrounded mesh={abs(b32 / b64 - 1):.6g}"
        )
    print(f"  direct constant-mix event ratio stored32 relative error={abs(f32(exact_ratio) / exact_ratio - 1):.6g}")


def main():
    epsilon = 1e-6
    kinds = ("linear", "in", "out", "inout", "outin")
    mixes = (0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99)
    ratios = (1.001, 1.1, 2, 4, 10, 40, 160)
    worst_cases = {}
    print("Analytic real-arithmetic bounds, dyadic adaptive subdivision; epsilon=1e-6")
    print("Grid: 7 ratios * both directions * 5 easings * 7 interior mixes = 490 ramps")
    for degree in (1, 2, 3):
        counts = []
        by_ratio = {}
        worst = (0, None)
        for ratio in ratios:
            ratio_counts = []
            for v0, v1 in ((0.05, 0.05 * ratio), (0.05 * ratio, 0.05)):
                for kind in kinds:
                    for mix in mixes:
                        count = len(mesh(v0, v1, kind, mix, epsilon, degree))
                        counts.append(count)
                        ratio_counts.append(count)
                        if count > worst[0]:
                            worst = (count, (v0, v1, kind, mix))
            by_ratio[ratio] = max(ratio_counts)
        worst_cases[degree] = worst[1]
        print(f"degree={degree}: median={median(counts):g}, max={worst[0]}, case={worst[1]}")
        print(f"  maxima by speed ratio: {by_ratio}")

    print("\nDetailed sampled/evaluation errors, 17 samples per cell; duration=1 second")
    for degree, case in worst_cases.items():
        v0, v1, kind, mix = case
        cells = mesh(v0, v1, kind, mix, epsilon, degree)
        result = probe(cells, v0, v1, 1 - mix, degree)
        print(f"degree={degree}, cells={len(cells)}, case={case}")
        print("  " + ", ".join(f"{key}={value:.6g}" for key, value in result.items()))
        assert result["share64"] <= epsilon * 1.001
        assert result["distance64"] <= 2 * epsilon / (1 - epsilon)

    print("\nTransfer construction arithmetic at the worst linear cell-count case")
    v0, v1, kind, mix = worst_cases[1]
    probe_computed32_transfers(mesh(v0, v1, kind, mix, epsilon), v0, v1, 1 - mix)

    print("\nExact-share alternative: Hermite quadrature, analytic integral remainder bound")
    for tolerance in (1e-5, 1e-6):
        worst = (0, None)
        for v0, v1 in ((0.05, 8), (8, 0.05)):
            for kind in kinds:
                for mix in mixes:
                    cells = mesh(v0, v1, kind, mix, tolerance, 3, quadrature=True)
                    if len(cells) > worst[0]:
                        worst = (len(cells), (v0, v1, kind, mix))
        v0, v1, kind, mix = worst[1]
        cells = mesh(v0, v1, kind, mix, tolerance, 3, quadrature=True)
        result = probe(cells, v0, v1, 1 - mix, 3)
        # For a query at an event start, the integral coincides with integrating
        # the Hermite share. At arbitrary t, exact-share S(t) is evaluated directly.
        assert result["distance64"] <= tolerance * 1.001
        print(
            f"epsilon={tolerance:g}, max quadrature cells={worst[0]}, case={worst[1]}, "
            f"integral64 relative error={result['distance64']:.6g}, "
            f"stored transfer tree32 relative error={result['distance_tree32']:.6g}"
        )

    print("\nLinear-share tolerance sweep, maximum-ratio ramp grid")
    for tolerance in (1e-4, 1e-5, 1e-6):
        cases = [
            (len(mesh(v0, v1, kind, mix, tolerance)), (v0, v1, kind, mix))
            for v0, v1 in ((0.05, 8), (8, 0.05))
            for kind in kinds
            for mix in mixes
        ]
        print(f"epsilon={tolerance:g}, max cells={max(cases)[0]}")

    print("\nFloat32 normalized endpoint storage, and absolute timestamp collapse at 1800 s")
    case = worst_cases[1]
    cells = mesh(*case, epsilon)
    endpoints = [cells[0][1], *(cell[2] for cell in cells)]
    offsets32 = [f32(x) for x in endpoints]
    print(
        f"normalized endpoints: {len(set(offsets32))}/{len(endpoints)} distinct; "
        f"max offset error={max(abs(x - y) for x, y in zip(endpoints, offsets32, strict=True)):.6g}"
    )
    for duration in (1, 0.1, 0.001):
        times = [f32(1800 + duration * x) for x in endpoints]
        print(
            f"duration={duration:g}s: absolute f32 endpoints {len(set(times))}/{len(times)} distinct; "
            f"collapsed cells={sum(a == b for a, b in pairwise(times))}; "
            f"minimum exact cell duration={duration * min(b - a for _, a, b in cells):.6g}s"
        )

    print("\nGlobal-vs-local float32 speed polynomial, decreasing 8 -> 0.05 ease-out")
    piece = pieces(8, 0.05, "out")[0]
    global_error = max(
        abs(horner((piece.c, piece.d, piece.e), f32(i / 4096), f32) / piece.value(i / 4096) - 1) for i in range(4097)
    )
    print(f"global coefficient Horner max relative error={global_error:.6g}")
    stable_error = 0.0
    for i in range(4097):
        u = f32(i / 4096)
        remaining = f32(1 - u)
        # v_min + positive_delta * complementary ease: no cancellation of
        # two large nearly equal speeds at the small target endpoint.
        stable = f32(f32(0.05) + f32(f32(7.95) * f32(remaining * remaining)))
        stable_error = max(stable_error, abs(stable / piece.value(u) - 1))
    print(f"positive complementary-ease evaluation max relative error={stable_error:.6g}")
    assert stable_error < 1e-6

    print("\nFixed group mix, positive skip-free speed: bounded local integration and horizon")
    # For ONE mix across the whole history, D(t,h) = v(t)^m * integral_t^h v(s)^(1-m).
    # Each positive integrand factor lies in [v_min, v_max], so for t <= h,
    # v_min*(h-t) <= D(t,h) <= v_max*(h-t). This claim fails for changing mix.
    minimum_factor, maximum_factor = float("inf"), 0.0
    for mix in (0, *mixes, 1):
        for speed_now in (0.05, 0.1, 1, 4, 8):
            for speed_future in (0.05, 0.1, 1, 4, 8):
                factor = speed_now**mix * speed_future ** (1 - mix)
                minimum_factor = min(minimum_factor, factor)
                maximum_factor = max(maximum_factor, factor)
    assert minimum_factor >= 0.05 * (1 - 1e-14)
    assert maximum_factor <= 8 * (1 + 1e-14)
    print(f"sampled integrand factor extrema={minimum_factor:.6g}, {maximum_factor:.6g}")
    preempt = 0.35
    for minimum_progress in (0, -1):
        upper_distance = preempt * (1 - minimum_progress)
        print(
            f"illustrative preempt={preempt}, p_min={minimum_progress}: "
            f"distance upper bound={upper_distance:g}, "
            f"all times before hit-{upper_distance / 0.05:g}s are provably outside"
        )

    # The oracle itself is checked against a closed-form positive linear ramp.
    q = 0.5
    exact = (8 ** (q + 1) - 0.05 ** (q + 1)) / ((q + 1) * (8 - 0.05))
    numerical = simpson(lambda t: (0.05 + 7.95 * t) ** q, 0, 1)
    assert abs(numerical / exact - 1) < 1e-12
    print(f"Simpson oracle vs analytic linear integral relative error={abs(numerical / exact - 1):.6g}")


if __name__ == "__main__":
    main()
