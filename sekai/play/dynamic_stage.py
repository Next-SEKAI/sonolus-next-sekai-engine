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
from sonolus.script.interval import clamp
from sonolus.script.runtime import time, touches
from sonolus.script.timing import beat_to_time

from sekai.lib import archetype_names
from sekai.lib.baseevent import BaseEvent, init_event_list
from sekai.lib.ease import EaseType
from sekai.lib.layout import layout_hitbox, touch_to_lane
from sekai.lib.level_config import LevelConfig
from sekai.lib.stage import (
    DivisionParity,
    JudgeLineColor,
    StageBorderStyle,
    StageProps,
    get_end_time,
    get_stage_props,
    get_start_time,
    play_lane_hit_effects,
)
from sekai.play import input_manager
from sekai.play.common import PlayLevelMemory
from sekai.play.static_stage import StageMemory


class ZoomChange(PlayArchetype, BaseEvent):
    name = archetype_names.ZOOM_CHANGE

    beat: StandardImport.BEAT
    zoom: float = imported()
    ease: EaseType = imported()
    next_ref: EntityRef[ZoomChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-2)
    def preprocess(self):
        LevelConfig.dynamic_stages = True
        self.time = beat_to_time(self.beat)

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False


class DynamicStage(PlayArchetype):
    name = archetype_names.STAGE

    from_start: bool = imported(name="fromStart")
    first_mask_change_ref: EntityRef[StageMaskChange] = imported(name="firstMaskChange")
    first_pivot_change_ref: EntityRef[StagePivotChange] = imported(name="firstPivotChange")
    first_style_change_ref: EntityRef[StageStyleChange] = imported(name="firstStyleChange")

    start_time: float = entity_data()
    end_time: float = entity_data()

    props: StageProps = shared_memory()

    @callback(order=-1)
    def preprocess(self):
        LevelConfig.dynamic_stages = True
        LevelConfig.skip_default_stage = True
        init_event_list(self.first_mask_change_ref)
        init_event_list(self.first_pivot_change_ref)
        init_event_list(self.first_style_change_ref)
        self.start_time = get_start_time(self)
        self.end_time = get_end_time(self)

    def spawn_order(self) -> float:
        return self.start_time

    def should_spawn(self) -> bool:
        return time() >= self.start_time

    @callback(order=-1)
    def update_sequential(self):
        if time() >= self.end_time:
            self.despawn = True
            return
        self.props @= get_stage_props(self)

    @callback(order=2)
    def touch(self):
        p = self.props
        half_offset = p.division.start.parity == DivisionParity.ODD and p.division.start.size % 2 == 1
        lo = p.lane - p.width + 0.5
        hi = p.lane + p.width - 0.5
        total_hitbox = layout_hitbox(p.lane - p.width, p.lane + p.width)
        empty_lanes = StageMemory.empty_lanes
        for touch in touches():
            if not total_hitbox.contains_point(touch.position):
                continue
            if not input_manager.is_allowed_empty(touch):
                continue
            lane = touch_to_lane(touch.position)
            rel = lane - p.pivot_lane
            if half_offset:
                rounded_lane = clamp(p.pivot_lane + round(rel), lo, hi)
            else:
                rounded_lane = clamp(p.pivot_lane + round(rel - 0.5) + 0.5, lo, hi)
            if touch.started:
                play_lane_hit_effects(rounded_lane, sfx=time() > PlayLevelMemory.last_note_sfx_time + 0.6)
                if not empty_lanes.is_full():
                    empty_lanes.append(rounded_lane)
            else:
                prev_lane = touch_to_lane(touch.prev_position)
                prev_rel = prev_lane - p.pivot_lane
                if half_offset:
                    prev_rounded_lane = clamp(p.pivot_lane + round(prev_rel), lo, hi)
                else:
                    prev_rounded_lane = clamp(p.pivot_lane + round(prev_rel - 0.5) + 0.5, lo, hi)
                if rounded_lane != prev_rounded_lane:
                    play_lane_hit_effects(rounded_lane, sfx=time() > PlayLevelMemory.last_note_sfx_time + 0.6)
                    if not empty_lanes.is_full():
                        empty_lanes.append(rounded_lane)

    def update_parallel(self):
        self.props.draw()


class StageMaskChange(PlayArchetype, BaseEvent):
    name = archetype_names.STAGE_MASK_CHANGE

    stage_ref: EntityRef[DynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    size: float = imported()
    ease: EaseType = imported()
    next_ref: EntityRef[StageMaskChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-2)
    def preprocess(self):
        self.time = beat_to_time(self.beat)

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False


class StagePivotChange(PlayArchetype, BaseEvent):
    name = archetype_names.STAGE_PIVOT_CHANGE

    stage_ref: EntityRef[DynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    division_size: float = imported(name="divisionSize")
    division_parity: DivisionParity = imported(name="divisionParity")
    y_offset: float = imported(name="yOffset")
    ease: EaseType = imported()
    next_ref: EntityRef[StagePivotChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-2)
    def preprocess(self):
        self.time = beat_to_time(self.beat)

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False


class StageStyleChange(PlayArchetype, BaseEvent):
    name = archetype_names.STAGE_STYLE_CHANGE

    stage_ref: EntityRef[DynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    judge_line_color: JudgeLineColor = imported(name="judgeLineColor")
    left_border_style: StageBorderStyle = imported(name="leftBorderStyle")
    right_border_style: StageBorderStyle = imported(name="rightBorderStyle")
    alpha: float = imported()
    lane_alpha: float = imported(name="laneAlpha")
    ease: EaseType = imported()
    next_ref: EntityRef[StageStyleChange] = imported(name="next")

    time: float = entity_data()

    @callback(order=-2)
    def preprocess(self):
        self.time = beat_to_time(self.beat)

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False
