from __future__ import annotations

from typing import cast

from sonolus.script.archetype import EntityRef, PreviewArchetype, StandardImport, entity_data, imported
from sonolus.script.interval import lerp
from sonolus.script.sprite import Sprite
from sonolus.script.timing import beat_to_time

from sekai.lib.connector import ConnectorKind, ConnectorLayer, SegmentPresentation
from sekai.lib.ease import EaseType
from sekai.lib.layer import (
    ELEVATION_NOTE_ARROW,
    ELEVATION_NOTE_TICK,
    LAYER_NOTE,
    get_z,
)
from sekai.lib.layout import FlickDirection
from sekai.lib.note import (
    NoteKind,
    get_attach_eased_frac,
    get_attach_frac,
    get_attach_params,
    get_note_body_elevation,
    get_note_sprite_set,
    is_critical,
    map_note_kind,
    mirror_flick_direction,
)
from sekai.lib.options import Options
from sekai.lib.skin import ArrowRenderType, ArrowSpriteSet, BodyRenderType, BodySpriteSet
from sekai.lib.stage import (
    VisualMask,
    get_next_event_time,
    get_stage_props,
    interpolate_visual_masks,
    masked_note_extents_by_limits,
)
from sekai.play.note import derive_note_archetypes
from sekai.preview.dynamic_stage import PreviewDynamicStage
from sekai.preview.layout import (
    PreviewData,
    get_adjusted_time,
    layout_preview_flick_arrow,
    layout_preview_flick_arrow_fallback,
    layout_preview_regular_note_body,
    layout_preview_regular_note_body_fallback,
    layout_preview_slim_note_body,
    layout_preview_slim_note_body_fallback,
    layout_preview_tick,
    time_to_preview_col,
    time_to_preview_y,
)


