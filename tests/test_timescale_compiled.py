# ruff: noqa: PT009, PT027
"""Execute production kernels in explicit arithmetic/storage modes."""

import unittest
from decimal import Decimal, localcontext

from sonolus.backend.blocks import PlayBlock
from sonolus.backend.node import FunctionNode
from sonolus.backend.ops import Op
from sonolus.script.archetype import PlayArchetype, entity_data, entity_memory, imported
from sonolus.script.array import Dim
from sonolus.script.containers import VarArray

from sekai.lib.timescale import (
    TargetPosition,
    TrajectoryCache,
    evaluate_trajectory,
    initialize_timescale_group,
    locate_target,
    prepare_group,
    prepare_trajectory,
)
from sekai.lib.timescale_math import TimePosition, integrate_times, speed_at
from sekai.lib.timescale_visibility import VisibilitySource, first_visible
from sekai.play.timescale import TimescaleChange, TimescaleGroup
from tests.timescale_reference import RefMarker, RefTimeline, integrate_speed, speed_value, visibility_island_markers
from tests.timescale_vm import NumericVM, binary32, compile_probe

PRECISIONS = (("binary32", None), ("binary64", None), ("binary64", "binary32"))


class PositionProbe(PlayArchetype):
    initial: float = imported()
    increment: float = imported()
    delta: float = imported()
    count: int = imported()
    mode: int = imported()
    position: TimePosition = entity_data()
    local_difference: float = entity_data()
    history_difference: float = entity_data()

    def preprocess(self):
        self.position = TimePosition.of(self.initial)
        for i in range(self.count):
            value = self.increment
            if (self.mode == 1 and i >= self.count // 2) or (self.mode == 2 and i % 2):
                value = -value
            self.position = self.position.add(value)
        self.local_difference = self.position.add(self.delta).difference(self.position)
        self.history_difference = self.position.difference(TimePosition.of(self.initial))


class PolynomialProbe(PlayArchetype):
    v0: float = imported()
    v1: float = imported()
    easing: int = imported()
    start: float = imported()
    end: float = imported()
    left: float = imported()
    right: float = imported()
    integrated: float = entity_data()
    sampled: float = entity_data()

    def preprocess(self):
        self.integrated = integrate_times(self.v0, self.v1, self.easing, self.start, self.end, self.left, self.right)
        self.sampled = speed_at(self.v0, self.v1, self.easing, self.start, self.end, self.right)


class TimelineProbe(PlayArchetype):
    group_ref: int = imported()
    hit: float = imported()
    now: float = imported()
    step: float = imported()
    count: int = imported()
    target: TargetPosition = entity_data()
    cache: TrajectoryCache = entity_memory()
    distance: float = entity_data()

    def preprocess(self):
        initialize_timescale_group(TimescaleGroup.at(self.group_ref))
        self.target = locate_target(self.group_ref, self.hit)
        for _ in range(self.count):
            prepare_group(self.group_ref, self.now)
            prepare_trajectory(self.group_ref, self.hit, self.target, self.cache, self.now)
            self.distance = evaluate_trajectory(self.group_ref, self.hit, self.target, self.cache, self.now)
            self.now += self.step


class SpawnAccuracyProbe(PlayArchetype):
    group_ref: int = imported()
    hit: float = imported()
    preempt: float = imported()
    low: float = imported()
    high: float = imported()
    earliest: float = imported()
    latest: float = imported()
    spawned: float = entity_data()

    def preprocess(self):
        initialize_timescale_group(TimescaleGroup.at(self.group_ref))
        sources = VarArray[VisibilitySource, Dim[4]].new()
        sources.append(VisibilitySource(self.group_ref, self.hit, self.preempt, 0, 0, False))
        self.spawned = first_visible(sources, self.low, self.high, self.earliest, self.latest)


def timeline_memory(records):
    """Only imports: the probe performs compiled preprocessing too."""
    size = len(records) + 2
    memory = {
        int(PlayBlock.EntityDataArray): [0.0] * (size * 32),
        int(PlayBlock.EntityInfoArray): [v for i in range(size) for v in (i, min(i, 2), int(i < 2))],
    }

    def put(archetype, index, **values):
        archetype._init_fields()
        for name, value in values.items():
            memory[int(PlayBlock.EntityDataArray)][index * 32 + archetype._imported_fields_[name].offset] = float(value)

    put(TimescaleGroup, 1, first_ref=2 if records else 0, force_note_speed=12)
    for i, record in enumerate(records, 2):
        put(
            TimescaleChange,
            i,
            beat=record.time,
            timescale=record.speed,
            timescale_skip=record.skip,
            timescale_group=1,
            timescale_ease=record.ease,
            transition_style=record.style,
            next_ref=i + 1 if i + 1 < size else 0,
        )
    return memory


class CompiledTimescaleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.position = compile_probe(PositionProbe)
        cls.polynomial = compile_probe(PolynomialProbe)
        cls.timeline = compile_probe(TimelineProbe, archetypes=[TimelineProbe, TimescaleGroup, TimescaleChange])
        cls.spawn = compile_probe(SpawnAccuracyProbe, archetypes=[SpawnAccuracyProbe, TimescaleGroup, TimescaleChange])

    def test_compiled_spawn_preserves_long_signed_visibility_islands(self):
        # Cancellation in a long signed ramp can move a tiny visibility island
        # outside an overly narrow spawn allowance. Exercise actual compiled
        # preprocessing and search together, including a late-song hit.
        cases = (
            (
                0.0,
                413.3699951171875,
                binary32(7.8),
                binary32(-6.3),
                453.2076416015625,
                0.3500162363052368,
                307.4515686035156,
            ),
            (1328.8055419921875, 1742.175537109375, 8.0, -8.0, 1800.0, 1.499955654144287, 1621.102294921875),
        )
        for start, end, first, last, hit, preempt, visible_time in cases:
            records = [RefMarker(start, first, ease=2), RefMarker(end, last), RefMarker(end, 8)]
            oracle = RefTimeline(records)
            visible_distance = oracle.distance(visible_time, hit)
            self.assertGreaterEqual(visible_distance, -5 * Decimal.from_float(preempt))
            self.assertLessEqual(visible_distance, 4 * Decimal.from_float(preempt))
            for precision, storage in PRECISIONS:
                with self.subTest(start=start, precision=precision, storage=storage):
                    result, _ = self.spawn.run(
                        precision=precision,
                        entity_storage_precision=storage,
                        memory=timeline_memory(records),
                        instruction_limit=1_000_000,
                        group_ref=1,
                        hit=hit,
                        preempt=preempt,
                        low=-3,
                        high=6,
                        earliest=-2,
                        latest=hit,
                    )
                    self.assertLessEqual(result["spawned"][0], visible_time)

    def test_compiled_spawn_keeps_islands_signed_reversals_and_completed_jumps(self):
        cases = [
            (visibility_island_markers(), 3, -0.9, 1, 1, 4 / 3),
            ([RefMarker(0, 1), RefMarker(1, -1), RefMarker(2, 1)], 3, 0.7, 0.8, 0.65, 0.7),
            ([RefMarker(0, 1), RefMarker(1, 1, skip=10)], 2, -4, -3, float("inf"), float("inf")),
            ([RefMarker(0, 1, style=1), RefMarker(1, 0.1, style=1), RefMarker(1, 1)], 2, 0.45, 0.55, 1.4, 1.45),
        ]
        for precision, storage in PRECISIONS:
            for records, hit, low, high, earliest, latest in cases:
                with self.subTest(precision=precision, storage=storage, low=low):
                    result, _ = self.spawn.run(
                        precision=precision,
                        entity_storage_precision=storage,
                        memory=timeline_memory(records),
                        group_ref=1,
                        hit=hit,
                        preempt=1,
                        low=low,
                        high=high,
                        earliest=0,
                        latest=hit,
                    )
                    self.assertGreaterEqual(result["spawned"][0], earliest)
                    self.assertLessEqual(result["spawned"][0], latest)

    def test_vm_rounding_and_execution_budget(self):
        expression = FunctionNode(Op.Add, (float(2**24), 1.0))
        self.assertEqual(NumericVM(precision="binary32").run(expression), 2**24)
        self.assertEqual(NumericVM(precision="binary64").run(expression), 2**24 + 1)
        with self.assertRaisesRegex(RuntimeError, "budget"):
            NumericVM(instruction_limit=30).run(FunctionNode(Op.While, (1.0, 0.0)))

    def test_split_history_retains_local_differences_and_signed_reentry(self):
        for precision, storage in PRECISIONS:
            for mode in (0, 1, 2):
                with self.subTest(precision=precision, storage=storage, mode=mode):
                    result, _ = self.position.run(
                        precision=precision,
                        entity_storage_precision=storage,
                        instruction_limit=8_000_000,
                        initial=1_000_000,
                        increment=binary32(0.0001),
                        delta=binary32(0.001),
                        count=20_000,
                        mode=mode,
                    )
                    whole, fraction = result["position"]
                    self.assertEqual(whole % 1, 0)
                    # Binary32 persistence can round a binary64 remainder to an endpoint.
                    self.assertLessEqual(abs(fraction), 1)
                    self.assertAlmostEqual(result["local_difference"][0], binary32(0.001), delta=4e-6)
                    if mode:
                        self.assertAlmostEqual(result["history_difference"][0], 0, delta=2e-7)

    def test_split_remainder_storage_near_signed_unit_boundaries(self):
        for precision, storage in PRECISIONS:
            for sign in (-1, 1):
                initial, increment = sign * binary32(1 - 2**-24), sign * binary32(4e-8)
                with self.subTest(precision=precision, storage=storage, sign=sign):
                    result, _ = self.position.run(
                        precision=precision,
                        entity_storage_precision=storage,
                        initial=initial,
                        increment=increment,
                        delta=binary32(0.001),
                        count=1,
                        mode=0,
                    )
                    whole, fraction = result["position"]
                    self.assertLessEqual(abs(fraction), 1)
                    self.assertAlmostEqual(whole + fraction, initial + increment, delta=6e-8)
                    self.assertAlmostEqual(result["history_difference"][0], increment, delta=6e-8)
                    self.assertAlmostEqual(result["local_difference"][0], binary32(0.001), delta=6e-8)

    def test_all_native_eases_against_decimal(self):
        with localcontext() as context:
            context.prec = 60
            for precision, storage in PRECISIONS:
                quantize = binary32 if precision == "binary32" or storage == "binary32" else float
                for easing in range(6):
                    for values in (
                        (0.05, 8, 1790, 1800, 1799.999, 1799.9995),
                        (8, 0.05, 0, 10, 2, 8),
                        (-1, 1, 0, 10, 8, 2),
                        (0.05, 7.8, 0, 0.001, 0.0001, 0.0009),
                    ):
                        with self.subTest(precision=precision, storage=storage, easing=easing, values=values):
                            v0, v1, start, end, left, right = map(quantize, values)
                            result, _ = self.polynomial.run(
                                precision=precision,
                                entity_storage_precision=storage,
                                v0=v0,
                                v1=v1,
                                easing=easing,
                                start=start,
                                end=end,
                                left=left,
                                right=right,
                            )
                            a, b, l, r = map(Decimal.from_float, (start, end, left, right))
                            expected = float(integrate_speed(v0, v1, easing, b - a, l - a, r - a))
                            expected_speed = float(speed_value(v0, v1, easing, (r - a) / (b - a)))
                            scale = max(abs(v0), abs(v1))
                            self.assertAlmostEqual(
                                result["integrated"][0], expected, delta=16 * 2**-24 * abs(right - left) * scale + 1e-10
                            )
                            self.assertAlmostEqual(result["sampled"][0], expected_speed, delta=16 * 2**-24 * scale)

    def test_compiled_group_and_caches_across_runs_and_seeks(self):
        cases = [
            [
                RefMarker(0, 1, ease=1),
                RefMarker(1, 3, ease=2),
                RefMarker(2, 2, ease=4, style=1),
                RefMarker(3, 0.5, ease=5, style=1),
                RefMarker(4, 4, ease=3),
                RefMarker(5, 1),
            ],
            [RefMarker(0, 1, skip=0.5), RefMarker(1, -2, ease=4), RefMarker(2, 0, skip=-0.5), RefMarker(3, 3)],
        ]
        for records in cases:
            oracle = RefTimeline(records)
            for precision, storage in PRECISIONS:
                for now, hit, step in ((-0.5, 2.5, 0.25), (0.25, 0.5, 0.25), (4.5, 0.5, -0.25)):
                    with self.subTest(precision=precision, storage=storage, now=now, hit=hit):
                        result, _ = self.timeline.run(
                            precision=precision,
                            entity_storage_precision=storage,
                            memory=timeline_memory(records),
                            group_ref=1,
                            now=now,
                            hit=hit,
                            step=step,
                            count=12,
                        )
                        expected = float(oracle.distance(now + 11 * step, hit))
                        self.assertAlmostEqual(result["distance"][0], expected, delta=2e-5 * max(1, abs(expected)))

    def test_compiled_mixed_signed_skips_stops_and_zero_crossing(self):
        records = [
            RefMarker(0, -1, style=1, ease=1),
            RefMarker(1, 1, style=1, skip=-2),
            RefMarker(2, 0, skip=1),
            RefMarker(3, 0, style=1),
            RefMarker(4, -2, skip=-1),
            RefMarker(4, 2, style=1, skip=2),
            RefMarker(5, 1),
        ]
        oracle = RefTimeline(records)
        for precision, storage in PRECISIONS:
            for now, hit in (
                (0, 5),
                (0.499999, 5),
                (0.5, 5),
                (0.500001, 5),
                (1, 0),
                (2, 5),
                (2.5, 0),
                (3, 5),
                (3.5, 0),
                (4, 0.5),
                (4.5, 0),
                (5, 0),
            ):
                now, hit = binary32(now), binary32(hit)
                with self.subTest(precision=precision, storage=storage, now=now, hit=hit):
                    result, _ = self.timeline.run(
                        precision=precision,
                        entity_storage_precision=storage,
                        memory=timeline_memory(records),
                        group_ref=1,
                        now=now,
                        hit=hit,
                        step=0,
                        count=1,
                    )
                    expected = float(oracle.distance(now, hit))
                    self.assertAlmostEqual(result["distance"][0], expected, delta=1e-5 * max(1, abs(expected)))

    def test_compiled_10000_speed_bursts_and_long_coordinate_history(self):
        near_boundary = [(1798.999, 1799.001), (1799.749, 1799.751), (1799.999, 1800.001)]
        cases = [
            (
                [
                    RefMarker(0, 1),
                    RefMarker(1798, 1, ease=ease, style=style),
                    RefMarker(1799, 10000, ease=ease, style=style),
                    RefMarker(1799.75, 1),
                    RefMarker(1800, 1),
                ],
                near_boundary,
            )
            for style in range(2)
            for ease in range(6)
        ]
        cases.extend(
            (
                [
                    RefMarker(0, 1),
                    RefMarker(1200, 10000),
                    RefMarker(1500, 1),
                    RefMarker(1798, 1, style=style),
                    RefMarker(1798.5, 1),
                ]
                + [RefMarker(1799 + i / 4, 1) for i in range(5)],
                [(1798.875, 1799.125), (1799.875, 1800.125), (1799.999, 1800.001)],
            )
            for style in range(2)
        )
        for records, queries in cases:
            oracle = RefTimeline(records)
            for precision, storage in PRECISIONS:
                for now, hit in queries:
                    # Separate late-song input quantization from coordinate arithmetic error.
                    now, hit = binary32(now), binary32(hit)
                    with self.subTest(precision=precision, storage=storage, now=now, hit=hit, records=records):
                        result, _ = self.timeline.run(
                            precision=precision,
                            entity_storage_precision=storage,
                            memory=timeline_memory(records),
                            group_ref=1,
                            now=now,
                            hit=hit,
                            step=0,
                            count=1,
                        )
                        expected = float(oracle.distance(now, hit))
                        # At the shortest practical 0.1-second preempt, 1e-5 seconds is 1e-4 progress.
                        self.assertAlmostEqual(result["distance"][0], expected, delta=1e-5)

    def test_late_near_hit_and_frame_work(self):
        for easing in range(6):
            records = [RefMarker(0, 0.05, ease=easing), RefMarker(1800, 8)]
            oracle = RefTimeline([RefMarker(0, binary32(0.05), ease=easing), RefMarker(1800, 8)])
            now, hit = binary32(1799.9995), binary32(1800.0005)
            result, _ = self.timeline.run(
                precision="binary32", memory=timeline_memory(records), group_ref=1, now=now, hit=hit, step=0, count=1
            )
            self.assertAlmostEqual(result["distance"][0], float(oracle.distance(now, hit)), delta=4e-6)
        records = [RefMarker(0, 1, ease=4), RefMarker(10, 2), RefMarker(20, 1)]
        _, first = self.timeline.run(
            precision="binary32", memory=timeline_memory(records), group_ref=1, now=3, hit=6, step=0.001, count=1
        )
        _, many = self.timeline.run(
            precision="binary32", memory=timeline_memory(records), group_ref=1, now=3, hit=6, step=0.001, count=20
        )
        self.assertLess((many.steps - first.steps) / 19, 1100)


if __name__ == "__main__":
    unittest.main()
