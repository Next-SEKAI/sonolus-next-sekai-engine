from __future__ import annotations

from sonolus.script.archetype import EntityRef, StandardImport, WatchArchetype, imported

from sekai.lib import archetype_names
from sekai.lib.baseevent import BaseEvent
from sekai.lib.ease import EaseType
from sekai.lib.stage import DivisionParity, JudgeLineColor, StageBorderStyle


class WatchZoomChange(WatchArchetype, BaseEvent):
    name = archetype_names.ZOOM_CHANGE

    beat: StandardImport.BEAT
    zoom: float = imported()
    ease: EaseType = imported()
    next_ref: EntityRef[WatchZoomChange] = imported(name="next")


class WatchDynamicStage(WatchArchetype):
    name = archetype_names.STAGE

    from_start: bool = imported(name="fromStart")
    first_mask_change_ref: EntityRef[WatchStageMaskChange] = imported(name="firstMaskChange")
    first_pivot_change_ref: EntityRef[WatchStagePivotChange] = imported(name="firstPivotChange")
    first_style_change_ref: EntityRef[WatchStageStyleChange] = imported(name="firstStyleChange")

    def spawn_time(self) -> float:
        return -1e8

    def despawn_time(self) -> float:
        return 1e8


class WatchStageMaskChange(WatchArchetype, BaseEvent):
    name = archetype_names.STAGE_MASK_CHANGE

    stage_ref: EntityRef[WatchDynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    size: float = imported()
    ease: EaseType = imported()
    next_ref: EntityRef[WatchStageMaskChange] = imported(name="next")


class WatchStagePivotChange(WatchArchetype, BaseEvent):
    name = archetype_names.STAGE_PIVOT_CHANGE

    stage_ref: EntityRef[WatchDynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    division_size: float = imported(name="divisionSize")
    division_parity: DivisionParity = imported(name="divisionParity")
    ease: EaseType = imported()
    next_ref: EntityRef[WatchStagePivotChange] = imported(name="next")


class WatchStageStyleChange(WatchArchetype, BaseEvent):
    name = archetype_names.STAGE_STYLE_CHANGE

    stage_ref: EntityRef[WatchDynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    judge_line_color: JudgeLineColor = imported(name="judgeLineColor")
    left_border_style: StageBorderStyle = imported(name="leftBorderStyle")
    right_border_style: StageBorderStyle = imported(name="rightBorderStyle")
    alpha: float = imported()
    lane_alpha: float = imported(name="laneAlpha")
    ease: EaseType = imported()
    next_ref: EntityRef[WatchStageStyleChange] = imported(name="next")
