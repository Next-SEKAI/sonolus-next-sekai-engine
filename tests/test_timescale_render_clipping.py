# ruff: noqa: PT009
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sonolus.script.archetype import PlayArchetype, entity_data, imported
from sonolus.script.sprite import Sprite
from sonolus.script.vec import Vec2

from sekai.lib import connector, sim_line
from sekai.lib.ease import EaseType
from sekai.lib.layer import ZIndexes
from sekai.lib.layout import StageScreenTransform
from sekai.lib.timescale_math import AccurateScalar
from tests.timescale_vm import compile_probe


class ProgressClippingProbe(PlayArchetype):
    head: float = imported()
    tail: float = imported()
    exponent: int = imported()
    radius: float = imported()
    lower: float = imported()
    upper: float = imported()
    start: float = entity_data()
    end: float = entity_data()
    first: float = entity_data()
    last: float = entity_data()

    def preprocess(self):
        self.start, self.end, self.first, self.last = connector.clip_progress_segment(
            AccurateScalar(self.head, 0.0, self.exponent, self.radius),
            AccurateScalar(self.tail, 0.0, self.exponent, self.radius),
            self.lower,
            self.upper,
        )


class TimescaleRenderClippingTests(unittest.TestCase):
    def test_compiled_huge_endpoint_clipping_in_binary32(self):
        probe = compile_probe(ProgressClippingProbe)
        result, _ = probe.run(precision="binary32", head=-0.75, tail=0.25, exponent=10000, lower=-2, upper=4)
        self.assertEqual(result, {"start": (-2.0,), "end": (4.0,), "first": (0.75,), "last": (0.75,)})

    def test_unclipped_overlapping_certificates_keep_exact_identity_fractions(self):
        head = AccurateScalar(1.0, 0.0, 0, 1e-5)
        tail = AccurateScalar(1.000002, 0.0, 0, 1e-5)
        self.assertEqual(connector.clip_progress_segment(head, tail, -3, 6), (1.0, 1.000002, 0.0, 1.0))

    def test_clipped_overlapping_certificates_interpolate_represented_centers(self):
        head = AccurateScalar(0.999998, 0.0, 0, 1e-5)
        tail = AccurateScalar(1.000002, 0.0, 0, 1e-5)
        start, end, first, last = connector.clip_progress_segment(head, tail, 1, 2)
        self.assertEqual((start, end, last), (1.0, 1.000002, 1.0))
        self.assertAlmostEqual(first, 0.5)
        start, end, first, last = connector.clip_progress_segment(tail, head, 1, 2)
        self.assertEqual((start, end, first), (1.000002, 1.0, 0.0))
        self.assertAlmostEqual(last, 0.5)

    def test_compiled_clipping_accepts_overlapping_endpoint_certificates(self):
        probe = compile_probe(ProgressClippingProbe)
        for lower, upper, expected_first in ((-3, 6, 0.0), (1, 2, 0.5)):
            result, _ = probe.run(
                precision="binary32",
                head=0.999998,
                tail=1.000002,
                exponent=0,
                radius=1e-5,
                lower=lower,
                upper=upper,
            )
            self.assertEqual(result["first"], (expected_first,))
            self.assertEqual(result["last"], (1.0,))

    def test_huge_opposite_endpoints_preserve_original_fraction_and_visible_span(self):
        head = AccurateScalar(-0.75, 0.0, 10000, 0.0)
        tail = AccurateScalar(0.25, 0.0, 10000, 0.0)
        start, end, first, last = connector.clip_progress_segment(head, tail, -2, 4)
        self.assertEqual((start, end), (-2, 4))
        self.assertAlmostEqual(first, 0.75)
        self.assertAlmostEqual(last, 0.75)
        self.assertFalse(connector.progress_segment_is_outside(head, tail, -2, 4))

    def test_reversed_huge_endpoints_preserve_orientation(self):
        head = AccurateScalar(0.25, 0.0, 10000, 0.0)
        tail = AccurateScalar(-0.75, 0.0, 10000, 0.0)
        self.assertEqual(connector.clip_progress_segment(head, tail, -2, 4), (4, -2, 0.25, 0.25))

    def test_same_side_huge_endpoints_can_be_rejected_without_materializing(self):
        for sign in (-1, 1):
            head = AccurateScalar(sign * 0.5, 0.0, 10000, 0.0)
            tail = AccurateScalar(sign * 0.75, 0.0, 9999, 0.0)
            self.assertTrue(connector.progress_segment_is_outside(head, tail, -2, 4))

    def test_ordinary_clipping_matches_float_path(self):
        for head, tail in ((-10.0, 6.0), (2.0, -3.0), (0.5, 0.5), (0.0, 1e-8)):
            expected = connector.clip_progress_segment(head, tail, -2, 4)
            actual = connector.clip_progress_segment(AccurateScalar.of(head), AccurateScalar.of(tail), -2, 4)
            for value, reference in zip(actual, expected, strict=True):
                self.assertAlmostEqual(value, reference)

    def test_huge_connector_draw_keeps_easing_and_full_visible_progress_span(self):
        self.enterContext(
            patch.object(connector, "DynamicLayout", SimpleNamespace(progress_start=-2, progress_cutoff=4, w_scale=1))
        )
        self.enterContext(patch.object(connector, "approach", side_effect=lambda progress: progress))
        self.enterContext(
            patch.object(connector, "pre_rotation_vec_at", side_effect=lambda lane, travel: Vec2(lane, travel))
        )
        self.enterContext(patch.object(connector, "connector_is_off_screen", return_value=False))
        self.enterContext(patch.object(connector, "get_connector_alpha_option", return_value=1))
        self.enterContext(patch.object(connector, "get_connector_quality_option", return_value=1))
        self.enterContext(patch.object(connector, "get_alpha", return_value=1))
        draw = self.enterContext(patch.object(connector, "draw_connector_default_segment"))
        connector.draw_connector_default(
            kind=connector.ConnectorKind.GUIDE_RED,
            visual_state=connector.ConnectorVisualState.WAITING,
            ease_type=EaseType.IN_QUAD,
            normal_sprite=Sprite(1),
            active_sprite=Sprite(-1),
            z_normal=ZIndexes(0, 0, 0, 0),
            z_active=ZIndexes(0, 0, 0, 0),
            head_lane=0,
            head_size=1,
            head_visual_progress=AccurateScalar(-0.75, 0.0, 10000, 0.0),
            head_target_time=0,
            head_ease_frac=0,
            head_alpha=0.2,
            tail_lane=8,
            tail_size=2,
            tail_visual_progress=AccurateScalar(0.25, 0.0, 10000, 0.0),
            tail_target_time=4,
            tail_ease_frac=1,
            tail_alpha=0.8,
        )
        draw.assert_called_once()
        segment = draw.call_args.kwargs
        self.assertEqual((segment["start_travel"], segment["end_travel"]), (-2, 4))
        self.assertAlmostEqual(segment["start_lane"], 4.5)
        self.assertAlmostEqual(segment["end_lane"], 4.5)
        self.assertAlmostEqual(segment["start_size"], 1.5625)
        self.assertAlmostEqual(segment["start_interp_frac"], 0.5625)
        self.assertAlmostEqual(segment["base_a"], 0.65)

    def test_huge_sim_line_uses_existing_zero_opacity_rule_before_conversion(self):
        self.enterContext(patch.object(sim_line, "Options", SimpleNamespace(sim_line_enabled=True)))
        self.enterContext(
            patch.object(sim_line, "DynamicLayout", SimpleNamespace(progress_start=-2, progress_cutoff=4))
        )
        draw = self.enterContext(patch.object(sim_line, "layout_sim_line"))
        sim_line.draw_sim_line(
            -2,
            AccurateScalar(-0.75, 0.0, 10000, 0.0),
            0,
            2,
            AccurateScalar(0.25, 0.0, 10000, 0.0),
            1,
            +StageScreenTransform,
            +StageScreenTransform,
            1,
            1,
        )
        draw.assert_not_called()


if __name__ == "__main__":
    unittest.main()
