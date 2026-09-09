# ruff: noqa: PT009, PT027
"""Execute optimized numeric probes; these tests do not establish client precision."""

from __future__ import annotations

import unittest
from contextlib import closing
from decimal import Decimal, localcontext

from sonolus.backend.blocks import PlayBlock
from sonolus.backend.node import FunctionNode
from sonolus.backend.ops import Op
from sonolus.script.archetype import EntityRef, PlayArchetype, entity_data, entity_memory, imported
from sonolus.script.internal.context import RuntimeChecks

from sekai.lib.timescale import (
    TargetPosition,
    TrajectoryCache,
    prepare_group,
    prepare_trajectory,
    prepared_time_matches,
)
from sekai.lib.timescale_consumer import prepare_note_trajectories
from sekai.lib.timescale_math import (
    AccurateScalar,
    NativeProgress,
    _Pair,
    _two_product,
    _two_sum,
    certified_integrate_times,
    certified_speed_at,
    clamped_fraction,
    midpoint_parts,
    native_affine_progress,
    native_constant_progress,
    native_difference_progress,
    native_scroll_progress,
    polynomial_piece_integral,
    published_progress,
)
from sekai.play.timescale import TimescaleChange, TimescaleGroup
from tests.timescale_vm import NumericVM, binary32, compile_probe


class ArithmeticProbe(PlayArchetype):
    a: float = imported()
    b: float = imported()
    count: int = imported()
    residual: float = entity_data()
    accumulated: float = entity_data()

    def preprocess(self):
        # Dynamic imports keep the optimizer from constant-folding the probe.
        self.residual = (self.a + self.b) - self.a
        result = 0.0
        for _ in range(self.count):
            result += self.b
        self.accumulated = result


class ErrorFreeTransformProbe(PlayArchetype):
    a: float = imported()
    b: float = imported()
    summed: _Pair = entity_data()
    multiplied: _Pair = entity_data()

    def preprocess(self):
        self.summed = _two_sum(self.a, self.b)
        self.multiplied = _two_product(self.a, self.b)


class AccurateArithmeticProbe(PlayArchetype):
    a: float = imported()
    b: float = imported()
    count: int = imported()
    added: AccurateScalar = entity_data()
    multiplied: AccurateScalar = entity_data()
    divided: AccurateScalar = entity_data()
    cycled: AccurateScalar = entity_data()
    grown: AccurateScalar = entity_data()
    published: AccurateScalar = entity_data()
    completed: bool = entity_data()

    def preprocess(self):
        left = AccurateScalar.of(self.a)
        right = AccurateScalar.of(self.b)
        self.added = left.add(right)
        self.multiplied = left.mul(right)
        self.divided = left.div(right)
        self.published = left.published_mul(right).published_add(left)
        value = AccurateScalar.of(1.0)
        growth = AccurateScalar.of(1.0)
        inverse = AccurateScalar.of(1.0).div(right)
        for _ in range(self.count):
            value @= value.mul(inverse).mul(right)
            growth @= growth.mul(right)
        self.cycled = value
        self.grown = growth
        self.completed = True


class CertifiedPolynomialProbe(PlayArchetype):
    v0: float = imported()
    v1: float = imported()
    easing: int = imported()
    a: float = imported()
    b: float = imported()
    start: float = imported()
    end: float = imported()
    integrated: AccurateScalar = entity_data()
    sampled: AccurateScalar = entity_data()

    def preprocess(self):
        self.integrated = certified_integrate_times(self.v0, self.v1, self.easing, self.a, self.b, self.start, self.end)
        self.sampled = certified_speed_at(self.v0, self.v1, self.easing, self.a, self.b, self.end)


class PieceIntegralProbe(PlayArchetype):
    vleft: float = imported()
    vright: float = imported()
    curvature: float = imported()
    width: float = imported()
    integrated: AccurateScalar = entity_data()

    def preprocess(self):
        self.integrated = polynomial_piece_integral(
            AccurateScalar.of(self.vleft),
            AccurateScalar.of(self.vright),
            AccurateScalar.of(self.curvature),
            AccurateScalar.of(self.width),
        )


