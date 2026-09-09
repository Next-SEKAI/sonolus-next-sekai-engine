# ruff: noqa: PT009
"""Compile the complete consumer path; instruction counts are not client timings."""

from __future__ import annotations

import unittest
from typing import cast

from sonolus.backend.blocks import PlayBlock
from sonolus.backend.mode import Mode
from sonolus.backend.optimize import STANDARD_PASSES, OptimizerConfig, optimize_and_finalize
from sonolus.build.compile import callback_to_cfg
from sonolus.script.archetype import EntityRef, PlayArchetype, entity_data, entity_memory, imported
from sonolus.script.internal.context import ModeContextState, ProjectContextState

from sekai.lib.layout import DynamicLayout, Layout, preempt_time
from sekai.lib.timescale import CacheKind, TargetPosition, TrajectoryCache
from sekai.lib.timescale_consumer import (
    TrajectoryDiagnostics,
    attachment_remaining,
    note_draw_progress,
    note_visual_progress_value,
)
from sekai.lib.timescale_math import AccurateScalar
from sekai.play.timescale import TimescaleChange, TimescaleGroup
from tests.test_timescale_compiled import timeline_probe_memory
from tests.timescale_reference import RefMarker
from tests.timescale_vm import CompiledProbe, binary32, compile_probe


def decode_scalar(values: tuple[float, ...]) -> AccurateScalar:
    return AccurateScalar(values[0], values[1], int(values[2]), values[3])


class ConsumerProbe(PlayArchetype):
    target_time: float = imported()
    now: float = imported()
    target_step: float = imported()
    count: int = imported()
    target_event: int = imported()
    target_prefix: float = imported()
    cache_kind: int = imported()
    timescale_group: EntityRef[TimescaleGroup] = imported()
    attach_head_ref: EntityRef[ConsumerProbe] = imported()
    attach_tail_ref: EntityRef[ConsumerProbe] = imported()
    visual_y_offset: float = imported()

    target_position: TargetPosition = entity_data()
    first: TrajectoryCache = entity_memory()
    second: TrajectoryCache = entity_memory()
    diagnostics: TrajectoryDiagnostics = entity_memory()

    output: AccurateScalar = entity_data()
    refinements: int = entity_data()
    scalar_output: float = entity_data()
    preempt: float = entity_data()
    native: bool = imported()
    native_progress_certified: bool = imported()

    @property
    def is_attached(self) -> bool:
        return False

    def preprocess(self):
        Layout.default_preempt = preempt_time()
        self.preempt = Layout.default_preempt
        DynamicLayout.progress_start = -3.0
        DynamicLayout.progress_cutoff = 6.0
        self.first.kind = CacheKind.IDENTITY
        self.first.run_ref = 0
        if self.timescale_group.index > 0:
            self.first.kind = CacheKind.SAME
            if self.cache_kind != 0:
                self.first.kind = cast(CacheKind, self.cache_kind)
            self.first.run_ref = self.timescale_group.get().current_run
        self.target_position.event_ref = self.target_event
        self.first.valid = True
        self.first.value = AccurateScalar.of(self.target_prefix)
        for _ in range(self.count):
            if self.native:
                self.scalar_output = note_draw_progress(self, self.first, self.second, self.now, self.diagnostics)
            else:
                self.output = note_visual_progress_value(self, self.first, self.second, self.now, self.diagnostics)
            # Vary source metadata to prevent folding repeated evaluations.
            self.visual_y_offset += self.target_step
        self.refinements = self.diagnostics.accurate_refinements


class AttachmentBlendProbe(PlayArchetype):
    head_remaining: float = imported()
    tail_remaining: float = imported()
    head_time: float = imported()
    tail_time: float = imported()
    target_time: float = imported()
    now: float = imported()
    output: AccurateScalar = entity_data()

    def preprocess(self):
        remaining = attachment_remaining(
            AccurateScalar.of(self.head_remaining),
            AccurateScalar.of(self.tail_remaining),
            self.head_time, self.tail_time, self.target_time, self.now, True,
        )
        self.output = AccurateScalar.of(1).sub(remaining).published()


class NearTailConsumerProbe(ConsumerProbe):
    failed: int = entity_data()

    @property
    def is_attached(self) -> bool:
        return True

    def preprocess(self):
        Layout.default_preempt = .0035
        Layout.spawn_progress_start = -3
        Layout.spawn_progress_cutoff = 6
        DynamicLayout.progress_start = -3
        DynamicLayout.progress_cutoff = 6
        self.first.kind = CacheKind.IDENTITY
        self.first.valid = True
        self.second.kind = CacheKind.IDENTITY
        self.second.valid = True
        self.scalar_output = note_draw_progress(self, self.first, self.second, self.now, self.diagnostics)
        self.refinements = self.diagnostics.accurate_refinements
        self.failed = self.diagnostics.uncertified_results