class PreviewBaseNote(PreviewArchetype):
    beat: StandardImport.BEAT
    stage_ref: EntityRef[PreviewDynamicStage] = imported(name="stage")
    lane: float = imported()
    size: float = imported()
    direction: FlickDirection = imported()
    active_head_ref: EntityRef[PreviewBaseNote] = imported(name="activeHead")
    is_attached: bool = imported(name="isAttached")
    connector_ease: EaseType = imported(name="connectorEase")
    segment_kind: ConnectorKind = imported(name="segmentKind")
    segment_alpha: float = imported(name="segmentAlpha")
    segment_layer: ConnectorLayer = imported(name="segmentLayer")
    segment_through_judge_line: bool = imported(name="segmentThroughJudgeLine")
    segment_presentation: SegmentPresentation = imported(name="segmentPresentation")
    attach_head_ref: EntityRef[PreviewBaseNote] = imported(name="attachHead")
    attach_tail_ref: EntityRef[PreviewBaseNote] = imported(name="attachTail")
    next_ref: EntityRef[PreviewBaseNote] = imported(name="next")
    prev_ref: EntityRef[PreviewBaseNote] = imported(name="prev")

    kind: NoteKind = entity_data()
    data_init_done: bool = entity_data()
    rel_lane: float = entity_data()
    target_time: float = entity_data()

    def init_data(self):
        if self.data_init_done:
            return

        self.kind = map_note_kind(cast(NoteKind, self.key))

        self.data_init_done = True

        if Options.mirror:
            self.lane *= -1
            self.direction = mirror_flick_direction(self.direction)

        self.target_time = beat_to_time(self.beat)

        if self.stage_ref.index > 0:
            props = get_stage_props(self.stage_ref.get(), self.target_time)
            self.rel_lane = self.lane
            self.lane += props.pivot_lane + props.x_lane_translate

        if self.next_ref.index > 0:
            self.next_ref.get().prev_ref = self.ref()

    def preprocess(self):
        self.init_data()

        if self.is_attached:
            attach_head = self.attach_head_ref.get()
            attach_tail = self.attach_tail_ref.get()
            attach_head.init_data()
            attach_tail.init_data()
            self.connector_ease = attach_head.connector_ease
            lane, size = get_attach_params(
                ease_type=attach_head.connector_ease,
                head_lane=attach_head._basic_visual_lane_at(self.target_time),
                head_size=attach_head.size,
                head_target_time=attach_head.target_time,
                tail_lane=attach_tail._basic_visual_lane_at(self.target_time),
                tail_size=attach_tail.size,
                tail_target_time=attach_tail.target_time,
                target_time=self.target_time,
            )
            self.lane = lane
            self.size = size

        PreviewData.max_time = max(PreviewData.max_time, self.target_time)

        if self.is_scored:
            col = max(time_to_preview_col(self.target_time), 0)
            if col < len(PreviewData.note_counts_by_col):
                PreviewData.note_counts_by_col[col] += 1

    def render(self):
        if not self.is_scored:
            return
        render_lane, render_size = self.visual_extents_at(self.target_time, left_limit=True)
        if abs(render_lane) > 12 or render_size <= 0:
            return
        draw_note(self.kind, render_lane, render_size, self.direction, self.target_time)

    @property
    def head_ease_frac(self) -> float:
        if self.is_attached:
            return get_attach_frac(
                self.attach_head_ref.get().target_time, self.attach_tail_ref.get().target_time, self.target_time
            )
        else:
            return 0.0

    @property
    def tail_ease_frac(self) -> float:
        if self.is_attached:
            return get_attach_frac(
                self.attach_head_ref.get().target_time, self.attach_tail_ref.get().target_time, self.target_time
            )
        else:
            return 1.0

    def _basic_visual_lane_at(self, t: float, left_limit: bool = False) -> float:
        if self.stage_ref.index <= 0:
            return self.lane
        props = get_stage_props(self.stage_ref.get(), t)
        x_lane_translate = props.x_lane_translate
        if left_limit:
            x_lane_translate = get_stage_props(self.stage_ref.get(), t, left_limit=True).x_lane_translate
        return props.pivot_lane + self.rel_lane + x_lane_translate

    def visual_lane_at(self, t: float, left_limit: bool = False) -> float:
        if self.is_attached:
            head = self.attach_head_ref.get()
            tail = self.attach_tail_ref.get()
            head_lane = head._basic_visual_lane_at(t, left_limit=left_limit)
            tail_lane = tail._basic_visual_lane_at(t, left_limit=left_limit)
            return lerp(
                head_lane,
                tail_lane,
                get_attach_eased_frac(self.connector_ease, head.target_time, tail.target_time, self.target_time),
            )
        return self._basic_visual_lane_at(t, left_limit=left_limit)

    def _basic_visual_mask_at(self, t: float, left_limit: bool = False) -> VisualMask:
        result = +VisualMask
        if self.stage_ref.index > 0:
            props = get_stage_props(self.stage_ref.get(), t, left_limit=left_limit)
            result.left = props.lane - props.width + props.x_lane_translate
            result.right = props.lane + props.width + props.x_lane_translate
            result.enabled = props.mask_notes
            if result.enabled:
                result.stage_index = self.stage_ref.index
        return result

    def visual_mask_at(self, t: float, left_limit: bool = False) -> VisualMask:
        result = +VisualMask
        if not self.is_attached:
            result @= self._basic_visual_mask_at(t, left_limit=left_limit)
            return result

        head = self.attach_head_ref.get()
        tail = self.attach_tail_ref.get()
        result @= interpolate_visual_masks(
            head._basic_visual_mask_at(t, left_limit=left_limit),
            tail._basic_visual_mask_at(t, left_limit=left_limit),
            get_attach_eased_frac(self.connector_ease, head.target_time, tail.target_time, self.target_time),
        )
        return result

    def visual_extents_at(self, t: float, left_limit: bool = False) -> tuple[float, float]:
        render_lane = self.visual_lane_at(t, left_limit=left_limit)
        mask = self.visual_mask_at(t, left_limit=left_limit)
        return masked_note_extents_by_limits(render_lane, self.size, mask.left, mask.right, mask.enabled)

    def _basic_next_visual_mask_event_time(self, t: float) -> float:
        if self.stage_ref.index <= 0:
            return 1e8
        return get_next_event_time(self.stage_ref.get(), t)

    def next_visual_mask_event_time(self, t: float) -> float:
        if not self.is_attached:
            return self._basic_next_visual_mask_event_time(t)
        return min(
            self.attach_head_ref.get()._basic_next_visual_mask_event_time(t),
            self.attach_tail_ref.get()._basic_next_visual_mask_event_time(t),
        )


