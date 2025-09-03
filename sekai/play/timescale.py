from __future__ import annotations

from sonolus.script.archetype import (
    EntityRef,
    PlayArchetype,
    StandardImport,
    callback,
    imported,
    shared_memory,
)
from sonolus.script.runtime import time

from sekai.lib import archetype_names
from sekai.lib.timescale import (
    ScaledTimeToFirstTime,
    TimeToScaledTime,
)


class TimescaleChange(PlayArchetype):
    name = archetype_names.TIMESCALE_CHANGE

    beat: StandardImport.BEAT
    timescale: StandardImport.TIMESCALE
    timescale_skip: StandardImport.TIMESCALE_SKIP
    timescale_group: StandardImport.TIMESCALE_GROUP
    timescale_ease: StandardImport.TIMESCALE_EASE
    next_ref: EntityRef[TimescaleChange] = imported(name="next")

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False


class TimescaleGroup(PlayArchetype):
    name = archetype_names.TIMESCALE_GROUP

    first_ref: EntityRef[TimescaleChange] = imported(name="first")

    current_scaled_time: float = shared_memory()

    time_to_scaled_time: TimeToScaledTime = shared_memory()
    scaled_time_to_first_time: ScaledTimeToFirstTime = shared_memory()
    scaled_time_to_first_time_2: ScaledTimeToFirstTime = shared_memory()

    def spawn_order(self) -> float:
        return -1e8

    def should_spawn(self) -> bool:
        return True

    @callback(order=-2)
    def preprocess(self):
        self.time_to_scaled_time.init(self.first_ref.index)
        self.scaled_time_to_first_time.init(self.first_ref.index)
        self.scaled_time_to_first_time_2.init(self.first_ref.index)

    @callback(order=-2)
    def update_sequential(self):
        self.current_scaled_time = self.time_to_scaled_time.get(time())
