from sonolus.script.archetype import EntityRef, WatchArchetype, callback, entity_memory
from sonolus.script.runtime import is_skip

from sekai.lib import archetype_names
from sekai.lib.layout import IDENTITY_STAGE_SCREEN_TRANSFORM, refresh_layout
from sekai.lib.stage import draw_stage_and_accessories, get_stage_props, play_lane_particle
from sekai.watch.dynamic_stage import WatchDynamicStage


class WatchStaticStage(WatchArchetype):
    name = archetype_names.STATIC_STAGE

    def spawn_time(self) -> float:
        return -1e8

    def despawn_time(self) -> float:
        return 1e8

    @callback(order=-3)
    def update_sequential(self):
        refresh_layout()

    def update_parallel(self):
        draw_stage_and_accessories()


class WatchScheduledLaneEffect(WatchArchetype):
    name = archetype_names.SCHEDULED_LANE_EFFECT

    lane: float = entity_memory()
    target_time: float = entity_memory()
    stage_ref: EntityRef[WatchDynamicStage] = entity_memory()
    played: bool = entity_memory()

    def spawn_time(self) -> float:
        return self.target_time

    def despawn_time(self) -> float:
        return self.target_time + 1

    def update_parallel(self):
        if self.played:
            return
        self.played = True
        if is_skip():
            return
        transform = +IDENTITY_STAGE_SCREEN_TRANSFORM
        if self.stage_ref.index > 0:
            props = get_stage_props(self.stage_ref.get(), self.target_time)
            transform @= props.stage_transform().to_screen_transform()
        play_lane_particle(self.lane, transform)
