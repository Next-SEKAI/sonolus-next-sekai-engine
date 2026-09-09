from sonolus.script.archetype import PreviewArchetype, StandardImport, entity_data, imported
from sonolus.script.printing import PrintColor, PrintFormat, print_number
from sonolus.script.quad import Quad
from sonolus.script.runtime import HorizontalAlign
from sonolus.script.timing import beat_to_time
from sonolus.script.vec import Vec2

from sekai.lib import archetype_names
from sekai.lib.ease import EaseType
from sekai.lib.layer import get_z, layers
from sekai.lib.level_config import LevelConfig
from sekai.lib.skin import ActiveSkin
from sekai.lib.timescale import TransitionStyle
from sekai.preview.layout import (
    PREVIEW_BAR_EXTEND_W,
    PREVIEW_BAR_LINE_ALPHA,
    PREVIEW_DYNAMIC_BAR_EXTEND_W,
    PREVIEW_LANE_W,
    PREVIEW_TEXT_H,
    PREVIEW_TEXT_MARGIN_X,
    PREVIEW_TEXT_MARGIN_Y,
    PREVIEW_TEXT_W,
    PreviewData,
    PreviewLayout,
    lane_to_preview_x,
    layout_preview_bar_line,
    print_at_time,
    time_to_preview_col,
    time_to_preview_y,
)


def print_transition_ease(ease: EaseType, marker_time: float, dynamic: bool):
    """Print the numeric easing code below the speed at the same chronological marker."""
    col = time_to_preview_col(marker_time)
    if dynamic:
        anchor_x = (
            lane_to_preview_x(0, col)
            - PreviewLayout.column_width / 2
            + PREVIEW_LANE_W * 0.5
            + PREVIEW_DYNAMIC_BAR_EXTEND_W
            - PREVIEW_TEXT_MARGIN_X
        )
    else:
        anchor_x = lane_to_preview_x(-6, col) + PREVIEW_TEXT_MARGIN_X - PREVIEW_BAR_EXTEND_W
    print_number(
        value=ease,
        fmt=PrintFormat.NUMBER,
        decimal_places=0,
        anchor=Vec2(anchor_x, time_to_preview_y(marker_time, col) + PREVIEW_TEXT_MARGIN_Y),
        pivot=Vec2(1 if dynamic else 0, 1),
        dimensions=Vec2(PREVIEW_TEXT_W * 0.5, PREVIEW_TEXT_H * 0.5),
        color=PrintColor.NEUTRAL,
        horizontal_align=HorizontalAlign.RIGHT if dynamic else HorizontalAlign.LEFT,
        background=False,
    )


class PreviewTimescaleChange(PreviewArchetype):
    name = archetype_names.TIMESCALE_CHANGE

    beat: StandardImport.BEAT
    timescale: StandardImport.TIMESCALE
    timescale_skip: StandardImport.TIMESCALE_SKIP
    timescale_group: StandardImport.TIMESCALE_GROUP
    timescale_ease: EaseType = imported(name="#TIMESCALE_EASE", default=EaseType.NONE)
    transition_style: TransitionStyle = imported(name="transitionStyle", default=TransitionStyle.TIMESCALE)

    time: float = entity_data()

    def preprocess(self):
        self.time = beat_to_time(self.beat)

    def render(self):
        if self.timescale_group.index != PreviewData.min_timescale_group:
            return
        if (
            self.timescale == 1
            and self.beat <= 0
            and self.timescale_ease == EaseType.NONE
            and self.transition_style == TransitionStyle.TIMESCALE
            and self.timescale_skip == 0
        ):
            return
        dynamic = LevelConfig.dynamic_stages
        layout = +Quad
        if dynamic:
            layout @= layout_preview_bar_line(self.time, "left_dynamic")
        else:
            layout @= layout_preview_bar_line(self.time, "left")
        ActiveSkin.timescale_change_line.draw(
            layout,
            z=get_z(layers.timescale_line).tuple,
            a=PREVIEW_BAR_LINE_ALPHA,
        )
        print_at_time(
            self.timescale,
            self.time,
            fmt=PrintFormat.TIMESCALE,
            color=PrintColor.CYAN if self.transition_style == TransitionStyle.SCROLL else PrintColor.YELLOW,
            side="left",
            dynamic=dynamic,
        )
        print_transition_ease(self.timescale_ease, self.time, dynamic)


class PreviewTimescaleGroup(PreviewArchetype):
    name = archetype_names.TIMESCALE_GROUP

    def preprocess(self):
        if PreviewData.min_timescale_group == 0:
            PreviewData.min_timescale_group = self.index
        else:
            PreviewData.min_timescale_group = min(PreviewData.min_timescale_group, self.index)
