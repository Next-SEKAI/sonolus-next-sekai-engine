from math import inf

from sonolus.script.archetype import EntityRef, WatchArchetype, callback, entity_data, entity_memory, imported
from sonolus.script.runtime import time

from sekai.debug import DISABLE_NOTES
from sekai.lib import archetype_names
from sekai.lib.sim_line import draw_sim_line
from sekai.lib.timescale import TrajectoryCache, group_hide_notes
from sekai.lib.timescale_consumer import (
    note_visual_progress,
    prepare_note_trajectories,
    register_note_group_window,
    segment_visual_spawn_time,
)
from sekai.watch.note import WatchBaseNote


class WatchSimLine(WatchArchetype):
    name = archetype_names.SIM_LINE

    left_ref: EntityRef[WatchBaseNote] = imported(name="left")
    right_ref: EntityRef[WatchBaseNote] = imported(name="right")

    left_trajectory_first: TrajectoryCache = entity_memory()
    left_trajectory_second: TrajectoryCache = entity_memory()
    right_trajectory_first: TrajectoryCache = entity_memory()
    right_trajectory_second: TrajectoryCache = entity_memory()

    start_time: float = entity_data()
    end_time: float = entity_data()

    @callback(order=1)
    def preprocess(self):
        self.start_time = inf
        if DISABLE_NOTES:
            return
        if not self.left.preprocess_done or not self.right.preprocess_done:
            return
        start_time = min(
            self.left.start_time,
            self.right.start_time,
            segment_visual_spawn_time(self.left, self.right, min(self.left.target_time, self.right.target_time)),
        )
        if start_time == inf:
            return
        self.end_time = min(self.left.despawn_time(), self.right.despawn_time(), self.left.target_time)
        self.left.extend_stage_windows(start_time - 1.0, self.end_time + 1.0)
        self.right.extend_stage_windows(start_time - 1.0, self.end_time + 1.0)

        register_note_group_window(self.left, start_time, self.end_time)
        register_note_group_window(self.right, start_time, self.end_time)
        self.start_time = start_time

    def spawn_time(self) -> float:
        if DISABLE_NOTES:
            return 1e8
        return self.start_time

    def despawn_time(self) -> float:
        return self.end_time

    def update_sequential(self):
        prepare_note_trajectories(self.left, self.left_trajectory_first, self.left_trajectory_second, time())
        prepare_note_trajectories(self.right, self.right_trajectory_first, self.right_trajectory_second, time())

    def update_parallel(self):
        if group_hide_notes(self.left.timescale_group) or group_hide_notes(self.right.timescale_group):
            return
        left_lane, left_size = self.left.visual_extents
        right_lane, right_size = self.right.visual_extents
        if left_size <= 0 or right_size <= 0:
            return
        draw_sim_line(
            left_lane=left_lane,
            left_visual_progress=note_visual_progress(
                self.left, self.left_trajectory_first, self.left_trajectory_second, time()
            ),
            left_target_time=self.left.target_time,
            right_lane=right_lane,
            right_visual_progress=note_visual_progress(
                self.right, self.right_trajectory_first, self.right_trajectory_second, time()
            ),
            right_target_time=self.right.target_time,
            left_transform=self.left.visual_stage_transform().to_screen_transform(),
            right_transform=self.right.visual_stage_transform().to_screen_transform(),
            left_note_alpha=self.left.visual_note_alpha,
            right_note_alpha=self.right.visual_note_alpha,
        )

    @property
    def left(self) -> WatchBaseNote:
        return self.left_ref.get()

    @property
    def right(self) -> WatchBaseNote:
        return self.right_ref.get()
