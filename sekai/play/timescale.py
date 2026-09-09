from __future__ import annotations

from sonolus.script.archetype import (
    EntityRef,
    PlayArchetype,
    StandardImport,
    callback,
    entity_data,
    imported,
    shared_memory,
)
from sonolus.script.runtime import time

from sekai.lib import archetype_names
from sekai.lib.ease import EaseType
from sekai.lib.timescale import TimelineError, TransitionStyle, initialize_timescale_group, prepare_group
from sekai.lib.timescale_math import AccurateScalar, AffineTransfer


class TimescaleChange(PlayArchetype):
    name = archetype_names.TIMESCALE_CHANGE

    beat: StandardImport.BEAT
    timescale: StandardImport.TIMESCALE
    timescale_skip: StandardImport.TIMESCALE_SKIP
    timescale_group: StandardImport.TIMESCALE_GROUP
    timescale_ease: EaseType = imported(name="#TIMESCALE_EASE", default=EaseType.NONE)
    hide_notes: bool = imported(name="hideNotes")
    next_ref: EntityRef[TimescaleChange] = imported(name="next")
    transition_style: TransitionStyle = imported(name="transitionStyle", default=TransitionStyle.TIMESCALE)

    event_start: float = entity_data()
    event_end: float = entity_data()
    tree_left: int = entity_data()
    tree_right: int = entity_data()
    subtree_first: int = entity_data()
    subtree_last: int = entity_data()
    aggregate: AffineTransfer = entity_data()
    run_first: int = entity_data()
    run_end: int = entity_data()
    run_prefix: AccurateScalar = entity_data()  # TS prefix distance; SCROLL remaining-run ratio.
    run_suffix: AccurateScalar = entity_data()

    suffix_r_min: AccurateScalar = shared_memory()
    suffix_r_max: AccurateScalar = shared_memory()
    suffix_b_max: AccurateScalar = shared_memory()
    ratio_or_curve: AccurateScalar = shared_memory()  # TS slope/curvature; SCROLL outgoing-link ratio.
    own_distance: AccurateScalar = shared_memory()
    ordinal: int = shared_memory()
    prev_ref: int = shared_memory()
    tree_parent: int = shared_memory()
    validation_owner: int = shared_memory()
    run_peak_speed: float = shared_memory()
    converted_skip: AccurateScalar = shared_memory()
    midpoint_hi: float = shared_memory()
    midpoint_lo: float = shared_memory()

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False


class TimescaleGroup(PlayArchetype):
    name = archetype_names.TIMESCALE_GROUP

    first_ref: EntityRef[TimescaleChange] = imported(name="first")
    force_note_speed: float = imported(name="forceNoteSpeed")
    root: int = entity_data()
    mode: int = entity_data()
    valid: bool = entity_data()
    marker_count: int = entity_data()
    final_ref: int = entity_data()
    error_code: TimelineError = entity_data()
    used: bool = entity_data()
    effective_preempt: float = entity_data()
    needed_start: float = entity_data()
    needed_end: float = entity_data()

    time_valid: bool = shared_memory()
    last_updated: float = shared_memory()
    current_event: int = shared_memory()
    current_run: int = shared_memory()
    current_constant: bool = shared_memory()
    current_run_end: int = shared_memory()
    current_speed: float = shared_memory()
    certified_current_speed: AccurateScalar = shared_memory()
    hide_notes: bool = shared_memory()
    future_ratio: AccurateScalar = shared_memory()  # SCROLL future ratio; TS current-piece curvature.
    future_distance: AccurateScalar = shared_memory()
    past_ratio: AccurateScalar = shared_memory()  # SCROLL past ratio; TS OUT_IN midpoint speed.
    past_distance: AccurateScalar = shared_memory()
    last_spawn_target: float = shared_memory()
    last_spawn_ceiling: float = shared_memory()
    last_spawn_time: float = shared_memory()
    spawn_cursor_valid: bool = shared_memory()

    @callback(order=-2)
    def preprocess(self):
        initialize_timescale_group(self)

    @callback(order=-3)
    def update_sequential(self):
        assert self.used, "Only groups with registered consumers may spawn"
        prepare_group(self.index, time())
        # Notes and SimLines prepare before their final parallel cleanup.
        # Refresh that first frame past the bound, even after a large jump.
        if time() > self.needed_end:
            self.despawn = True

    def spawn_order(self) -> float:
        return self.needed_start

    def should_spawn(self) -> bool:
        return self.used and time() >= self.needed_start