class PublishedGeometryProbe(PlayArchetype):
    a: float = imported()
    b: float = imported()
    x: float = imported()
    preempt: float = imported()
    offset: float = imported()
    exponent: int = imported()
    tolerance: float = imported()
    accurate: bool = imported()
    hull: AccurateScalar = entity_data()
    fraction: AccurateScalar = entity_data()
    divided: AccurateScalar = entity_data()
    progress: AccurateScalar = entity_data()
    delta: AccurateScalar = entity_data()
    within_tolerance: bool = entity_data()

    def preprocess(self):
        left = AccurateScalar.of(self.a)
        right = AccurateScalar.of(self.b)
        left.exponent += self.exponent
        right.exponent += self.exponent
        self.hull = left.hull(right)
        self.divided = left.published_div(right)
        self.fraction = clamped_fraction(
            AccurateScalar.of(self.a), AccurateScalar.of(self.b), AccurateScalar.of(self.x), accurate=self.accurate
        )
        self.progress = published_progress(left, self.preempt, self.offset)
        self.within_tolerance = self.progress.error_at_most(self.tolerance)
        self.delta = AccurateScalar.of(self.x).sub(AccurateScalar.of(self.a))


class GroupPreparationProbe(PlayArchetype):
    group_ref: int = imported()
    now: float = imported()
    step: float = imported()
    count: int = imported()
    sampled: float = entity_data()
    event: int = entity_data()

    def preprocess(self):
        for _ in range(self.count):
            prepare_group(self.group_ref, self.now)
            self.now += self.step
        self.sampled = TimescaleGroup.at(self.group_ref).current_speed
        self.event = TimescaleGroup.at(self.group_ref).current_event


class CachePreparationProbe(PlayArchetype):
    group_ref: int = imported()
    now: float = imported()
    hit: float = imported()
    target_event: int = imported()
    count: int = imported()
    target: TargetPosition = entity_data()
    cache: TrajectoryCache = entity_memory()
    sampled: AccurateScalar = entity_data()

    def preprocess(self):
        self.target = TargetPosition(self.target_event)
        for _ in range(self.count):
            prepare_trajectory(self.group_ref, self.hit, self.target, self.cache, self.now, target_ref=1)
        self.sampled = self.cache.value


class NotePreparationProbe(PlayArchetype):
    timescale_group: EntityRef[TimescaleGroup] = imported()
    now: float = imported()
    target_time: float = imported()
    target_event: int = imported()
    count: int = imported()
    attach_head_ref: EntityRef[NotePreparationProbe] = imported()
    attach_tail_ref: EntityRef[NotePreparationProbe] = imported()
    target_position: TargetPosition = entity_data()
    first: TrajectoryCache = entity_memory()
    second: TrajectoryCache = entity_memory()
    sampled: AccurateScalar = entity_data()

    @property
    def is_attached(self) -> bool:
        return False

    def preprocess(self):
        self.target_position = TargetPosition(self.target_event)
        for _ in range(self.count):
            prepare_note_trajectories(self, self.first, self.second, self.now)
        self.sampled = self.first.value


def legacy_prepare_note_trajectories(note, first, second, now):
    """Previous helper control flow, using the same current trajectory kernel."""
    if note.is_attached:
        head = note.attach_head_ref.get()
        tail = note.attach_tail_ref.get()
        prepare_trajectory(head.timescale_group, head.target_time, head.target_position, first, now, head.index)
        prepare_trajectory(tail.timescale_group, tail.target_time, tail.target_position, second, now, tail.index)
    else:
        prepare_trajectory(note.timescale_group, note.target_time, note.target_position, first, now, note.index)


class HotKernelProbe(PlayArchetype):
    hit: float = imported()
    now: float = imported()
    speed_value: float = imported()
    preempt: float = imported()
    offset: float = imported()
    vleft: float = imported()
    vright: float = imported()
    curvature: float = imported()
    bpm: float = imported()
    native: NativeProgress = entity_data()
    midpoint: _Pair = entity_data()
    integrated: AccurateScalar = entity_data()
    converted: AccurateScalar = entity_data()

    def preprocess(self):
        self.native = native_constant_progress(self.hit, self.now, self.speed_value, self.preempt, self.offset)
        self.midpoint = midpoint_parts(self.hit, self.now)
        self.integrated = polynomial_piece_integral(
            AccurateScalar.of(self.vleft),
            AccurateScalar.of(self.vright),
            AccurateScalar.of(self.curvature),
            AccurateScalar.difference(self.hit, self.now),
        )
        self.converted = AccurateScalar.of(49.0).scale(60.0).div(AccurateScalar.of(self.bpm))


class NativeDifferenceProbe(PlayArchetype):
    target_hi: float = imported()
    target_lo: float = imported()
    target_exponent: int = imported()
    target_error: float = imported()
    current_hi: float = imported()
    current_lo: float = imported()
    current_exponent: int = imported()
    current_error: float = imported()
    preempt: float = imported()
    offset: float = imported()
    output: NativeProgress = entity_data()

    def preprocess(self):
        target = AccurateScalar(self.target_hi, self.target_lo, self.target_exponent, self.target_error)
        current = AccurateScalar(self.current_hi, self.current_lo, self.current_exponent, self.current_error)
        self.output = native_difference_progress(target, current, self.preempt, self.offset)


