from math import pi

from sonolus.script.runtime import HorizontalAlign, aspect_ratio, runtime_ui, safe_area
from sonolus.script.ui import (
    EaseType,
    UiAnimation,
    UiAnimationTween,
    UiConfig,
    UiJudgmentErrorPlacement,
    UiJudgmentErrorStyle,
    UiMetric,
    UiVisibility,
)
from sonolus.script.vec import Vec2

from sekai.lib.layout import Layout, is_vertical
from sekai.lib.options import Options

# Degrees of in-place rotation applied to each runtime UI element in vertical mode (runtime rotation
# is in degrees; positive is counterclockwise). Matches the 90deg-CCW rotation of the gameplay.
VERTICAL_UI_ROTATION = 90.0

ui_config = UiConfig(
    scope="Sekai",
    primary_metric=UiMetric.ARCADE,
    secondary_metric=UiMetric.LIFE,
    menu_visibility=UiVisibility(scale=1, alpha=1),
    judgment_visibility=UiVisibility(scale=1, alpha=1),
    combo_visibility=UiVisibility(scale=1, alpha=1),
    progress_visibility=UiVisibility(scale=1, alpha=1),
    primary_metric_visibility=UiVisibility(scale=1, alpha=1),
    secondary_metric_visibility=UiVisibility(scale=1, alpha=1),
    tutorial_navigation_visibility=UiVisibility(scale=1, alpha=1),
    tutorial_instruction_visibility=UiVisibility(scale=1, alpha=1),
    judgment_animation=UiAnimation(
        scale=UiAnimationTween(
            start=0,
            end=1,
            duration=0.075,
            ease=EaseType.LINEAR,
        ),
        alpha=UiAnimationTween(
            start=1,
            end=0,
            duration=0.3,
            ease=EaseType.NONE,
        ),
    ),
    combo_animation=UiAnimation(
        scale=UiAnimationTween(
            start=0.6,
            end=1,
            duration=0.15,
            ease=EaseType.LINEAR,
        ),
        alpha=UiAnimationTween(
            start=1,
            end=1,
            duration=0,
            ease=EaseType.LINEAR,
        ),
    ),
    judgment_error_style=UiJudgmentErrorStyle.LATE,
    judgment_error_placement=UiJudgmentErrorPlacement.TOP,
    judgment_error_min=20,
)


