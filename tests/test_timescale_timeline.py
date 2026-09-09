# ruff: noqa: PT009
"""Exercise production indexes against a separate chronological Decimal oracle."""

import random
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sekai.lib import timescale as ts
from sekai.lib.timescale_math import AccurateScalar, AffineTransfer
from tests.timescale_reference import RefMarker, RefTimeline


class TimelineFixture:
    def __init__(self, records, validate_oracle=True):
        self.oracle: Any = RefTimeline(records) if validate_oracle else None
        self.markers = {}
        self.group: Any = SimpleNamespace(
            index=100000, first_ref=SimpleNamespace(index=1 if records else 0), force_note_speed=0, valid=False
        )
        for i, record in enumerate(records, 1):
            self.markers[i] = SimpleNamespace(
                index=i,
                beat=float(record.time),
                timescale=float(record.speed),
                timescale_skip=float(record.skip),
                timescale_ease=int(record.ease),
                transition_style=int(record.style),
                hide_notes=record.hide,
                next_ref=SimpleNamespace(index=i + 1 if i < len(records) else 0),
                timescale_group=SimpleNamespace(index=100000),
                validation_owner=0,
                aggregate=AffineTransfer.identity(),
                run_prefix=AccurateScalar.of(0),
                run_suffix=AccurateScalar.of(0),
            )

    def __enter__(self):
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(ts, "_marker", side_effect=self.markers.__getitem__))
        self.stack.enter_context(patch.object(ts, "_valid_marker_ref", side_effect=lambda r: r in self.markers))
        self.stack.enter_context(
            patch.object(ts, "timescale_group_archetype", return_value=SimpleNamespace(at=lambda _: self.group))
        )
        self.stack.enter_context(patch.object(ts, "Options", SimpleNamespace(disable_timescale=False)))
        self.stack.enter_context(patch.object(ts, "beat_to_time", side_effect=lambda x: x))
        self.stack.enter_context(patch.object(ts, "beat_to_bpm", return_value=60))
        self.stack.enter_context(patch.object(ts, "preempt_time", return_value=.0035))
        ts.initialize_timescale_group(self.group)
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


class TimescaleTimelineTests(unittest.TestCase):
    def assert_distance(self, fixture, a, b):
        actual = ts.distance_between(100000, a, b).to_float()
        expected = float(fixture.oracle.distance(a, b))
        self.assertAlmostEqual(actual, expected, delta=max(1e-9, abs(expected) * 1e-11))

    def test_atomic_ties_and_prelude_skip(self):
        records = [RefMarker(0, 1), RefMarker(1, 2, style=1), RefMarker(1, 1), RefMarker(2, 3)]
        with TimelineFixture(records) as fixture:
            self.assertTrue(fixture.group.valid)
            self.assertEqual(ts.locate_time(100000, 1), 3)
            for a in [-3, -1, 0, 0.5, 1, 1.2, 2, 3]:
                for b in [-2, 0, 0.75, 1, 2, 4]:
                    self.assert_distance(fixture, a, b)
        with TimelineFixture([RefMarker(-4, -1, skip=3), RefMarker(-1, 0, skip=-2)]) as fixture:
            for a, b in [(-5, -4), (-5, 0), (-2, 0), (0, -5)]:
                self.assert_distance(fixture, a, b)

    def test_random_ranges_all_eases_and_styles(self):
        rng = random.Random(37)
        records = [RefMarker(i / 4, rng.uniform(0.05, 8), ease=i % 6, style=rng.randrange(2)) for i in range(70)]
        with TimelineFixture(records) as fixture:
            for _ in range(150):
                self.assert_distance(fixture, rng.uniform(-3, 20), rng.uniform(-3, 20))
            for first in range(1, 68, 7):
                for last in range(first, 70, 9):
                    actual = ts._range_transfer(fixture.group, first, last)
                    expected = fixture.oracle.anchor_transfer(first - 1, last)
                    self.assertAlmostEqual(
                        actual.ratio.to_float(), float(expected[0]), delta=abs(float(expected[0])) * 1e-11
                    )
                    self.assertAlmostEqual(
                        actual.distance.to_float(), float(expected[1]), delta=max(1e-9, abs(float(expected[1])) * 1e-11)
                    )

    def test_balanced_tree_bounds_and_parents(self):
        for count in [1, 2, 3, 4, 7, 8, 31, 64, 1000]:
            with TimelineFixture([RefMarker(i, 1) for i in range(count)]) as fixture:
                pending = [(fixture.group.root, 0, 1)]
                visited = set()
                while pending:
                    ref, parent, depth = pending.pop()
                    node = fixture.markers[ref]
                    self.assertEqual(node.tree_parent, parent)
                    self.assertLessEqual(depth, count.bit_length())
                    self.assertNotIn(ref, visited)
                    visited.add(ref)
                    pending.extend((child, ref, depth + 1) for child in (node.tree_left, node.tree_right) if child)
                self.assertEqual(len(visited), count)

    def test_hybrid_validation_and_cycle(self):
        for records in [[RefMarker(0, 0, style=1)], [RefMarker(0, 1, skip=1), RefMarker(1, 1, style=1)]]:
            with TimelineFixture(records, validate_oracle=False) as fixture:
                self.assertFalse(fixture.group.used)
                self.assertFalse(fixture.group.valid)
                self.assertEqual(fixture.group.error_code, ts.TimelineError.HYBRID)
        fixture = TimelineFixture([RefMarker(0, 1), RefMarker(1, 2)])
        fixture.markers[2].next_ref.index = 1
        with fixture:
            self.assertFalse(fixture.group.valid)
            self.assertEqual(fixture.group.error_code, ts.TimelineError.CYCLE)

    def test_empty_identity(self):
        with TimelineFixture([]) as fixture:
            self.assertTrue(fixture.group.valid)
            self.assertEqual(ts.locate_target(100000, 3).event_ref, 0)
            self.assertEqual(ts.distance_between(100000, -2, 3).to_float(), 5)

    def test_positive_subtree_envelopes_keep_nonzero_lower_bound(self):
        with TimelineFixture([RefMarker(i, 1) for i in range(32)]) as fixture:
            root = fixture.markers[fixture.group.root]
            # A final SCROLL annotation changes group classification, even though
            # its outgoing interval is an analytic held tail.
            self.assertEqual(fixture.group.mode, 0)
        records = [RefMarker(i, 1, style=1 if i == 31 else 0) for i in range(32)]
        with TimelineFixture(records) as fixture:
            root = fixture.markers[fixture.group.root]
            self.assertGreater(root.suffix_r_min.to_float(), 0.99)
            self.assertLess(root.suffix_r_max.to_float(), 1.01)
            self.assertGreaterEqual(root.suffix_b_max.to_float(), 31)
            self.assertLess(root.suffix_b_max.to_float(), 31.01)


if __name__ == "__main__":
    unittest.main()