class NativeAffineProbe(PlayArchetype):
    value: float = imported()
    ratio: float = imported()
    distance: float = imported()
    ratio_error: float = imported()
    preempt: float = imported()
    offset: float = imported()
    past: bool = imported()
    output: NativeProgress = entity_data()

    def preprocess(self):
        ratio = AccurateScalar.of(self.ratio)
        ratio.error = self.ratio_error
        self.output = native_affine_progress(
            AccurateScalar.of(self.value),
            ratio,
            AccurateScalar.of(self.distance),
            self.preempt,
            self.offset,
            self.past,
        )


class NativeScrollProbe(PlayArchetype):
    v0: float = imported()
    v1: float = imported()
    easing: int = imported()
    a: float = imported()
    b: float = imported()
    now_base: float = imported()
    divisor: float = imported()
    hit: float = imported()
    preempt: float = imported()
    offset: float = imported()
    shift: int = imported()
    sampled: AccurateScalar = entity_data()
    output: NativeProgress = entity_data()

    def preprocess(self):
        now = self.now_base + 1 / self.divisor
        self.sampled = certified_speed_at(self.v0, self.v1, self.easing, self.a, self.b, now)
        self.sampled.exponent += self.shift
        self.output = native_scroll_progress(self.hit, now, self.sampled, self.preempt, self.offset)


class ScaledPowerProbe(PlayArchetype):
    shift: int = imported()
    negative: bool = imported()
    multiplied: AccurateScalar = entity_data()
    divided: AccurateScalar = entity_data()

    def preprocess(self):
        value = AccurateScalar(0.75, 2.0**-30, 10, 2.0**-40)
        factor = AccurateScalar.of(-1 if self.negative else 1)
        factor.exponent += self.shift
        self.multiplied = value.mul(factor)
        self.divided = value.div(factor)


class FrameTimeWriteProbe(PlayArchetype):
    base: float = imported()
    divisor: float = imported()
    group_ref: int = imported()

    def preprocess(self):
        TimescaleGroup.at(self.group_ref).last_updated = self.base + 1 / self.divisor


class FrameTimeCheckProbe(PlayArchetype):
    base: float = imported()
    divisor: float = imported()
    group_ref: int = imported()
    delta: float = imported()
    exact_equal: bool = entity_data()
    guard_passed: bool = entity_data()

    def preprocess(self):
        now = self.base + 1 / self.divisor + self.delta
        stored = TimescaleGroup.at(self.group_ref).last_updated
        self.exact_equal = stored == now
        self.guard_passed = prepared_time_matches(stored, now)


def timeline_probe_memory(records, now, hit, preempt=0.35):
    with closing(timeline_probe_frames(records, [now], hit, preempt)) as frames:
        return next(frames)


def timeline_probe_frames(records, times, hit, preempt=0.35):
    """Export host-preprocessed fixtures for compiled hot-path benchmarks.

    This measures compiled queries, not compiled preprocessing. Record heads are
    storage-safe, but this fixture does not model binary32 beat conversion.
    """
    from sekai.lib import timescale as ts
    from tests.test_timescale_timeline import TimelineFixture

    size = len(records) + 2
    memory = {
        int(PlayBlock.EntityDataArray): [0.0] * (size * 32),
        int(PlayBlock.EntitySharedMemoryArray): [0.0] * (size * 32),
        int(PlayBlock.EntityInfoArray): [v for i in range(size) for v in (i, min(i, 2), int(i < 2))],
    }
    refs = {
        "first_ref",
        "root",
        "final_ref",
        "current_event",
        "current_run",
        "current_run_end",
        "next_ref",
        "timescale_group",
        "tree_left",
        "tree_right",
        "subtree_first",
        "subtree_last",
        "run_first",
        "run_end",
        "prev_ref",
        "tree_parent",
        "validation_owner",
    }

    def map_ref(value):
        value = getattr(value, "index", value)
        return 1 if value == 100000 else value + 1 if value > 0 else 0

    def flatten(value):
        if hasattr(type(value), "_fields_"):
            return [number for field in type(value)._fields_ for number in flatten(getattr(value, field.name))]
        return [float(value)]

    def put(archetype, index, source):
        archetype._init_fields()
        for block, fields in (
            (PlayBlock.EntityDataArray, {**archetype._imported_fields_, **archetype._data_fields_}),
            (PlayBlock.EntitySharedMemoryArray, archetype._shared_memory_fields_),
        ):
            for name, field in fields.items():
                if not hasattr(source, name):
                    continue
                value = getattr(source, name)
                values = [map_ref(value)] if name in refs else flatten(value)
                for offset, number in enumerate(values):
                    memory[int(block)][index * 32 + field.offset + offset] = number

    with TimelineFixture(records, validate_oracle=False) as fixture:
        fixture.group.effective_preempt = preempt
        target = ts.locate_target(100000, hit)
        for index, marker in fixture.markers.items():
            put(TimescaleChange, index + 1, marker)
        for now in times:
            ts.prepare_group(100000, now)
            put(TimescaleGroup, 1, fixture.group)
            yield memory, (map_ref(target.event_ref),)


