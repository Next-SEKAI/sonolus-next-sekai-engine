from sonolus.script.interval import clamp, lerp, unlerp, unlerp_clamped

from sekai.lib.connector import progress_segment_is_outside
from sekai.lib.layer import get_z, layers
from sekai.lib.layout import DynamicLayout, StageScreenTransform, approach, get_alpha, layout_sim_line
from sekai.lib.options import Options
from sekai.lib.skin import ActiveSkin
from sekai.lib.timescale_math import AccurateScalar


def draw_sim_line(
    left_lane: float,
    left_visual_progress: float | AccurateScalar,
    left_target_time: float,
    right_lane: float,
    right_visual_progress: float | AccurateScalar,
    right_target_time: float,
    left_transform: StageScreenTransform,
    right_transform: StageScreenTransform,
    left_note_alpha: float,
    right_note_alpha: float,
):
    if not Options.sim_line_enabled:
        return

    if progress_segment_is_outside(
        left_visual_progress, right_visual_progress, DynamicLayout.progress_start, DynamicLayout.progress_cutoff
    ):
        return

    if isinstance(left_visual_progress, AccurateScalar) or isinstance(right_visual_progress, AccurateScalar):
        left_value = AccurateScalar.of(0.0)
        right_value = AccurateScalar.of(0.0)
        if isinstance(left_visual_progress, AccurateScalar):
            left_value @= left_visual_progress
        else:
            left_value @= AccurateScalar.of(left_visual_progress)
        if isinstance(right_visual_progress, AccurateScalar):
            right_value @= right_visual_progress
        else:
            right_value @= AccurateScalar.of(right_visual_progress)
        difference = left_value.sub(right_value)
        # Existing SimLine opacity is exactly zero for a progress separation of
        # at least one. Classify that before converting either huge endpoint.
        if difference.compare(AccurateScalar.of(1.0)) >= 0 or difference.compare(AccurateScalar.of(-1.0)) <= 0:
            return
        left_progress = left_value.to_float()
        right_progress = right_value.to_float()
    else:
        left_progress = left_visual_progress
        right_progress = right_visual_progress

    if (left_progress < 1 < right_progress) or (left_progress > 1 > right_progress):
        return

    adj_left_progress = clamp(left_progress, DynamicLayout.progress_start, DynamicLayout.progress_cutoff)
    adj_right_progress = clamp(right_progress, DynamicLayout.progress_start, DynamicLayout.progress_cutoff)
    if abs(left_progress - right_progress) > 1e-6:
        adj_left_frac = unlerp(left_progress, right_progress, adj_left_progress)
        adj_right_frac = unlerp(left_progress, right_progress, adj_right_progress)
        adj_left_lane = lerp(left_lane, right_lane, adj_left_frac)
        adj_right_lane = lerp(left_lane, right_lane, adj_right_frac)
    else:
        adj_left_lane = left_lane
        adj_right_lane = right_lane
    adj_left_travel = approach(adj_left_progress)
    adj_right_travel = approach(adj_right_progress)
    layout = layout_sim_line(
        adj_left_lane,
        adj_left_travel,
        adj_right_lane,
        adj_right_travel,
        left_transform,
        right_transform,
    )
    progress_diff = abs(left_progress - right_progress)
    fade_alpha = unlerp_clamped(1, 0.5, progress_diff)
    z = get_z(
        layers.sim_line,
        (left_target_time + right_target_time) / 2,
        (left_lane + right_lane) / 2,
        # Keep the line below both endpoint notes.
        elevation=min(left_transform.elevation, right_transform.elevation),
    )
    a = (
        min(
            get_alpha(left_target_time) * left_note_alpha,
            get_alpha(right_target_time) * right_note_alpha,
            1.0,
        )
        * fade_alpha
    )
    if a <= 0:
        return
    ActiveSkin.sim_line.draw(layout, z=z.tuple, a=a)