def draw_note(kind: NoteKind, lane: float, size: float, direction: FlickDirection, target_time: float):
    col = time_to_preview_col(target_time)
    y = time_to_preview_y(target_time, col)
    sprite_set = get_note_sprite_set(kind, direction)
    draw_note_body(sprite_set.body, kind, lane, size, target_time, col, y)
    draw_note_arrow(sprite_set.arrow, kind, lane, size, target_time, direction, col, y)
    draw_note_tick(sprite_set.tick, lane, target_time, col, y)


def draw_note_body(
    sprites: BodySpriteSet, kind: NoteKind, lane: float, size: float, target_time: float, col: int, y: float
):
    elevation = get_note_body_elevation(kind)
    z = get_z(LAYER_NOTE, time=get_adjusted_time(target_time, col), lane=lane, elevation=elevation)
    match sprites.render_type:
        case BodyRenderType.NORMAL:
            left_layout, middle_layout, right_layout = layout_preview_regular_note_body(lane, size, col, y)
            sprites.left.draw(left_layout, z=z.tuple)
            sprites.middle.draw(middle_layout, z=z.tuple)
            sprites.right.draw(right_layout, z=z.tuple)
        case BodyRenderType.SLIM:
            left_layout, middle_layout, right_layout = layout_preview_slim_note_body(lane, size, col, y)
            sprites.left.draw(left_layout, z=z.tuple)
            sprites.middle.draw(middle_layout, z=z.tuple)
            sprites.right.draw(right_layout, z=z.tuple)
        case BodyRenderType.NORMAL_FALLBACK:
            layout = layout_preview_regular_note_body_fallback(lane, size, col, y)
            sprites.middle.draw(layout, z=z.tuple)
        case BodyRenderType.SLIM_FALLBACK:
            layout = layout_preview_slim_note_body_fallback(lane, size, col, y)
            sprites.middle.draw(layout, z=z.tuple)


def draw_note_arrow(
    sprites: ArrowSpriteSet,
    kind: NoteKind,
    lane: float,
    size: float,
    target_time: float,
    direction: FlickDirection,
    col: int,
    y: float,
):
    z = get_z(
        LAYER_NOTE,
        elevation=ELEVATION_NOTE_ARROW,
        time=get_adjusted_time(target_time, col),
        lane=lane,
        etc=direction + 6 * (not is_critical(kind)),
    )
    match sprites.render_type:
        case ArrowRenderType.NORMAL:
            layout = layout_preview_flick_arrow(lane, size, direction, col, y)
            sprites.get_sprite(size, direction).draw(layout, z=z.tuple)
        case ArrowRenderType.FALLBACK:
            layout = layout_preview_flick_arrow_fallback(lane, size, direction, col, y)
            sprites.get_sprite(size, direction).draw(layout, z=z.tuple)


def draw_note_tick(sprite: Sprite, lane: float, target_time: float, col: int, y: float):
    z = get_z(LAYER_NOTE, time=get_adjusted_time(target_time, col), lane=lane, elevation=ELEVATION_NOTE_TICK)
    layout = layout_preview_tick(lane, col, y)
    sprite.draw(layout, z=z.tuple)


PREVIEW_NOTE_ARCHETYPES = derive_note_archetypes(PreviewBaseNote)
