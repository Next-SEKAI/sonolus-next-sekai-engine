from sonolus.script.archetype import PreviewArchetype, StandardImport, entity_data
from sonolus.script.printing import PrintColor, PrintFormat
from sonolus.script.timing import beat_to_time

from sekai.lib import archetype_names
from sekai.lib.layer import LAYER_TIMESCALE_LINE, get_z
from sekai.lib.skin import Skin
from sekai.preview.layout import PREVIEW_BAR_LINE_ALPHA, PreviewData, layout_preview_bar_line, print_at_time


class PreviewTimescaleChange(PreviewArchetype):
    name = archetype_names.TIMESCALE_CHANGE

    beat: StandardImport.BEAT
    timescale: StandardImport.TIMESCALE
    timescale_skip: StandardImport.TIMESCALE_SKIP
    timescale_group: StandardImport.TIMESCALE_GROUP
    timescale_ease: StandardImport.TIMESCALE_EASE

    time: float = entity_data()

    def preprocess(self):
        self.time = beat_to_time(self.beat)

    def render(self):
        if self.timescale_group.index != PreviewData.min_timescale_group:
            return
        if self.timescale == 1 and self.beat <= 0:
            return
        Skin.timescale_change_line.draw(
            layout_preview_bar_line(self.time, "left"),
            z=get_z(LAYER_TIMESCALE_LINE),
            a=PREVIEW_BAR_LINE_ALPHA,
        )
        print_at_time(
            self.timescale,
            self.time,
            fmt=PrintFormat.TIMESCALE,
            color=PrintColor.YELLOW,
            side="left",
        )


class PreviewTimescaleGroup(PreviewArchetype):
    name = archetype_names.TIMESCALE_GROUP

    def preprocess(self):
        if PreviewData.min_timescale_group == 0:
            PreviewData.min_timescale_group = self.index
        else:
            PreviewData.min_timescale_group = min(PreviewData.min_timescale_group, self.index)
