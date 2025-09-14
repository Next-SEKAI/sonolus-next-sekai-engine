from sonolus.script.archetype import PreviewArchetype, StandardImport, entity_data, imported
from sonolus.script.printing import PrintColor, PrintFormat
from sonolus.script.timing import beat_to_time

from sekai.lib import archetype_names
from sekai.lib.layer import LAYER_BPM_LINE, get_z
from sekai.lib.skin import Skin
from sekai.preview.layout import layout_preview_bar_line, print_at_time


class PreviewBpmChange(PreviewArchetype):
    name = archetype_names.BPM_CHANGE

    beat: StandardImport.BEAT = imported()
    bpm: StandardImport.BPM = imported()

    time: float = entity_data()

    def preprocess(self):
        self.time = beat_to_time(self.beat)

    def render(self):
        Skin.bpm_change_line.draw(
            layout_preview_bar_line(self.time, "right"),
            z=get_z(LAYER_BPM_LINE),
            a=0.8,
        )
        print_at_time(
            self.bpm,
            self.time,
            fmt=PrintFormat.BPM,
            color=PrintColor.PURPLE,
            side="right",
        )