def init_ui():
    ui = runtime_ui()

    gap = 0.05
    show_ui = not Options.hide_ui

    # In vertical mode the whole landscape presentation is rotated 90deg CCW to fill the portrait
    # screen. The UI is laid out in a virtual landscape frame (half-width 1, half-height = aspect)
    # and then mapped onto the portrait screen by rotating each anchor 90deg CCW about the center
    # while rotating each element in place. This puts the score/life on the portrait LEFT edge,
    # which reads as the top of the rotated view.
    vertical = is_vertical()
    if vertical:
        vhh = aspect_ratio()
        bl_x = -1.0 + gap
        br_x = 1.0 - gap
        bt_y = vhh - gap
        bb_y = -vhh + gap
    else:
        vhh = 1.0
        box = safe_area().shrink(Vec2(gap, gap))
        min_x_extent = min(box.r, -box.l)
        bl_x = -min_x_extent
        br_x = min_x_extent
        bt_y = box.t
        bb_y = box.b
    box_w = br_x - bl_x
    box_center_y = (bt_y + bb_y) / 2
    box_tl = Vec2(bl_x, bt_y)
    box_tr = Vec2(br_x, bt_y)
    box_bl = Vec2(bl_x, bb_y)

    # ui_angle maps anchor positions (radians, via Vec2.rotate); ui_rotation rotates the element
    # graphics (degrees, runtime convention). Both are the same 90deg-CCW turn in vertical mode.
    ui_angle = pi / 2 if vertical else 0.0
    ui_rotation = VERTICAL_UI_ROTATION if vertical else 0.0

    if vertical:
        # Combo centered in the middle, sitting directly on top of the judgment, which is nudged
        # down. Combo is 1/3 and judgment 1/2 of their landscape sizes.
        combo_x = 0.0
        combo_y = 0.0
        combo_h = 2 * vhh * 0.14 * 0.5  # 1/3 of landscape, then +50%
        judgment_y = 2 * vhh * -0.14
        judgment_h = 2 * vhh * 0.0475 * 0.6  # 1/2 of landscape, then +20%
    else:
        combo_x = Layout.field_w * 0.355
        combo_y = Layout.field_h * 0.0875
        combo_h = Layout.field_h * 0.14
        judgment_y = Layout.field_h * -0.115
        judgment_h = Layout.field_h * 0.0475

    ui.menu.update(
        anchor=box_tr.rotate(ui_angle),
        pivot=Vec2(1, 1),
        dimensions=Vec2(0.15, 0.15) * ui.menu_config.scale,
        rotation=ui_rotation,
        alpha=ui.menu_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.CENTER,
        background=True,
    )
    ui.primary_metric_bar.update(
        anchor=box_tl.rotate(ui_angle),
        pivot=Vec2(0, 1),
        dimensions=Vec2(0.75, 0.15) * ui.primary_metric_config.scale,
        rotation=ui_rotation,
        alpha=ui.primary_metric_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.LEFT,
        background=True,
    )
    ui.primary_metric_value.update(
        anchor=(box_tl + Vec2(0.715, -0.035) * ui.primary_metric_config.scale).rotate(ui_angle),
        pivot=Vec2(1, 1),
        dimensions=Vec2(0, 0.08) * ui.primary_metric_config.scale,
        rotation=ui_rotation,
        alpha=ui.primary_metric_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.RIGHT,
        background=False,
    )
    ui.secondary_metric_bar.update(
        anchor=(box_tr - Vec2(gap, 0) - Vec2(0.15, 0) * ui.menu_config.scale).rotate(ui_angle),
        pivot=Vec2(1, 1),
        dimensions=Vec2(0.55, 0.15) * ui.secondary_metric_config.scale,
        rotation=ui_rotation,
        alpha=ui.secondary_metric_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.LEFT,
        background=True,
    )
    ui.secondary_metric_value.update(
        anchor=(
            box_tr
            - Vec2(gap, 0)
            - Vec2(0.15, 0) * ui.menu_config.scale
            - Vec2(0.035, 0.035) * ui.secondary_metric_config.scale
        ).rotate(ui_angle),
        pivot=Vec2(1, 1),
        dimensions=Vec2(0, 0.08) * ui.secondary_metric_config.scale,
        rotation=ui_rotation,
        alpha=ui.secondary_metric_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.RIGHT,
        background=False,
    )
    ui.combo_value.update(
        anchor=Vec2(combo_x, combo_y).rotate(ui_angle),
        pivot=Vec2(0.5, 0.5),
        dimensions=Vec2(0, combo_h) * ui.combo_config.scale,
        rotation=ui_rotation,
        alpha=ui.combo_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.CENTER,
        background=False,
    )
    ui.combo_text.update(
        anchor=Vec2(combo_x, combo_y).rotate(ui_angle),
        pivot=Vec2(0.5, -2.25),
        dimensions=Vec2(0, combo_h * 0.25) * ui.combo_config.scale,
        rotation=ui_rotation,
        alpha=ui.combo_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.CENTER,
        background=False,
    )
    ui.judgment.update(
        anchor=Vec2(0, judgment_y).rotate(ui_angle),
        pivot=Vec2(0.5, 0.5),
        dimensions=Vec2(0, judgment_h) * ui.judgment_config.scale,
        rotation=ui_rotation,
        alpha=ui.judgment_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.CENTER,
        background=False,
    )
    ui.progress.update(
        anchor=box_bl.rotate(ui_angle),
        pivot=Vec2(0, 0),
        dimensions=Vec2(box_w, 0.15 * ui.progress_config.scale),
        rotation=ui_rotation,
        alpha=ui.progress_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.CENTER,
        background=True,
    )
    ui.progress_graph.update(
        anchor=(box_bl + Vec2(0, gap + 0.15 * ui.progress_config.scale)).rotate(ui_angle),
        pivot=Vec2(0, 0),
        dimensions=Vec2(box_w, 0.3 * ui.progress_config.scale),
        rotation=ui_rotation,
        alpha=ui.progress_config.alpha * show_ui,
        horizontal_align=HorizontalAlign.CENTER,
        background=True,
    )
    ui.previous.update(
        anchor=Vec2(bl_x, box_center_y),
        pivot=Vec2(0, 0.5),
        dimensions=Vec2(0.15, 0.15) * ui.navigation_config.scale,
        alpha=ui.navigation_config.alpha,
        background=True,
    )
    ui.next.update(
        anchor=Vec2(br_x, box_center_y),
        pivot=Vec2(1, 0.5),
        dimensions=Vec2(0.15, 0.15) * ui.navigation_config.scale,
        alpha=ui.navigation_config.alpha,
        background=True,
    )
    ui.instruction.update(
        anchor=Vec2(0, 0.4),
        pivot=Vec2(0.5, 0.5),
        dimensions=Vec2(1.2, 0.15) * ui.instruction_config.scale,
        alpha=ui.instruction_config.alpha,
        background=True,
    )
