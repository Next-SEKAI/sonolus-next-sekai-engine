# ruff: noqa: PT009
"""Preserve local scroll skips after large normalized histories."""

import unittest

from sonolus.backend.blocks import PlayBlock

from sekai.play.timescale import TimescaleChange, TimescaleGroup
from tests.test_timescale_compiled import PRECISIONS, TimelineProbe, timeline_memory
from tests.timescale_reference import RefMarker
from tests.timescale_vm import binary32, compile_probe


class ScrollPrefixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = compile_probe(TimelineProbe, archetypes=[TimelineProbe, TimescaleGroup, TimescaleChange])

    def test_stopped_skip_history_preserves_later_normal_skip(self):
        count = 1700
        end = count / 8
        for sign in (-1, 1):
            for style in (0, 1):
                records = [RefMarker(i / 8, 0, skip=sign, style=style) for i in range(count)] + [
                    RefMarker(end, 1, style=1),
                    RefMarker(end + 0.5, 1, skip=1, style=1),
                    RefMarker(end + 1, 1, style=1),
                ]
                for precision, storage in PRECISIONS:
                    with self.subTest(sign=sign, style=style, precision=precision, storage=storage):
                        result, _ = self.probe.run(
                            precision=precision,
                            entity_storage_precision=storage,
                            memory=timeline_memory(records),
                            group_ref=1,
                            now=end + 0.25,
                            hit=end + 0.75,
                            step=0,
                            count=1,
                            instruction_limit=10_000_000,
                        )
                        self.assertAlmostEqual(result["distance"][0], 1.5, delta=1e-6)

    def test_signed_block_carries_keep_high_speed_skip_precision(self):
        now, hit = binary32(1.4999), binary32(1.5001)
        for sign in (-1, 1):
            for history in (63.99995, 64.00005, 127.99995):
                records = [
                    RefMarker(0, 1, skip=sign * binary32(history), style=1),
                    RefMarker(1, 10000, style=1),
                    RefMarker(1.5, 10000, skip=sign, style=1),
                    RefMarker(2, 1, style=1),
                ]
                expected = 10000 * (hit - now) + sign
                for precision, storage in PRECISIONS:
                    with self.subTest(sign=sign, history=history, precision=precision, storage=storage):
                        result, _ = self.probe.run(
                            precision=precision,
                            entity_storage_precision=storage,
                            memory=timeline_memory(records),
                            group_ref=1,
                            now=now,
                            hit=hit,
                            step=0,
                            count=1,
                        )
                        # Unit fractions already incur up to 0.000166 at 10000x.
                        self.assertAlmostEqual(result["distance"][0], expected, delta=2e-4)

    def test_large_incoming_skip_preserves_existing_remainder(self):
        for sign in (-1, 1):
            records = [
                RefMarker(0, 1, skip=sign * 31.25, style=1),
                RefMarker(0.125, binary32(1e-4), skip=10000, style=1),
                RefMarker(0.25, 1, style=1),
            ]
            for precision, storage in PRECISIONS:
                with self.subTest(sign=sign, precision=precision, storage=storage):
                    _, vm = self.probe.run(
                        precision=precision,
                        entity_storage_precision=storage,
                        memory=timeline_memory(records),
                        group_ref=1,
                        now=0.375,
                        hit=0.5,
                        step=0,
                        count=1,
                    )
                    fields = TimescaleChange._data_fields_
                    offset = 3 * 32 + fields["scroll_skip"].offset
                    base = vm.get(PlayBlock.EntityDataArray, 3 * 32 + fields["scroll_skip_base"].offset)
                    total = (
                        base + vm.get(PlayBlock.EntityDataArray, offset) + vm.get(PlayBlock.EntityDataArray, offset + 1)
                    )
                    self.assertAlmostEqual(total, sign * 31.25 + 100_000_000, delta=1e-6)
