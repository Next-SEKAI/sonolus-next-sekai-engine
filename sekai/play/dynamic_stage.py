from __future__ import annotations

from sonolus.script.archetype import EntityRef, PlayArchetype, StandardImport, callback, imported

from sekai.lib import archetype_names
from sekai.lib.baseevent import BaseEvent, init_event_list
from sekai.lib.ease import EaseType
from sekai.lib.stage import DivisionParity, JudgeLineColor, StageBorderStyle


class ZoomChange(PlayArchetype, BaseEvent):
    name = archetype_names.ZOOM_CHANGE

    beat: StandardImport.BEAT
    zoom: float = imported()
    ease: EaseType = imported()
    next_ref: EntityRef[ZoomChange] = imported(name="next")

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

    @callback(order=-1)
    def preprocess(self):
        init_event_list(self.first_mask_change_ref)
        init_event_list(self.first_pivot_change_ref)
        init_event_list(self.first_style_change_ref)

    def spawn_order(self) -> float:
        return -1e8

    def should_spawn(self) -> bool:
        return True


class StageMaskChange(PlayArchetype, BaseEvent):
    name = archetype_names.STAGE_MASK_CHANGE

    stage_ref: EntityRef[DynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    size: float = imported()
    ease: EaseType = imported()
    next_ref: EntityRef[StageMaskChange] = imported(name="next")

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
    ease: EaseType = imported()
    next_ref: EntityRef[StagePivotChange] = imported(name="next")

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

    def spawn_order(self) -> float:
        return 1e8

    def should_spawn(self) -> bool:
        return False