def decimal_primitive(kind, u):
    """Independent analytic easing primitives, evaluated with Decimal precision."""
    half = Decimal("0.5")
    if kind == 1:
        return u**2 / 2
    if kind == 2:
        return u**3 / 3
    if kind == 3:
        return u**2 - u**3 / 3
    if kind == 4:
        return 2 * u**3 / 3 if u <= half else u - half + 2 * (1 - u) ** 3 / 3
    if kind == 5:
        return u**2 - 2 * u**3 / 3 if u <= half else Decimal(1) / 6 + (u - half) / 2 + 2 * (u - half) ** 3 / 3
    return Decimal(0)


class CompiledNumericHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = compile_probe(ArithmeticProbe)

    def test_rounding_modes_and_compiled_loop(self):
        for precision, residual in (("binary32", 0.0), ("binary64", 1.0)):
            with self.subTest(precision=precision):
                result, vm = self.probe.run(precision=precision, a=2**24, b=1, count=7)
                self.assertEqual(result["residual"], (residual,))
                self.assertEqual(result["accumulated"], (7.0,))
                self.assertGreater(vm.steps, 7)
                self.assertLess(vm.steps, 300)
                self.assertLessEqual(vm.write_blocks, {int(PlayBlock.EntityData), int(PlayBlock.TemporaryMemory)})

    def test_execution_budget_is_enforced(self):
        with self.assertRaisesRegex(RuntimeError, "instruction budget"):
            self.probe.run(a=1, b=1, count=10_000, instruction_limit=50)
        with self.assertRaisesRegex(RuntimeError, "instruction budget"):
            NumericVM(instruction_limit=10).run(FunctionNode(Op.While, (1.0, 0.0)))

    def test_unsupported_client_operations_fail_explicitly(self):
        with self.assertRaisesRegex(NotImplementedError, "TimeToScaledTime"):
            NumericVM().run(FunctionNode(Op.TimeToScaledTime, (1.0, 1.0)))

    def test_native_interpolation_rounds_intermediate_operations(self):
        for precision in ("binary32", "binary64"):
            vm = NumericVM(precision=precision)
            expected = float(2**24) if precision == "binary32" else float(2**24 + 1)
            self.assertEqual(vm.run(FunctionNode(Op.Lerp, (2**24, 2**24 + 2, 0.5))), expected)
            expected_fraction = 0.5 if precision == "binary32" else (2**24 + 1) / 2**25
            self.assertEqual(vm.run(FunctionNode(Op.Unlerp, (-(2**24), 2**24, 1))), expected_fraction)
            self.assertEqual(vm.run(FunctionNode(Op.Remap, (-(2**24), 2**24, 0, 1, 1))), expected_fraction)
            self.assertEqual(vm.run(FunctionNode(Op.LerpClamped, (2, 4, 2))), 4)
            self.assertEqual(vm.run(FunctionNode(Op.UnlerpClamped, (2, 4, 6))), 1)
            self.assertEqual(vm.run(FunctionNode(Op.RemapClamped, (2, 4, 10, 20, -1))), 10)
            self.assertEqual(vm.run(FunctionNode(Op.Clamp, (5, 0, 1))), 1)


class CompiledTimescaleArithmeticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transforms = compile_probe(ErrorFreeTransformProbe)
        cls.arithmetic = compile_probe(AccurateArithmeticProbe)

    def assert_encloses(self, fields, reference):
        hi, lo, exponent, error = fields
        with localcontext() as context:
            context.prec = 1000
            scale = Decimal(2) ** int(exponent)
            center = (Decimal.from_float(hi) + Decimal.from_float(lo)) * scale
            radius = Decimal.from_float(error) * scale
            self.assertLessEqual(abs(center - reference), radius, (fields, reference))

    def test_optimizer_preserves_error_free_residuals(self):
        for precision, large in (("binary32", 2**24), ("binary64", 2**53)):
            with self.subTest(precision=precision):
                result, _ = self.transforms.run(precision=precision, a=large, b=1.0)
                self.assertEqual(result["summed"], (float(large), 1.0))
        a, b = binary32(0.7234567), binary32(0.8765432)
        result, _ = self.transforms.run(precision="binary32", a=a, b=b)
        hi, lo = result["multiplied"]
        self.assertNotEqual(lo, 0.0)
        self.assertEqual(hi + lo, a * b)

    def test_compiled_certificates_and_nondyadic_cycles(self):
        with localcontext() as context:
            context.prec = 1000
            for precision, storage in (("binary32", None), ("binary64", None), ("binary64", "binary32")):
                for a, b in ((1.0, binary32(7.8)), (binary32(0.05), 8.0), (-0.75, 0.75)):
                    with self.subTest(precision=precision, storage=storage, a=a, b=b):
                        result, vm = self.arithmetic.run(
                            precision=precision, entity_storage_precision=storage, a=a, b=b, count=128
                        )
                        x, y = Decimal.from_float(a), Decimal.from_float(b)
                        self.assert_encloses(result["added"], x + y)
                        self.assert_encloses(result["multiplied"], x * y)
                        self.assert_encloses(result["divided"], x / y)
                        self.assert_encloses(result["cycled"], Decimal(1))
                        self.assert_encloses(result["grown"], y**128)
                        self.assert_encloses(result["published"], x * y + x)
                        self.assertEqual(result["completed"], (1.0,))
                        hi, lo, exponent, _ = result["cycled"]
                        self.assertLess(abs((hi + lo) * 2**exponent - 1), 1e-8)
                        self.assertLess(vm.steps, 350_000)
                        self.assertLessEqual(
                            vm.write_blocks, {int(PlayBlock.EntityData), int(PlayBlock.TemporaryMemory)}
                        )
                        self.assertLessEqual(
                            vm.read_blocks,
                            {int(PlayBlock.EntityData), int(PlayBlock.TemporaryMemory), int(PlayBlock.EngineRom)},
                        )

    def test_native_difference_preserves_cancelled_prefixes(self):
        probe = compile_probe(NativeDifferenceProbe)
        for precision, storage in (("binary32", None), ("binary64", None), ("binary64", "binary32")):
            for delta in (0.001, -0.001, 0.0):
                with self.subTest(precision=precision, storage=storage, delta=delta):
                    quantize = binary32 if precision == "binary32" or storage == "binary32" else float
                    # Put the short interval in the low component, as a cached
                    # prefix near one million requires more than a binary32 head.
                    hi, lo, exponent = 1_000_000 / 2**20, quantize(delta / 2**20), 20
                    preempt = quantize(0.0035)
                    result, vm = probe.run(
                        precision=precision,
                        entity_storage_precision=storage,
                        target_hi=hi,
                        target_lo=lo,
                        target_exponent=exponent,
                        target_error=0,
                        current_hi=hi,
                        current_lo=0,
                        current_exponent=exponent,
                        current_error=0,
                        preempt=preempt,
                        offset=0,
                    )
                    with localcontext() as context:
                        context.prec = 1000
                        expected = 1 - Decimal.from_float(lo) * (2**20) / Decimal.from_float(preempt)
                        value, error = map(Decimal.from_float, result["output"])
                        self.assertLessEqual(abs(value - expected), error)
                    self.assertLess(vm.steps, 500)

    def test_native_affine_certificates_and_uncertain_denominator(self):
        probe = compile_probe(NativeAffineProbe)
        for precision, storage in (("binary32", None), ("binary64", None), ("binary64", "binary32")):
            quantize = binary32 if precision == "binary32" or storage == "binary32" else float
            for past in (False, True):
                for value, ratio, distance in ((0.25, 7.8, 0.05), (-0.25, -0.75, 0.05), (1e6, 1.0, -1e6)):
                    with self.subTest(precision=precision, storage=storage, past=past, value=value):
                        value, ratio, distance, preempt = map(quantize, (value, ratio, distance, 0.0035))
                        result, _ = probe.run(
                            precision=precision,
                            entity_storage_precision=storage,
                            value=value,
                            ratio=ratio,
                            distance=distance,
                            preempt=preempt,
                            offset=0.125,
                            ratio_error=0,
                            past=past,
                        )
                        with localcontext() as context:
                            context.prec = 1000
                            c, r, b, p = map(Decimal.from_float, (value, ratio, distance, preempt))
                            trajectory = -(c + b) / r if past else r * c + b
                            expected = 1 - trajectory / p - Decimal("0.125")
                            center, radius = map(Decimal.from_float, result["output"])
                            self.assertLessEqual(abs(center - expected), radius)
            result, _ = probe.run(
                precision=precision,
                entity_storage_precision=storage,
                value=1,
                ratio=0.75,
                distance=0.25,
                preempt=1,
                offset=0,
                ratio_error=0.8,
                past=True,
            )
            self.assertEqual(result["output"][1], float("inf"))

    def test_exact_power_of_two_scaling_preserves_uncertainty(self):
        probe = compile_probe(ScaledPowerProbe)
        for precision, storage in (("binary32", None), ("binary64", None), ("binary64", "binary32")):
            for shift in (-1536, 1536):
                for negative in (False, True):
                    with self.subTest(precision=precision, storage=storage, shift=shift, negative=negative):
                        result, _ = probe.run(
                            precision=precision,
                            entity_storage_precision=storage,
                            shift=shift,
                            negative=negative,
                        )
                        sign = -1 if negative else 1
                        self.assertEqual(result["multiplied"], (sign * 0.75, sign * 2.0**-30, 10 + shift, 2.0**-40))
                        self.assertEqual(result["divided"], (sign * 0.75, sign * 2.0**-30, 10 - shift, 2.0**-40))

    def test_native_scroll_certificates_all_eases_and_guarded_fallback(self):
        from tests.timescale_reference import speed_value

        probe = compile_probe(NativeScrollProbe)
        for precision, storage in (("binary32", None), ("binary64", None), ("binary64", "binary32")):
            quantize = binary32 if precision == "binary32" or storage == "binary32" else float
            arithmetic = binary32 if precision == "binary32" else float
            for easing in range(6):
                for values in (
                    (0.05, 8, 1799.5, 1800.5, 1800, 10, 1801.25),
                    (7.8, 0.05, 0, 1, 0, 2, 2),
                    (0.05, 8, 0, 1, -1, 1, 1.25),
                    (8, 0.05, 0, 1, 0, 1, -0.25),
                ):
                    with self.subTest(precision=precision, storage=storage, easing=easing, values=values):
                        v0, v1, a, b, base, divisor, hit = map(quantize, values)
                        preempt = quantize(0.0035)
                        result, _ = probe.run(
                            precision=precision,
                            entity_storage_precision=storage,
                            v0=v0,
                            v1=v1,
                            easing=easing,
                            a=a,
                            b=b,
                            now_base=base,
                            divisor=divisor,
                            hit=hit,
                            preempt=preempt,
                            offset=0.125,
                            shift=0,
                        )
                        now = arithmetic(base + arithmetic(1 / divisor))
                        with localcontext() as context:
                            context.prec = 1000
                            start, end, time = map(Decimal.from_float, (a, b, now))
                            u = max(Decimal(0), min(Decimal(1), (time - start) / (end - start)))
                            current_speed = speed_value(v0, v1, easing, u)
                            expected = 1 - (Decimal.from_float(hit) - time) * current_speed / Decimal.from_float(
                                preempt
                            )
                            expected -= Decimal("0.125")
                            center, radius = map(Decimal.from_float, result["output"])
                            self.assertLessEqual(abs(center - expected), radius)
            for hit, preempt, offset, shift in (
                (2.0**31, 1, 0, 0),
                (1, 2.0**-31, 0, 0),
                (1, 1, 2.0**61, 0),
                (1, 1, 0, 40),
            ):
                result, _ = probe.run(
                    precision=precision,
                    entity_storage_precision=storage,
                    v0=1,
                    v1=2,
                    easing=1,
                    a=0,
                    b=1,
                    now_base=0,
                    divisor=2,
                    hit=hit,
                    preempt=preempt,
                    offset=offset,
                    shift=shift,
                )
                self.assertEqual(result["output"][1], float("inf"))

    def test_computed_frame_time_survives_binary32_entity_storage(self):
        writer = compile_probe(FrameTimeWriteProbe, archetypes=[FrameTimeWriteProbe, TimescaleGroup, TimescaleChange])
        reader = compile_probe(FrameTimeCheckProbe, archetypes=[FrameTimeCheckProbe, TimescaleGroup, TimescaleChange])
        memory = {int(PlayBlock.EntityInfoArray): [0, 0, 1, 1, 1, 1]}
        for base in (3.0, 1800.0):
            _, written = writer.run(
                precision="binary64",
                entity_storage_precision="binary32",
                memory=memory,
                base=base,
                divisor=10,
                group_ref=1,
            )
            for delta, matches in ((0.0, True), (0.016, False)):
                result, _ = reader.run(
                    precision="binary64",
                    entity_storage_precision="binary32",
                    memory=written.blocks,
                    base=base,
                    divisor=10,
                    group_ref=1,
                    delta=delta,
                )
                self.assertEqual(result["exact_equal"], (0.0,))
                self.assertEqual(result["guard_passed"], (float(matches),))

    def test_compiled_hull_fraction_progress_and_error_comparison(self):
        probe = compile_probe(PublishedGeometryProbe)
        with localcontext() as context:
            context.prec = 1000
            for precision, storage in (("binary32", None), ("binary64", None), ("binary64", "binary32")):
                for a, b, x, exponent in (
                    (0.0, 3.0, 1.0, 0),
                    (2.0, 5.0, 10.0, 0),
                    (1.0, 1.0, 3.0, 0),
                    (1799.999, 1800.0, 1799.9995, 0),
                    (-0.75, 0.5, 0.0, 1536),
                ):
                    for accurate in (False, True):
                        with self.subTest(
                            precision=precision, storage=storage, a=a, exponent=exponent, accurate=accurate
                        ):
                            quantize = binary32 if precision == "binary32" or storage == "binary32" else float
                            a, b, x = quantize(a), quantize(b), quantize(x)
                            lead, offset = quantize(0.35), quantize(0.2)
                            result, _ = probe.run(
                                precision=precision,
                                entity_storage_precision=storage,
                                a=a,
                                b=b,
                                x=x,
                                exponent=exponent,
                                preempt=lead,
                                offset=offset,
                                tolerance=1e-4,
                                accurate=accurate,
                            )
                            da, db, dx = map(Decimal.from_float, (a, b, x))
                            scale = Decimal(2) ** exponent
                            self.assert_encloses(result["hull"], da * scale)
                            self.assert_encloses(result["hull"], db * scale)
                            self.assert_encloses(result["divided"], da / db)
                            fraction = (
                                Decimal("0.5")
                                if abs(b - a) < 1e-6
                                else max(Decimal(0), min(Decimal(1), (dx - da) / (db - da)))
                            )
                            self.assert_encloses(result["fraction"], fraction)
                            self.assert_encloses(
                                result["progress"],
                                1 - da * scale / Decimal.from_float(lead) - Decimal.from_float(offset),
                            )
                            self.assert_encloses(result["delta"], dx - da)
                            if precision == "binary32" or storage == "binary32":
                                self.assertEqual(result["delta"][3], 0.0)
                            if exponent == 1536:
                                self.assertEqual(result["within_tolerance"], (0.0,))

    def test_compiled_hot_kernels_and_varied_bpm_certificates(self):
        probe = compile_probe(HotKernelProbe)
        with localcontext() as context:
            context.prec = 1000
            for precision, storage in (("binary32", None), ("binary64", None), ("binary64", "binary32")):
                quantize = binary32 if precision == "binary32" or storage == "binary32" else float
                for hit, now, speed_value in ((4.0, 3.0, 1.0), (1800.0, 1799.9995, 8.0), (3.0, 4.0, -2.0)):
                    for bpm in (50, 60, 75, 120, 137, 180):
                        with self.subTest(precision=precision, storage=storage, hit=hit, now=now, bpm=bpm):
                            inputs = {
                                name: quantize(value)
                                for name, value in {
                                    "hit": hit,
                                    "now": now,
                                    "speed_value": speed_value,
                                    "preempt": 0.35,
                                    "offset": 0.2,
                                    "vleft": 1.0,
                                    "vright": 2.0,
                                    "curvature": 0.02,
                                    "bpm": bpm,
                                }.items()
                            }
                            out, _ = probe.run(
                                precision=precision,
                                entity_storage_precision=storage,
                                hit=inputs["hit"],
                                now=inputs["now"],
                                speed_value=inputs["speed_value"],
                                preempt=inputs["preempt"],
                                offset=inputs["offset"],
                                vleft=inputs["vleft"],
                                vright=inputs["vright"],
                                curvature=inputs["curvature"],
                                bpm=inputs["bpm"],
                            )
                            values = {name: Decimal.from_float(value) for name, value in inputs.items()}
                            width = values["hit"] - values["now"]
                            reference = 1 - width * values["speed_value"] / values["preempt"] - values["offset"]
                            value, error = map(Decimal.from_float, out["native"])
                            self.assertLessEqual(abs(value - reference), error)
                            midpoint = sum(map(Decimal.from_float, out["midpoint"]))
                            self.assertEqual(midpoint, (values["hit"] + values["now"]) / 2)
                            integral = width * (
                                (values["vleft"] + values["vright"]) / 2 - values["curvature"] * width**2 / 6
                            )
                            self.assert_encloses(out["integrated"], integral)
                            self.assert_encloses(out["converted"], Decimal(49) * 60 / values["bpm"])

    def test_zero_denominator_terminates_before_publishing_result(self):
        checked = compile_probe(AccurateArithmeticProbe, runtime_checks=RuntimeChecks.TERMINATE)
        for precision in ("binary32", "binary64"):
            with self.subTest(precision=precision):
                result, _ = checked.run(precision=precision, a=1, b=0, count=1)
                self.assertEqual(result["completed"], (0.0,))
                self.assertEqual(result["divided"], (0.0, 0.0, 0.0, 0.0))

    def test_nonfinite_inputs_terminate_before_publishing_result(self):
        checked = compile_probe(AccurateArithmeticProbe, runtime_checks=RuntimeChecks.TERMINATE)
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                result, _ = checked.run(precision="binary32", a=value, b=1, count=0)
                self.assertEqual(result["completed"], (0.0,))

    def test_scaled_arithmetic_exceeds_binary64_range_without_materializing(self):
        result, _ = self.arithmetic.run(precision="binary32", a=1, b=8, count=512)
        with localcontext() as context:
            context.prec = 1000
            self.assert_encloses(result["grown"], Decimal(2) ** 1536)
        self.assertGreater(result["grown"][2], 1024)

    def test_piece_integral_certificates(self):
        probe = compile_probe(PieceIntegralProbe)
        with localcontext() as context:
            context.prec = 1000
            for precision, storage in (("binary32", None), ("binary64", None), ("binary64", "binary32")):
                quantize = binary32 if precision == "binary32" or storage == "binary32" else float
                for values in (
                    (0.05, 8, 0.02, 6),
                    (8, 0.05, -0.02, 6),
                    (-1, 1, 0, 10),
                    (1, 1, 0, 0),
                    (0.05, 7.8, 5, 0.001),
                    (7.8, 0.05, 5, -0.001),
                ):
                    with self.subTest(precision=precision, storage=storage, values=values):
                        left, right, curve, width = map(quantize, values)
                        result, _ = probe.run(
                            precision=precision,
                            entity_storage_precision=storage,
                            vleft=left,
                            vright=right,
                            curvature=curve,
                            width=width,
                        )
                        dl, dr, dc, dw = map(Decimal.from_float, (left, right, curve, width))
                        expected = dw * ((dl + dr) / 2 - dc * dw**2 / 6)
                        self.assert_encloses(result["integrated"], expected)

    def test_certified_polynomials_enclose_independent_decimal_integral(self):
        certified = compile_probe(CertifiedPolynomialProbe)
        with localcontext() as context:
            context.prec = 1000
            for easing in range(6):
                for precision, storage in (("binary32", None), ("binary64", None), ("binary64", "binary32")):
                    for a, b, start, end, start_speed, end_speed in (
                        (-2.0, 8.0, 2.0, 6.0, 8.0, 0.05),
                        (1790.0, 1800.0, 1799.999, 1799.9995, 8.0, 0.05),
                        (0.0, 10.0, 8.0, 2.0, 8.0, 0.05),
                        (0.0, 0.001, 0.0001, 0.0009, 8.0, 0.05),
                        (0.0, 10.0, 2.0, 8.0, -1.0, 1.0),
                        (0.0, 10.0, 4.999, 5.001, -1.0, 1.0),
                    ):
                        with self.subTest(
                            easing=easing, precision=precision, storage=storage, a=a, b=b, start=start, end=end
                        ):
                            quantize = binary32 if precision == "binary32" or storage == "binary32" else float
                            inputs = {"v0": quantize(start_speed), "v1": quantize(end_speed), "easing": easing}
                            inputs.update(
                                {
                                    name: quantize(value)
                                    for name, value in zip(("a", "b", "start", "end"), (a, b, start, end), strict=True)
                                }
                            )
                            result, vm = certified.run(precision=precision, entity_storage_precision=storage, **inputs)
                            da, db, left, right = (
                                Decimal.from_float(inputs[name]) for name in ("a", "b", "start", "end")
                            )
                            v0, v1 = Decimal.from_float(inputs["v0"]), Decimal.from_float(inputs["v1"])
                            duration = db - da
                            u0, u1 = (left - da) / duration, (right - da) / duration
                            reference = v0 * (right - left)
                            if easing:
                                reference += (
                                    duration
                                    * (v1 - v0)
                                    * (decimal_primitive(easing, u1) - decimal_primitive(easing, u0))
                                )
                            self.assert_encloses(result["integrated"], reference)
                            self.assertLess(vm.steps, 100_000)


if __name__ == "__main__":
    unittest.main()