def put_fixture(memory, archetype, index, **fields):
    archetype._init_fields()
    data = {**archetype._imported_fields_, **archetype._data_fields_}
    shared = archetype._shared_memory_fields_
    for name, values in fields.items():
        block = PlayBlock.EntityDataArray if name in data else PlayBlock.EntitySharedMemoryArray
        field = data[name] if name in data else shared[name]
        for offset, value in enumerate(values if isinstance(values, tuple) else (values,)):
            memory[int(block)][index * 32 + field.offset + offset] = value


def grouped_hold_memory(now: float, speed: float = 1.0) -> dict[int, list[float]]:
    """Immutable one-marker group and its already prepared current-frame state."""
    memory = {int(PlayBlock.EntityDataArray): [0.0] * 96, int(PlayBlock.EntitySharedMemoryArray): [0.0] * 96}

    memory[int(PlayBlock.EntityInfoArray)] = [0, 0, 1, 1, 1, 1, 2, 2, 0]
    one = (0.5, 0.0, 1.0, 0.0)
    certified_speed = AccurateScalar.of(speed)
    put_fixture(memory,
        TimescaleGroup, 1, first_ref=2, root=2, final_ref=2, valid=1, marker_count=1,
        force_note_speed=12, effective_preempt=0.35, time_valid=1, last_updated=now, current_event=2, current_run=2,
        current_constant=True, current_speed=speed,
        certified_current_speed=(certified_speed.hi, certified_speed.lo, certified_speed.exponent, certified_speed.error),
        future_ratio=one, past_ratio=one, past_distance=(0.75, 0.0, 2, 0),
    )
    put_fixture(memory, TimescaleChange, 2, timescale=speed, event_start=0, event_end=float("inf"), run_first=2, ordinal=1)
    return memory


def grouped_linear_memory() -> dict[int, list[float]]:
    """v(t)=1+t on [0,2]; current prefix at t=1 is exactly 1.5."""
    memory = grouped_hold_memory(1.0)
    for block in (PlayBlock.EntityDataArray, PlayBlock.EntitySharedMemoryArray):
        memory[int(block)].extend([0.0] * 32)
    memory[int(PlayBlock.EntityInfoArray)].extend([3, 2, 0])
    put_fixture(memory, TimescaleGroup, 1, final_ref=3, marker_count=2, current_constant=False,
                current_speed=2, certified_current_speed=(0.5, 0, 2, 0), past_distance=(0.75, 0, 1, 0))
    put_fixture(memory, TimescaleChange, 2, timescale_ease=1, event_end=2, next_ref=3)
    put_fixture(memory, TimescaleChange, 3, timescale=3, event_start=2, event_end=float("inf"),
                run_first=2, ordinal=2, run_prefix=(0.5, 0, 3, 0))
    return memory


def compile_consumer_probe() -> CompiledProbe:
    project = ProjectContextState()
    mode = ModeContextState(Mode.PLAY, [ConsumerProbe, TimescaleGroup, TimescaleChange])
    cfg = callback_to_cfg(project, mode, ConsumerProbe.preprocess, "preprocess", archetype=ConsumerProbe)
    node = optimize_and_finalize(cfg, STANDARD_PASSES, OptimizerConfig(mode=Mode.PLAY, callback="preprocess"))
    return CompiledProbe(ConsumerProbe, node, tuple(project.rom.values))


class CompiledTimescaleConsumerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = compile_consumer_probe()
        cls.attachment = compile_probe(AttachmentBlendProbe)
        cls.near_tail = compile_probe(
            NearTailConsumerProbe, archetypes=[NearTailConsumerProbe, ConsumerProbe, TimescaleGroup, TimescaleChange]
        )

    def test_identity_consumer_certificate_and_instruction_count(self):
        measurements = []
        for count in (1, 20):
            outputs, vm = self.probe.run(
                precision="binary32", target_time=4.0, now=3.0, target_step=0.001, count=count
            )
            value = decode_scalar(outputs["output"])
            self.assertTrue(value.error_at_most(1e-4))
            self.assertEqual(outputs["refinements"], (0.0,))
            measurements.append(vm.steps)
        per_note = (measurements[1] - measurements[0]) / 19
        print(f"Consumer identity: {per_note:.0f} VM instructions/note, {per_note * 1000:.0f} for 1,000 notes")

    def test_grouped_constant_consumer_certificate_and_instruction_count(self):
        measurements = []
        for count in (1, 20):
            outputs, vm = self.probe.run(
                precision="binary32", memory=grouped_hold_memory(3.0), target_time=4.0, now=3.0,
                target_step=0.001, count=count, timescale_group=1, target_event=2, target_prefix=4.0,
            )
            value = decode_scalar(outputs["output"])
            self.assertTrue(value.error_at_most(1e-4))
            evaluated_offset = 0.0
            for _ in range(count - 1):
                evaluated_offset = binary32(evaluated_offset + binary32(0.001))
            expected = 1 - 1.0 / binary32(0.35) - evaluated_offset
            self.assertLessEqual(abs(value.to_float() - expected), value.absolute_error().to_float())
            self.assertEqual(outputs["refinements"], (0.0,))
            measurements.append(vm.steps)
        per_note = (measurements[1] - measurements[0]) / 19
        print(f"Consumer grouped hold: {per_note:.0f} VM instructions/note, {per_note * 1000:.0f} for 1,000 notes")

    def test_native_note_draw_progress_and_instruction_count(self):
        for grouped in (False, True):
            measurements = []
            for count in (1, 20):
                outputs, vm = self.probe.run(
                    precision="binary32", memory=grouped_hold_memory(3.0), target_time=4.0, now=3.0,
                    target_step=0.001, count=count, timescale_group=int(grouped),
                    target_event=2 if grouped else 0, target_prefix=4.0, native=True, native_progress_certified=True,
                )
                evaluated_offset = 0.0
                for _ in range(count - 1):
                    evaluated_offset = binary32(evaluated_offset + binary32(0.001))
                expected = 1 - 1.0 / (binary32(0.35) if grouped else outputs["preempt"][0]) - evaluated_offset
                self.assertAlmostEqual(outputs["scalar_output"][0], expected, delta=1e-4)
                self.assertEqual(outputs["refinements"], (0.0,))
                measurements.append(vm.steps)
            per_note = (measurements[1] - measurements[0]) / 19
            print(f"Native consumer {'grouped hold' if grouped else 'identity'}: {per_note:.0f} VM instructions/note")

    def test_native_same_run_linear_progress_and_instruction_count(self):
        measurements = []
        for count in (1, 20):
            outputs, vm = self.probe.run(
                precision="binary32", memory=grouped_linear_memory(), target_time=1.5, now=1.0,
                target_step=0.001, count=count, timescale_group=1, target_event=2,
                target_prefix=2.625, native=True, native_progress_certified=True,
            )
            evaluated_offset = 0.0
            for _ in range(count - 1):
                evaluated_offset = binary32(evaluated_offset + binary32(0.001))
            expected = 1 - (2.625 - 1.5) / binary32(0.35) - evaluated_offset
            self.assertAlmostEqual(outputs["scalar_output"][0], expected, delta=1e-4)
            self.assertEqual(outputs["refinements"], (0.0,))
            measurements.append(vm.steps)
        print(f"Native consumer linear: {(measurements[1] - measurements[0]) / 19:.0f} VM instructions/note")

    def test_native_same_run_target_after_later_marker(self):
        outputs, _ = self.probe.run(
            precision="binary32", memory=grouped_linear_memory(), target_time=2.5, now=1.0,
            target_step=0, count=1, timescale_group=1, target_event=3,
            target_prefix=5.5, native=True, native_progress_certified=True, visual_y_offset=-10,
        )
        expected = 1 - (5.5 - 1.5) / binary32(0.35) + 10
        self.assertAlmostEqual(outputs["scalar_output"][0], expected, delta=1e-4)
        self.assertEqual(outputs["refinements"], (0.0,))

    def test_future_hybrid_progress_and_instruction_count(self):
        records = [RefMarker(0, 1), RefMarker(1, 2, style=1), RefMarker(2, 1)]
        memory, target = timeline_probe_memory(records, .5, 1.5)
        measurements = []
        for count in (1, 20):
            outputs, vm = self.probe.run(
                precision="binary32", memory=memory, target_time=1.5, now=.5,
                target_step=.001, count=count, timescale_group=1, target_event=target[0],
                target_prefix=1.0, cache_kind=int(CacheKind.FUTURE), native=True,
                native_progress_certified=True, visual_y_offset=-1,
            )
            offset = -1.0
            for _ in range(count - 1):
                offset = binary32(offset + binary32(.001))
            expected = 1 - 1.5 / binary32(.35) - offset
            self.assertAlmostEqual(outputs["scalar_output"][0], expected, delta=1e-4)
            self.assertEqual(outputs["refinements"], (0.0,))
            measurements.append(vm.steps)
        print(f"Native consumer FUTURE hybrid: {(measurements[1] - measurements[0]) / 19:.0f} VM instructions/note")

    def test_past_hybrid_progress_uses_current_scroll_ratio(self):
        records = [RefMarker(0, 1), RefMarker(1, 2, ease=1, style=1), RefMarker(2, 3)]
        memory, target = timeline_probe_memory(records, 1.5, .5)
        outputs, _ = self.probe.run(
            precision="binary32", memory=memory, target_time=.5, now=1.5,
            target_step=0, count=1, timescale_group=1, target_event=target[0],
            target_prefix=.5, cache_kind=int(CacheKind.PAST), native=True,
            native_progress_certified=True, visual_y_offset=1,
        )
        # At now=1.5, current speed is 2.5; anchor speed is 2, so the
        # backward ratio is .8 and D=-(.5+1)/.8=-1.875.
        expected = 1.875 / binary32(.35)
        self.assertAlmostEqual(outputs["scalar_output"][0], expected, delta=1e-4)
        self.assertEqual(outputs["refinements"], (0.0,))

    def test_same_scroll_progress_across_internal_markers_and_instruction_count(self):
        records = [RefMarker(0, 1, ease=1, style=1), RefMarker(2, 3, style=1)]
        for hit, initial_offset in ((1.5, 0.0), (2.5, -6.0)):
            memory, target = timeline_probe_memory(records, 1.0, hit)
            measurements = []
            for count in (1, 20):
                outputs, vm = self.probe.run(
                    precision="binary32", memory=memory, target_time=hit, now=1.0,
                    target_step=.001, count=count, timescale_group=1, target_event=target[0],
                    target_prefix=0, native=True, native_progress_certified=True,
                    visual_y_offset=initial_offset,
                )
                offset = initial_offset
                for _ in range(count - 1):
                    offset = binary32(offset + binary32(.001))
                expected = 1 - 2 * (hit - 1) / binary32(.35) - offset
                self.assertAlmostEqual(outputs["scalar_output"][0], expected, delta=1e-4)
                self.assertEqual(outputs["refinements"], (0.0,))
                measurements.append(vm.steps)
            print(f"Native consumer SAME SCROLL hit={hit}: {(measurements[1] - measurements[0]) / 19:.0f} VM instructions/note")

    def test_same_scroll_progress_preserves_nondyadic_speed_uncertainty(self):
        records = [RefMarker(0, 1, ease=1, style=1), RefMarker(2, 3, style=1)]
        now = binary32(.3)
        hit = binary32(1.5)
        memory, target = timeline_probe_memory(records, now, hit)
        outputs, _ = self.probe.run(
            precision="binary32", memory=memory, target_time=hit, now=now,
            target_step=0, count=1, timescale_group=1, target_event=target[0],
            target_prefix=0, native=True, native_progress_certified=True, visual_y_offset=-1,
        )
        expected = 2 - (1 + now) * (hit - now) / binary32(.35)
        self.assertAlmostEqual(outputs["scalar_output"][0], expected, delta=1e-4)
        self.assertEqual(outputs["refinements"], (0.0,))

    def test_compiled_attachment_fraction_cancellation_is_certified(self):
        outputs, _ = self.attachment.run(
            precision="binary32", head_remaining=10000, tail_remaining=-20000,
            head_time=0, tail_time=3, target_time=1, now=-1,
        )
        value = decode_scalar(outputs["output"])
        self.assertAlmostEqual(value.to_float(), 1.0, delta=1e-4)
        self.assertTrue(value.error_at_most(1e-4))

    def test_native_signed_and_stop_constants_near_late_song_hit(self):
        now = binary32(1799.8)
        for speed in (-8.0, 0.0, 8.0):
            for offset in (-1.0, 0.0, 1.0):
                outputs, _ = self.probe.run(
                    precision="binary32", memory=grouped_hold_memory(now, speed),
                    target_time=1800.0, now=now, target_step=0, count=1,
                    timescale_group=1, target_event=2, native=True, native_progress_certified=True,
                    visual_y_offset=offset,
                )
                expected = 1 - ((1800.0 - now) * speed) / binary32(0.35) - offset
                self.assertAlmostEqual(outputs["scalar_output"][0], expected, delta=1e-4)

    def test_compiled_near_tail_attachment_refines_and_renders(self):
        memory = {
            int(PlayBlock.EntityDataArray): [0.0] * 96,
            int(PlayBlock.EntityInfoArray): [0, 0, 1, 1, 1, 0, 2, 1, 0],
        }
        put_fixture(memory, ConsumerProbe, 1, target_time=-2)
        put_fixture(memory, ConsumerProbe, 2, target_time=1)
        for gap in (2.0**-20, 17 * 2.0**-24):
            outputs, _ = self.near_tail.run(
                precision="binary32", memory=memory, target_time=1, now=1 - 3 * gap,
                attach_head_ref=1, attach_tail_ref=2,
            )
            fraction = .5 if gap < 1e-6 else 1.0
            expected = 1 - fraction * 3 * gap / binary32(.0035)
            self.assertAlmostEqual(outputs["scalar_output"][0], expected, delta=1e-4)
            self.assertEqual(outputs["refinements"], (1.0,))
            self.assertEqual(outputs["failed"], (0.0,))


if __name__ == "__main__":
    unittest.main()
