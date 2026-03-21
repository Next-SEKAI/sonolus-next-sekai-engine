from sonolus.script.archetype import WatchArchetype, callback, entity_memory
from sonolus.script.runtime import is_skip

from sekai.lib import archetype_names
from sekai.lib.layout import refresh_layout
from sekai.lib.stage import draw_stage_and_accessories, play_lane_particle


class WatchStage(WatchArchetype):
    name = archetype_names.STAGE

    def spawn_time(self) -> float:
        return -1e8

    def despawn_time(self) -> float:
        return 1e8

    @callback(order=-2)
    def update_sequential(self):
        refresh_layout()

    def update_parallel(self):
        draw_stage_and_accessories()


class WatchScheduledLaneEffect(WatchArchetype):
    name = archetype_names.SCHEDULED_LANE_EFFECT

    lane: float = entity_memory()
    target_time: float = entity_memory()

    def spawn_time(self) -> float:
        return self.target_time

    def despawn_time(self) -> float:
        return self.target_time + 1

    def initialize(self):
        if is_skip():
            return
        play_lane_particle(self.lane)
