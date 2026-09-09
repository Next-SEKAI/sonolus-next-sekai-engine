# ruff: noqa: PT009
"""Check immutable run blocks and compiled queries against the Decimal oracle."""

import unittest

from sekai.lib.timescale import DISTANCE_LIMIT
from sekai.play.timescale import TimescaleChange, TimescaleGroup
from tests.test_timescale_compiled import PRECISIONS, TimelineProbe, timeline_memory
from tests.test_timescale_timeline import TimelineFixture
from tests.timescale_reference import RefMarker, RefTimeline
from tests.timescale_vm import binary32, compile_probe


class RangeIndexTests(unittest.TestCase):
    def test_block_spans_match_run_ordinals(self):
        records = [RefMarker(i / 11, 1 + i % 2, style=i % 2) for i in range(600)]
        with TimelineFixture(records) as fixture:
            for ordinal, marker in fixture.markers.items():
                width = ordinal & -ordinal
                self.assertEqual(marker.jump_width, min(width, len(records) - ordinal))
                self.assertEqual(marker.jump_end, ordinal + marker.jump_width if marker.jump_width else 0)

    def test_native_indexed_queries_and_same_time_ratios(self):
        probe = compile_probe(TimelineProbe, archetypes=[TimelineProbe, TimescaleGroup, TimescaleChange])
        queries = [(now, hit, 0, 1) for now, hit in [(1, 2), (1, 4), (1, 7), (7, 1), (-0.1, 0.9), (0.9, -0.1)]]
        speeds = (0.05, 0.25, 8, 1, 0.5, 4)
        cases = [
            (
                [RefMarker(binary32(i / 11), binary32(1 + i % 2 * 0.1), ease=i % 6, style=i % 2) for i in range(120)],
                queries,
            ),
            (
                [RefMarker(0, binary32(1 if i % 2 == 0 else 7.8), style=(i // 2) % 2) for i in range(101)]
                + [RefMarker(1, 1)],
                queries,
            ),
            (
                # Three markers per run, with tied boundaries late in the chart.
                [RefMarker(0, 1)]
                + [
                    RefMarker(
                        1790 + (i // 7 * 6 + min(i % 7, 5)) / 16,
                        binary32(speeds[i % 6]),
                        ease=i % 6,
                        style=(i // 3) % 2,
                    )
                    for i in range(120)
                ],
                [
                    (1790.03125, 1795.34375, 0, 1),
                    (1795.34375, 1790.03125, 0, 1),
                    (1793.03125, 1794.34375, 0.0625, 35),
                    (1795.34375, 1793.03125, -0.0625, 35),
                    (1794.96875, 1795.03125, 0, 1),
                    (1795.03125, 1794.96875, 0, 1),
                    (1791.125, 1795.5, 0, 1),
                    (1795.5, 1791.125, 0, 1),
                ],
            ),
        ]
        for records, queries in cases:
            oracle = RefTimeline(records)
            for precision, storage in PRECISIONS:
                for now, hit, step, count in queries:
                    with self.subTest(model=(precision, storage), now=now, hit=hit):
                        result, _ = probe.run(
                            precision=precision,
                            entity_storage_precision=storage,
                            memory=timeline_memory(records),
                            group_ref=1,
                            now=now,
                            hit=hit,
                            step=step,
                            count=count,
                            instruction_limit=5_000_000,
                        )
                        expected = max(
                            -DISTANCE_LIMIT, min(DISTANCE_LIMIT, float(oracle.distance(now + step * (count - 1), hit)))
                        )
                        self.assertAlmostEqual(result["distance"][0], expected, delta=2e-5 * max(1, abs(expected)))
