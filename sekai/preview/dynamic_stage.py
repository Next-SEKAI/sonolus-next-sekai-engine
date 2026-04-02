from __future__ import annotations

from sonolus.script.archetype import EntityRef, PreviewArchetype, StandardImport, imported

from sekai.lib import archetype_names
from sekai.lib.baseevent import BaseEvent
from sekai.lib.ease import EaseType
from sekai.lib.stage import DivisionParity, JudgeLineColor, StageBorderStyle


class PreviewZoomChange(PreviewArchetype, BaseEvent):
    name = archetype_names.ZOOM_CHANGE

    beat: StandardImport.BEAT
    zoom: float = imported()
    ease: EaseType = imported()
    next_ref: EntityRef[PreviewZoomChange] = imported(name="next")


class PreviewDynamicStage(PreviewArchetype):
    name = archetype_names.STAGE

    from_start: bool = imported(name="fromStart")
    first_mask_change_ref: EntityRef[PreviewStageMaskChange] = imported(name="firstMaskChange")
    first_pivot_change_ref: EntityRef[PreviewStagePivotChange] = imported(name="firstPivotChange")
    first_style_change_ref: EntityRef[PreviewStageStyleChange] = imported(name="firstStyleChange")


class PreviewStageMaskChange(PreviewArchetype, BaseEvent):
    name = archetype_names.STAGE_MASK_CHANGE

    stage_ref: EntityRef[PreviewDynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    size: float = imported()
    ease: EaseType = imported()
    next_ref: EntityRef[PreviewStageMaskChange] = imported(name="next")


class PreviewStagePivotChange(PreviewArchetype, BaseEvent):
    name = archetype_names.STAGE_PIVOT_CHANGE

    stage_ref: EntityRef[PreviewDynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    lane: float = imported()
    division_size: float = imported(name="divisionSize")
    division_parity: DivisionParity = imported(name="divisionParity")
    ease: EaseType = imported()
    next_ref: EntityRef[PreviewStagePivotChange] = imported(name="next")


class PreviewStageStyleChange(PreviewArchetype, BaseEvent):
    name = archetype_names.STAGE_STYLE_CHANGE

    stage_ref: EntityRef[PreviewDynamicStage] = imported(name="stage")
    beat: StandardImport.BEAT
    judge_line_color: JudgeLineColor = imported(name="judgeLineColor")
    left_border_style: StageBorderStyle = imported(name="leftBorderStyle")
    right_border_style: StageBorderStyle = imported(name="rightBorderStyle")
    alpha: float = imported()
    lane_alpha: float = imported(name="laneAlpha")
    ease: EaseType = imported()
    next_ref: EntityRef[PreviewStageStyleChange] = imported(name="next")
