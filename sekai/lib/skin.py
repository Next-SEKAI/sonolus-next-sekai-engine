from __future__ import annotations

from enum import IntEnum
from typing import Self, assert_never

from sonolus.script.array import Array, Dim
from sonolus.script.globals import level_data
from sonolus.script.interval import clamp
from sonolus.script.record import Record
from sonolus.script.sprite import RenderMode, Sprite, SpriteGroup, StandardSprite, skin, sprite, sprite_group

from sekai.lib.layout import FlickDirection
from sekai.lib.note_style import NoteStyle, NoteVisualFamily

# Keep six arrow widths adjacent so each direction remains a SpriteGroup.
_STYLE_COLORS = ("Neutral", "Red", "Green", "Blue", "Yellow", "Purple", "Cyan", "Black")
_STYLE_NOTE_NAMES = (
    "Normal Note",
    "Slide Note",
    "Flick Note",
    "Down Flick Note",
    "Critical Note",
    "Critical Slide Note",
    "Critical Flick Note",
    "Critical Down Flick Note",
    "Normal Trace Note",
    "Trace Flick Note",
    "Trace Down Flick Note",
    "Critical Trace Note",
    "Critical Trace Flick Note",
    "Critical Trace Down Flick Note",
    None,
    None,
    "Damage Note",
)
_STYLE_TICK_NAMES = (
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    None,
    "Normal Trace Diamond",
    "Trace Flick Diamond",
    "Trace Down Flick Diamond",
    "Critical Trace Diamond",
    "Critical Trace Flick Diamond",
    "Critical Trace Down Flick Diamond",
    "Normal Slide Diamond",
    "Critical Slide Diamond",
    None,
)
_STYLE_SLOT_NAMES = (
    "Normal",
    "Slide",
    "Flick",
    "Down Flick",
    "Critical",
    "Critical Slide",
    "Critical Flick",
    "Critical Down Flick",
)
_STYLE_ARROWS = ("Flick Arrow", "Critical Flick Arrow")
_STYLE_DIRECTIONS = ("Up", "Up Left", "Down", "Down Left")
_STYLE_SPRITE_NAMES = tuple(
    name
    for color in _STYLE_COLORS
    for name in (
        *(
            f"Sekai {family} {part} {color}"
            for family in _STYLE_NOTE_NAMES
            if family
            for part in ("Left", "Middle", "Right")
        ),
        *(f"Sekai {family} {color}" for family in _STYLE_TICK_NAMES if family),
        *(f"Sekai Slot{glow} {family} {color}" for family in _STYLE_SLOT_NAMES for glow in ("", " Glow")),
        *(
            f"Sekai {family} {direction} {width} {color}"
            for family in _STYLE_ARROWS
            for direction in _STYLE_DIRECTIONS
            for width in range(1, 7)
        ),
        *(
            f"Sekai {family} Active Slide Connection {state} {color}"
            for family in ("Normal", "Critical")
            for state in ("Normal", "Active")
        ),
        *(f"Sekai {family} Slide Slot Glow {color}" for family in ("Normal", "Critical")),
        f"Sekai Damage Slide Connection {color}",
        f"Sekai Damage Slide Connection Active {color}",
    )
)
_STYLE_SPRITE_INDEX = {name: index for index, name in enumerate(_STYLE_SPRITE_NAMES)}


@skin
class BaseSkin:
    render_mode: RenderMode = RenderMode.LIGHTWEIGHT

    cover: StandardSprite.STAGE_COVER

    lane: StandardSprite.LANE
    stage_middle: StandardSprite.STAGE_MIDDLE
    judgment_line: StandardSprite.JUDGMENT_LINE
    stage_left_border: StandardSprite.STAGE_LEFT_BORDER
    stage_right_border: StandardSprite.STAGE_RIGHT_BORDER

    lane_background: Sprite = sprite("Sekai Lane Background")
    lane_divider: Sprite = sprite("Sekai Lane Divider")
    stage_border: Sprite = sprite("Sekai Stage Border")
    lane_background_preview: Sprite = sprite("Sekai Lane Background Preview")
    lane_divider_preview: Sprite = sprite("Sekai Lane Divider Preview")
    stage_border_preview: Sprite = sprite("Sekai Stage Border Preview")
    judgment_background: Sprite = sprite("Sekai Judgment Background")

    judgment_background_neutral: Sprite = sprite("Sekai Judgment Background Neutral")
    judgment_gradient_neutral: Sprite = sprite("Sekai Judgment Gradient Neutral")
    judgment_edge_neutral: Sprite = sprite("Sekai Judgment Edge Neutral")
    judgment_single_line_neutral: Sprite = sprite("Sekai Judgment Single Line Neutral")
    judgment_edge_left_neutral: Sprite = sprite("Sekai Judgment Edge Left Neutral")
    judgment_center_neutral: Sprite = sprite("Sekai Judgment Center Neutral")

    judgment_background_red: Sprite = sprite("Sekai Judgment Background Red")
    judgment_gradient_red: Sprite = sprite("Sekai Judgment Gradient Red")
    judgment_edge_red: Sprite = sprite("Sekai Judgment Edge Red")
    judgment_single_line_red: Sprite = sprite("Sekai Judgment Single Line Red")
    judgment_edge_left_red: Sprite = sprite("Sekai Judgment Edge Left Red")
    judgment_center_red: Sprite = sprite("Sekai Judgment Center Red")

    judgment_background_green: Sprite = sprite("Sekai Judgment Background Green")
    judgment_gradient_green: Sprite = sprite("Sekai Judgment Gradient Green")
    judgment_edge_green: Sprite = sprite("Sekai Judgment Edge Green")
    judgment_single_line_green: Sprite = sprite("Sekai Judgment Single Line Green")
    judgment_edge_left_green: Sprite = sprite("Sekai Judgment Edge Left Green")
    judgment_center_green: Sprite = sprite("Sekai Judgment Center Green")

    judgment_background_blue: Sprite = sprite("Sekai Judgment Background Blue")
    judgment_gradient_blue: Sprite = sprite("Sekai Judgment Gradient Blue")
    judgment_edge_blue: Sprite = sprite("Sekai Judgment Edge Blue")
    judgment_single_line_blue: Sprite = sprite("Sekai Judgment Single Line Blue")
    judgment_edge_left_blue: Sprite = sprite("Sekai Judgment Edge Left Blue")
    judgment_center_blue: Sprite = sprite("Sekai Judgment Center Blue")

    judgment_background_yellow: Sprite = sprite("Sekai Judgment Background Yellow")
    judgment_gradient_yellow: Sprite = sprite("Sekai Judgment Gradient Yellow")
    judgment_edge_yellow: Sprite = sprite("Sekai Judgment Edge Yellow")
    judgment_single_line_yellow: Sprite = sprite("Sekai Judgment Single Line Yellow")
    judgment_edge_left_yellow: Sprite = sprite("Sekai Judgment Edge Left Yellow")
    judgment_center_yellow: Sprite = sprite("Sekai Judgment Center Yellow")

    judgment_background_purple: Sprite = sprite("Sekai Judgment Background Purple")
    judgment_gradient_purple: Sprite = sprite("Sekai Judgment Gradient Purple")
    judgment_edge_purple: Sprite = sprite("Sekai Judgment Edge Purple")
    judgment_single_line_purple: Sprite = sprite("Sekai Judgment Single Line Purple")
    judgment_edge_left_purple: Sprite = sprite("Sekai Judgment Edge Left Purple")
    judgment_center_purple: Sprite = sprite("Sekai Judgment Center Purple")

    judgment_background_cyan: Sprite = sprite("Sekai Judgment Background Cyan")
    judgment_gradient_cyan: Sprite = sprite("Sekai Judgment Gradient Cyan")
    judgment_edge_cyan: Sprite = sprite("Sekai Judgment Edge Cyan")
    judgment_single_line_cyan: Sprite = sprite("Sekai Judgment Single Line Cyan")
    judgment_edge_left_cyan: Sprite = sprite("Sekai Judgment Edge Left Cyan")
    judgment_center_cyan: Sprite = sprite("Sekai Judgment Center Cyan")

    judgment_background_black: Sprite = sprite("Sekai Judgment Background Black")
    judgment_gradient_black: Sprite = sprite("Sekai Judgment Gradient Black")
    judgment_edge_black: Sprite = sprite("Sekai Judgment Edge Black")
    judgment_single_line_black: Sprite = sprite("Sekai Judgment Single Line Black")
    judgment_edge_left_black: Sprite = sprite("Sekai Judgment Edge Left Black")
    judgment_center_black: Sprite = sprite("Sekai Judgment Center Black")

    sekai_stage: Sprite = sprite("Sekai Stage")

    sim_line: StandardSprite.SIMULTANEOUS_CONNECTION_NEUTRAL

    note_cyan_left: Sprite = sprite("Sekai Note Cyan Left")
    note_cyan_middle: Sprite = sprite("Sekai Note Cyan Middle")
    note_cyan_right: Sprite = sprite("Sekai Note Cyan Right")
    note_cyan_fallback: StandardSprite.NOTE_HEAD_CYAN

    note_green_left: Sprite = sprite("Sekai Note Green Left")
    note_green_middle: Sprite = sprite("Sekai Note Green Middle")
    note_green_right: Sprite = sprite("Sekai Note Green Right")
    note_green_fallback: StandardSprite.NOTE_HEAD_GREEN

    note_red_left: Sprite = sprite("Sekai Note Red Left")
    note_red_middle: Sprite = sprite("Sekai Note Red Middle")
    note_red_right: Sprite = sprite("Sekai Note Red Right")
    note_red_fallback: StandardSprite.NOTE_HEAD_RED

    note_yellow_left: Sprite = sprite("Sekai Note Yellow Left")
    note_yellow_middle: Sprite = sprite("Sekai Note Yellow Middle")
    note_yellow_right: Sprite = sprite("Sekai Note Yellow Right")
    note_yellow_fallback: StandardSprite.NOTE_HEAD_YELLOW

    normal_note_left: Sprite = sprite("Sekai Normal Note Left")
    normal_note_middle: Sprite = sprite("Sekai Normal Note Middle")
    normal_note_right: Sprite = sprite("Sekai Normal Note Right")
    normal_note_basic: Sprite = sprite("Sekai Normal Note Basic")

    slide_note_left: Sprite = sprite("Sekai Slide Note Left")
    slide_note_middle: Sprite = sprite("Sekai Slide Note Middle")
    slide_note_right: Sprite = sprite("Sekai Slide Note Right")
    slide_note_basic: Sprite = sprite("Sekai Slide Note Basic")

    flick_note_left: Sprite = sprite("Sekai Flick Note Left")
    flick_note_middle: Sprite = sprite("Sekai Flick Note Middle")
    flick_note_right: Sprite = sprite("Sekai Flick Note Right")
    flick_note_basic: Sprite = sprite("Sekai Flick Note Basic")

    down_flick_note_left: Sprite = sprite("Sekai Down Flick Note Left")
    down_flick_note_middle: Sprite = sprite("Sekai Down Flick Note Middle")
    down_flick_note_right: Sprite = sprite("Sekai Down Flick Note Right")

    critical_note_left: Sprite = sprite("Sekai Critical Note Left")
    critical_note_middle: Sprite = sprite("Sekai Critical Note Middle")
    critical_note_right: Sprite = sprite("Sekai Critical Note Right")
    critical_note_basic: Sprite = sprite("Sekai Critical Note Basic")

    critical_slide_note_left: Sprite = sprite("Sekai Critical Slide Note Left")
    critical_slide_note_middle: Sprite = sprite("Sekai Critical Slide Note Middle")
    critical_slide_note_right: Sprite = sprite("Sekai Critical Slide Note Right")
    critical_slide_note_basic: Sprite = sprite("Sekai Critical Slide Note Basic")

    critical_flick_note_left: Sprite = sprite("Sekai Critical Flick Note Left")
    critical_flick_note_middle: Sprite = sprite("Sekai Critical Flick Note Middle")
    critical_flick_note_right: Sprite = sprite("Sekai Critical Flick Note Right")
    critical_flick_note_basic: Sprite = sprite("Sekai Critical Flick Note Basic")

    critical_down_flick_note_left: Sprite = sprite("Sekai Critical Down Flick Note Left")
    critical_down_flick_note_middle: Sprite = sprite("Sekai Critical Down Flick Note Middle")
    critical_down_flick_note_right: Sprite = sprite("Sekai Critical Down Flick Note Right")

    slide_tick_note_green: Sprite = sprite("Sekai Diamond Green")
    slide_tick_note_green_fallback: StandardSprite.NOTE_TICK_GREEN

    slide_tick_note_yellow: Sprite = sprite("Sekai Diamond Yellow")
    slide_tick_note_yellow_fallback: StandardSprite.NOTE_TICK_YELLOW

    normal_slide_tick_note: Sprite = sprite("Sekai Normal Slide Diamond")

    critical_slide_tick_note: Sprite = sprite("Sekai Critical Slide Diamond")

    active_slide_connection_green_normal: Sprite = sprite("Sekai Active Slide Connection Green")
    active_slide_connection_green_active: Sprite = sprite("Sekai Active Slide Connection Green Active")
    active_slide_connection_green_fallback: StandardSprite.NOTE_CONNECTION_GREEN_SEAMLESS

    active_slide_connection_yellow_normal: Sprite = sprite("Sekai Active Slide Connection Yellow")
    active_slide_connection_yellow_active: Sprite = sprite("Sekai Active Slide Connection Yellow Active")
    active_slide_connection_yellow_fallback: StandardSprite.NOTE_CONNECTION_YELLOW_SEAMLESS

    normal_active_slide_connection_normal: Sprite = sprite("Sekai Normal Active Slide Connection Normal")
    normal_active_slide_connection_active: Sprite = sprite("Sekai Normal Active Slide Connection Active")

    critical_active_slide_connection_normal: Sprite = sprite("Sekai Critical Active Slide Connection Normal")
    critical_active_slide_connection_active: Sprite = sprite("Sekai Critical Active Slide Connection Active")

    slot_cyan: Sprite = sprite("Sekai Slot Cyan")
    slot_green: Sprite = sprite("Sekai Slot Green")
    slot_red: Sprite = sprite("Sekai Slot Red")
    slot_yellow: Sprite = sprite("Sekai Slot Yellow")
    slot_yellow_flick: Sprite = sprite("Sekai Slot Yellow Flick")
    slot_yellow_slider: Sprite = sprite("Sekai Slot Yellow Slider")

    slot_normal: Sprite = sprite("Sekai Slot Normal")
    slot_slide: Sprite = sprite("Sekai Slot Slide")
    slot_flick: Sprite = sprite("Sekai Slot Flick")
    slot_down_flick: Sprite = sprite("Sekai Slot Down Flick")
    slot_critical: Sprite = sprite("Sekai Slot Critical")
    slot_critical_slide: Sprite = sprite("Sekai Slot Critical Slide")
    slot_critical_flick: Sprite = sprite("Sekai Slot Critical Flick")
    slot_critical_down_flick: Sprite = sprite("Sekai Slot Critical Down Flick")

    slot_glow_cyan: Sprite = sprite("Sekai Slot Glow Cyan")
    slot_glow_green: Sprite = sprite("Sekai Slot Glow Green")
    slot_glow_red: Sprite = sprite("Sekai Slot Glow Red")
    slot_glow_yellow: Sprite = sprite("Sekai Slot Glow Yellow")
    slot_glow_yellow_flick: Sprite = sprite("Sekai Slot Glow Yellow Flick")
    slot_glow_yellow_slider_tap: Sprite = sprite("Sekai Slot Glow Yellow Slider Tap")

    slot_glow_normal: Sprite = sprite("Sekai Slot Glow Normal")
    slot_glow_slide: Sprite = sprite("Sekai Slot Glow Slide")
    slot_glow_flick: Sprite = sprite("Sekai Slot Glow Flick")
    slot_glow_down_flick: Sprite = sprite("Sekai Slot Glow Down Flick")
    slot_glow_critical: Sprite = sprite("Sekai Slot Glow Critical")
    slot_glow_critical_slide: Sprite = sprite("Sekai Slot Glow Critical Slide")
    slot_glow_critical_flick: Sprite = sprite("Sekai Slot Glow Critical Flick")
    slot_glow_critical_down_flick: Sprite = sprite("Sekai Slot Glow Critical Down Flick")

    slide_connector_slot_glow_green: Sprite = sprite("Sekai Slot Glow Green Slider Hold")
    slide_connector_slot_glow_yellow: Sprite = sprite("Sekai Slot Glow Yellow Slider Hold")

    normal_slide_connector_slot_glow: Sprite = sprite("Sekai Normal Slide Slot Glow")
    critical_slide_connector_slot_glow: Sprite = sprite("Sekai Critical Slide Slot Glow")

    flick_arrow_red_up: SpriteGroup = sprite_group(f"Sekai Flick Arrow Red Up {i}" for i in range(1, 7))
    flick_arrow_red_up_left: SpriteGroup = sprite_group(f"Sekai Flick Arrow Red Up Left {i}" for i in range(1, 7))
    flick_arrow_red_down: SpriteGroup = sprite_group(f"Sekai Flick Arrow Red Down {i}" for i in range(1, 7))
    flick_arrow_red_down_left: SpriteGroup = sprite_group(f"Sekai Flick Arrow Red Down Left {i}" for i in range(1, 7))
    flick_arrow_red_fallback: StandardSprite.DIRECTIONAL_MARKER_RED

    flick_arrow_yellow_up: SpriteGroup = sprite_group(f"Sekai Flick Arrow Yellow Up {i}" for i in range(1, 7))
    flick_arrow_yellow_up_left: SpriteGroup = sprite_group(f"Sekai Flick Arrow Yellow Up Left {i}" for i in range(1, 7))
    flick_arrow_yellow_down: SpriteGroup = sprite_group(f"Sekai Flick Arrow Yellow Down {i}" for i in range(1, 7))
    flick_arrow_yellow_down_left: SpriteGroup = sprite_group(
        f"Sekai Flick Arrow Yellow Down Left {i}" for i in range(1, 7)
    )
    flick_arrow_yellow_fallback: StandardSprite.DIRECTIONAL_MARKER_YELLOW

    flick_arrow_up: SpriteGroup = sprite_group(f"Sekai Flick Arrow Up {i}" for i in range(1, 7))
    flick_arrow_up_left: SpriteGroup = sprite_group(f"Sekai Flick Arrow Up Left {i}" for i in range(1, 7))
    flick_arrow_down: SpriteGroup = sprite_group(f"Sekai Flick Arrow Down {i}" for i in range(1, 7))
    flick_arrow_down_left: SpriteGroup = sprite_group(f"Sekai Flick Arrow Down Left {i}" for i in range(1, 7))

    critical_flick_arrow_up: SpriteGroup = sprite_group(f"Sekai Critical Flick Arrow Up {i}" for i in range(1, 7))
    critical_flick_arrow_up_left: SpriteGroup = sprite_group(
        f"Sekai Critical Flick Arrow Up Left {i}" for i in range(1, 7)
    )
    critical_flick_arrow_down: SpriteGroup = sprite_group(f"Sekai Critical Flick Arrow Down {i}" for i in range(1, 7))
    critical_flick_arrow_down_left: SpriteGroup = sprite_group(
        f"Sekai Critical Flick Arrow Down Left {i}" for i in range(1, 7)
    )

    trace_note_green_left: Sprite = sprite("Sekai Trace Note Green Left")
    trace_note_green_middle: Sprite = sprite("Sekai Trace Note Green Middle")
    trace_note_green_right: Sprite = sprite("Sekai Trace Note Green Right")
    trace_note_green_fallback: StandardSprite.NOTE_HEAD_GREEN
    trace_note_green_tick: Sprite = sprite("Sekai Trace Diamond Green")
    trace_note_green_tick_fallback: StandardSprite.NOTE_TICK_GREEN

    trace_note_red_left: Sprite = sprite("Sekai Trace Note Red Left")
    trace_note_red_middle: Sprite = sprite("Sekai Trace Note Red Middle")
    trace_note_red_right: Sprite = sprite("Sekai Trace Note Red Right")
    trace_note_red_fallback: StandardSprite.NOTE_HEAD_RED
    trace_note_red_tick: Sprite = sprite("Sekai Trace Diamond Red")
    trace_note_red_tick_fallback: StandardSprite.NOTE_TICK_RED

    trace_note_yellow_left: Sprite = sprite("Sekai Trace Note Yellow Left")
    trace_note_yellow_middle: Sprite = sprite("Sekai Trace Note Yellow Middle")
    trace_note_yellow_right: Sprite = sprite("Sekai Trace Note Yellow Right")
    trace_note_yellow_fallback: StandardSprite.NOTE_HEAD_YELLOW
    trace_note_yellow_tick: Sprite = sprite("Sekai Trace Diamond Yellow")
    trace_note_yellow_tick_fallback: StandardSprite.NOTE_TICK_YELLOW

    trace_note_purple_left: Sprite = sprite("Sekai Trace Note Purple Left")
    trace_note_purple_middle: Sprite = sprite("Sekai Trace Note Purple Middle")
    trace_note_purple_right: Sprite = sprite("Sekai Trace Note Purple Right")
    trace_note_purple_fallback: StandardSprite.NOTE_HEAD_PURPLE

    normal_trace_note_left: Sprite = sprite("Sekai Normal Trace Note Left")
    normal_trace_note_middle: Sprite = sprite("Sekai Normal Trace Note Middle")
    normal_trace_note_right: Sprite = sprite("Sekai Normal Trace Note Right")
    normal_trace_note_tick: Sprite = sprite("Sekai Normal Trace Diamond")
    normal_trace_note_basic: Sprite = sprite("Sekai Normal Trace Note Basic")

    trace_flick_note_left: Sprite = sprite("Sekai Trace Flick Note Left")
    trace_flick_note_middle: Sprite = sprite("Sekai Trace Flick Note Middle")
    trace_flick_note_right: Sprite = sprite("Sekai Trace Flick Note Right")
    trace_flick_note_tick: Sprite = sprite("Sekai Trace Flick Diamond")
    trace_flick_note_basic: Sprite = sprite("Sekai Trace Flick Note Basic")

    trace_down_flick_note_left: Sprite = sprite("Sekai Trace Down Flick Note Left")
    trace_down_flick_note_middle: Sprite = sprite("Sekai Trace Down Flick Note Middle")
    trace_down_flick_note_right: Sprite = sprite("Sekai Trace Down Flick Note Right")
    trace_down_flick_note_tick: Sprite = sprite("Sekai Trace Down Flick Diamond")

    critical_trace_note_left: Sprite = sprite("Sekai Critical Trace Note Left")
    critical_trace_note_middle: Sprite = sprite("Sekai Critical Trace Note Middle")
    critical_trace_note_right: Sprite = sprite("Sekai Critical Trace Note Right")
    critical_trace_note_tick: Sprite = sprite("Sekai Critical Trace Diamond")
    critical_trace_note_basic: Sprite = sprite("Sekai Critical Trace Note Basic")

    critical_trace_flick_note_left: Sprite = sprite("Sekai Critical Trace Flick Note Left")
    critical_trace_flick_note_middle: Sprite = sprite("Sekai Critical Trace Flick Note Middle")
    critical_trace_flick_note_right: Sprite = sprite("Sekai Critical Trace Flick Note Right")
    critical_trace_flick_note_tick: Sprite = sprite("Sekai Critical Trace Flick Diamond")
    critical_trace_flick_note_basic: Sprite = sprite("Sekai Critical Trace Flick Note Basic")

    critical_trace_down_flick_note_left: Sprite = sprite("Sekai Critical Trace Down Flick Note Left")
    critical_trace_down_flick_note_middle: Sprite = sprite("Sekai Critical Trace Down Flick Note Middle")
    critical_trace_down_flick_note_right: Sprite = sprite("Sekai Critical Trace Down Flick Note Right")
    critical_trace_down_flick_note_tick: Sprite = sprite("Sekai Critical Trace Down Flick Diamond")

    damage_note_left: Sprite = sprite("Sekai Damage Note Left")
    damage_note_middle: Sprite = sprite("Sekai Damage Note Middle")
    damage_note_right: Sprite = sprite("Sekai Damage Note Right")
    damage_note_basic: Sprite = sprite("Sekai Damage Note Basic")

    guide_green: Sprite = sprite("Sekai Guide Green")
    guide_green_fallback: StandardSprite.NOTE_CONNECTION_GREEN_SEAMLESS
    guide_yellow: Sprite = sprite("Sekai Guide Yellow")
    guide_yellow_fallback: StandardSprite.NOTE_CONNECTION_YELLOW_SEAMLESS
    guide_red: Sprite = sprite("Sekai Guide Red")
    guide_red_fallback: StandardSprite.NOTE_CONNECTION_RED_SEAMLESS
    guide_purple: Sprite = sprite("Sekai Guide Purple")
    guide_purple_fallback: StandardSprite.NOTE_CONNECTION_PURPLE_SEAMLESS
    guide_cyan: Sprite = sprite("Sekai Guide Cyan")
    guide_cyan_fallback: StandardSprite.NOTE_CONNECTION_CYAN_SEAMLESS
    guide_blue: Sprite = sprite("Sekai Guide Blue")
    guide_blue_fallback: StandardSprite.NOTE_CONNECTION_BLUE_SEAMLESS
    guide_neutral: Sprite = sprite("Sekai Guide Neutral")
    guide_neutral_fallback: StandardSprite.NOTE_CONNECTION_NEUTRAL_SEAMLESS
    guide_black: Sprite = sprite("Sekai Guide Black")
    guide_black_fallback: StandardSprite.NOTE_CONNECTION_NEUTRAL_SEAMLESS

    damage_slide_connection: Sprite = sprite("Sekai Damage Slide Connection")
    damage_slide_connection_fallback: StandardSprite.NOTE_CONNECTION_PURPLE_SEAMLESS
    damage_slide_connection_active: Sprite = sprite("Sekai Damage Slide Connection Active")
    damage_slide_connection_active_fallback: StandardSprite.NOTE_CONNECTION_RED_SEAMLESS

    beat_line: StandardSprite.GRID_NEUTRAL
    preview_divider: StandardSprite.GRID_NEUTRAL
    bpm_change_line: StandardSprite.GRID_PURPLE
    timescale_change_line: StandardSprite.GRID_YELLOW
    camera_line: StandardSprite.GRID_RED
    camera_target_line: StandardSprite.GRID_CYAN

    color_sprites: SpriteGroup = sprite_group(_STYLE_SPRITE_NAMES)


EMPTY_SPRITE = Sprite(-1)
EMPTY_SPRITE_GROUP = SpriteGroup(-1, 1)


def first_available_sprite(*sprites: Sprite) -> Sprite:
    result = +EMPTY_SPRITE
    for s in sprites:
        if s.is_available:
            result @= s
            break
    return result


def first_available_sprite_group(*groups: SpriteGroup) -> SpriteGroup:
    result = +EMPTY_SPRITE_GROUP
    for g in groups:
        if g[0].is_available:
            result @= g
            break
    return result


class JudgmentSpriteSet(Record):
    judgment_background: Sprite
    judgment_gradient: Sprite
    judgment_edge: Sprite
    judgment_single_line: Sprite
    judgment_edge_left: Sprite
    judgment_center: Sprite


class BodyRenderType(IntEnum):
    NORMAL = 0
    SLIM = 1
    NORMAL_FALLBACK = 2
    SLIM_FALLBACK = 3


class BodySpriteSet(Record):
    render_type: BodyRenderType
    left: Sprite
    middle: Sprite
    right: Sprite

    @property
    def available(self):
        return self.middle.is_available

    @classmethod
    def of_normal(cls, left: Sprite, middle: Sprite, right: Sprite) -> Self:
        return cls(
            render_type=BodyRenderType.NORMAL,
            left=left,
            middle=middle,
            right=right,
        )

    @classmethod
    def of_slim(cls, left: Sprite, middle: Sprite, right: Sprite) -> Self:
        return cls(
            render_type=BodyRenderType.SLIM,
            left=left,
            middle=middle,
            right=right,
        )

    @classmethod
    def of_normal_fallback(cls, fallback: Sprite) -> Self:
        return cls(
            render_type=BodyRenderType.NORMAL_FALLBACK,
            left=EMPTY_SPRITE,
            middle=fallback,
            right=EMPTY_SPRITE,
        )

    @classmethod
    def of_slim_fallback(cls, fallback: Sprite) -> Self:
        return cls(
            render_type=BodyRenderType.SLIM_FALLBACK,
            left=EMPTY_SPRITE,
            middle=fallback,
            right=EMPTY_SPRITE,
        )


EMPTY_BODY_SPRITE_SET = BodySpriteSet(
    render_type=BodyRenderType.NORMAL_FALLBACK,
    left=EMPTY_SPRITE,
    middle=EMPTY_SPRITE,
    right=EMPTY_SPRITE,
)


def first_available_body_sprite_set(*sets: BodySpriteSet) -> BodySpriteSet:
    result = +EMPTY_BODY_SPRITE_SET
    for s in sets:
        if s.available:
            result @= s
            break
    return result


class ArrowRenderType(IntEnum):
    NORMAL = 0
    FALLBACK = 1


class ArrowSpriteSet(Record):
    render_type: ArrowRenderType
    up: SpriteGroup
    up_left: SpriteGroup
    down: SpriteGroup
    down_left: SpriteGroup

    def _get_index_from_size(self, size: float) -> int:
        return int(clamp(round(size * 2), 1, 6)) - 1

    def get_sprite(self, size: float, direction) -> Sprite:
        result = +Sprite
        match self.render_type:
            case ArrowRenderType.NORMAL:
                index = self._get_index_from_size(size)
                match direction:
                    case FlickDirection.UP_OMNI:
                        result @= self.up[index]
                    case FlickDirection.DOWN_OMNI:
                        result @= self.down[index]
                    case FlickDirection.UP_LEFT | FlickDirection.UP_RIGHT:
                        result @= self.up_left[index]
                    case FlickDirection.DOWN_LEFT | FlickDirection.DOWN_RIGHT:
                        result @= self.down_left[index]
                    case _:
                        assert_never(direction)
            case ArrowRenderType.FALLBACK:
                result @= self.up[0]
            case _:
                assert_never(self.render_type)
        return result

    @property
    def available(self):
        return self.up[0].is_available

    @classmethod
    def of_normal(cls, up: SpriteGroup, up_left: SpriteGroup, down: SpriteGroup, down_left: SpriteGroup) -> Self:
        return cls(
            render_type=ArrowRenderType.NORMAL,
            up=up,
            up_left=up_left,
            down=down,
            down_left=down_left,
        )

    @classmethod
    def of_fallback(cls, fallback: Sprite) -> Self:
        return cls(
            render_type=ArrowRenderType.FALLBACK,
            up=SpriteGroup(fallback.id, 1),
            up_left=EMPTY_SPRITE_GROUP,
            down=EMPTY_SPRITE_GROUP,
            down_left=EMPTY_SPRITE_GROUP,
        )


def first_available_arrow_sprite_set(*sets: ArrowSpriteSet) -> ArrowSpriteSet:
    result = +EMPTY_ARROW_SPRITE_SET
    for s in sets:
        if s.available:
            result @= s
            break
    return result


EMPTY_ARROW_SPRITE_SET = ArrowSpriteSet(
    render_type=ArrowRenderType.FALLBACK,
    up=EMPTY_SPRITE_GROUP,
    up_left=EMPTY_SPRITE_GROUP,
    down=EMPTY_SPRITE_GROUP,
    down_left=EMPTY_SPRITE_GROUP,
)


class NoteSpriteSet(Record):
    body: BodySpriteSet
    arrow: ArrowSpriteSet
    tick: Sprite
    slot: Sprite
    slot_glow: Sprite


EMPTY_NOTE_SPRITE_SET = NoteSpriteSet(
    body=EMPTY_BODY_SPRITE_SET,
    arrow=EMPTY_ARROW_SPRITE_SET,
    tick=EMPTY_SPRITE,
    slot=EMPTY_SPRITE,
    slot_glow=EMPTY_SPRITE,
)


class ActiveConnectorRenderType(IntEnum):
    NORMAL = 0
    FALLBACK = 1


class ActiveConnectionSpriteSet(Record):
    render_type: ActiveConnectorRenderType
    normal: Sprite
    active: Sprite

    @property
    def available(self):
        return self.normal.is_available

    @classmethod
    def of_normal(cls, normal: Sprite, active: Sprite) -> Self:
        return cls(
            render_type=ActiveConnectorRenderType.NORMAL,
            normal=normal,
            active=active,
        )

    @classmethod
    def of_fallback(cls, fallback: Sprite) -> Self:
        return cls(
            render_type=ActiveConnectorRenderType.FALLBACK,
            normal=fallback,
            active=fallback,
        )


EMPTY_ACTIVE_CONNECTION_SPRITE_SET = ActiveConnectionSpriteSet(
    render_type=ActiveConnectorRenderType.FALLBACK,
    normal=EMPTY_SPRITE,
    active=EMPTY_SPRITE,
)


def first_available_active_connection_sprite_set(*sets: ActiveConnectionSpriteSet) -> ActiveConnectionSpriteSet:
    result = +EMPTY_ACTIVE_CONNECTION_SPRITE_SET
    for s in sets:
        if s.available:
            result @= s
            break
    return result


class ActiveConnectorSpriteSet(Record):
    connection: ActiveConnectionSpriteSet
    slot_glow: Sprite


note_cyan_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.note_cyan_left,
    middle=BaseSkin.note_cyan_middle,
    right=BaseSkin.note_cyan_right,
)
note_cyan_fallback_body_sprites = BodySpriteSet.of_normal_fallback(
    fallback=BaseSkin.note_cyan_fallback,
)
note_green_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.note_green_left,
    middle=BaseSkin.note_green_middle,
    right=BaseSkin.note_green_right,
)
note_green_fallback_body_sprites = BodySpriteSet.of_normal_fallback(
    fallback=BaseSkin.note_green_fallback,
)
note_red_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.note_red_left,
    middle=BaseSkin.note_red_middle,
    right=BaseSkin.note_red_right,
)
note_red_fallback_body_sprites = BodySpriteSet.of_normal_fallback(
    fallback=BaseSkin.note_red_fallback,
)
note_yellow_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.note_yellow_left,
    middle=BaseSkin.note_yellow_middle,
    right=BaseSkin.note_yellow_right,
)
note_yellow_fallback_body_sprites = BodySpriteSet.of_normal_fallback(
    fallback=BaseSkin.note_yellow_fallback,
)
normal_note_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.normal_note_left,
    middle=BaseSkin.normal_note_middle,
    right=BaseSkin.normal_note_right,
)
slide_note_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.slide_note_left,
    middle=BaseSkin.slide_note_middle,
    right=BaseSkin.slide_note_right,
)
flick_note_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.flick_note_left,
    middle=BaseSkin.flick_note_middle,
    right=BaseSkin.flick_note_right,
)
down_flick_note_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.down_flick_note_left,
    middle=BaseSkin.down_flick_note_middle,
    right=BaseSkin.down_flick_note_right,
)
critical_note_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.critical_note_left,
    middle=BaseSkin.critical_note_middle,
    right=BaseSkin.critical_note_right,
)
critical_slide_note_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.critical_slide_note_left,
    middle=BaseSkin.critical_slide_note_middle,
    right=BaseSkin.critical_slide_note_right,
)
critical_flick_note_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.critical_flick_note_left,
    middle=BaseSkin.critical_flick_note_middle,
    right=BaseSkin.critical_flick_note_right,
)
critical_down_flick_note_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.critical_down_flick_note_left,
    middle=BaseSkin.critical_down_flick_note_middle,
    right=BaseSkin.critical_down_flick_note_right,
)

flick_arrow_red_sprites = ArrowSpriteSet.of_normal(
    up=BaseSkin.flick_arrow_red_up,
    up_left=BaseSkin.flick_arrow_red_up_left,
    down=BaseSkin.flick_arrow_red_down,
    down_left=BaseSkin.flick_arrow_red_down_left,
)
flick_arrow_red_fallback_sprites = ArrowSpriteSet.of_fallback(
    fallback=BaseSkin.flick_arrow_red_fallback,
)
flick_arrow_yellow_sprites = ArrowSpriteSet.of_normal(
    up=BaseSkin.flick_arrow_yellow_up,
    up_left=BaseSkin.flick_arrow_yellow_up_left,
    down=BaseSkin.flick_arrow_yellow_down,
    down_left=BaseSkin.flick_arrow_yellow_down_left,
)
flick_arrow_yellow_fallback_sprites = ArrowSpriteSet.of_fallback(
    fallback=BaseSkin.flick_arrow_yellow_fallback,
)
flick_arrow_sprites = ArrowSpriteSet.of_normal(
    up=BaseSkin.flick_arrow_up,
    up_left=BaseSkin.flick_arrow_up_left,
    down=BaseSkin.flick_arrow_down,
    down_left=BaseSkin.flick_arrow_down_left,
)
critical_flick_arrow_sprites = ArrowSpriteSet.of_normal(
    up=BaseSkin.critical_flick_arrow_up,
    up_left=BaseSkin.critical_flick_arrow_up_left,
    down=BaseSkin.critical_flick_arrow_down,
    down_left=BaseSkin.critical_flick_arrow_down_left,
)

trace_note_green_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.trace_note_green_left,
    middle=BaseSkin.trace_note_green_middle,
    right=BaseSkin.trace_note_green_right,
)
trace_note_green_fallback_body_sprites = BodySpriteSet.of_slim_fallback(
    fallback=BaseSkin.trace_note_green_fallback,
)
trace_note_red_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.trace_note_red_left,
    middle=BaseSkin.trace_note_red_middle,
    right=BaseSkin.trace_note_red_right,
)
trace_note_red_fallback_body_sprites = BodySpriteSet.of_slim_fallback(
    fallback=BaseSkin.trace_note_red_fallback,
)
trace_note_yellow_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.trace_note_yellow_left,
    middle=BaseSkin.trace_note_yellow_middle,
    right=BaseSkin.trace_note_yellow_right,
)
trace_note_yellow_fallback_body_sprites = BodySpriteSet.of_slim_fallback(
    fallback=BaseSkin.trace_note_yellow_fallback,
)
trace_note_purple_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.trace_note_purple_left,
    middle=BaseSkin.trace_note_purple_middle,
    right=BaseSkin.trace_note_purple_right,
)
trace_note_purple_fallback_body_sprites = BodySpriteSet.of_slim_fallback(
    fallback=BaseSkin.trace_note_purple_fallback,
)
normal_trace_note_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.normal_trace_note_left,
    middle=BaseSkin.normal_trace_note_middle,
    right=BaseSkin.normal_trace_note_right,
)
trace_flick_note_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.trace_flick_note_left,
    middle=BaseSkin.trace_flick_note_middle,
    right=BaseSkin.trace_flick_note_right,
)
trace_down_flick_note_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.trace_down_flick_note_left,
    middle=BaseSkin.trace_down_flick_note_middle,
    right=BaseSkin.trace_down_flick_note_right,
)
critical_trace_note_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.critical_trace_note_left,
    middle=BaseSkin.critical_trace_note_middle,
    right=BaseSkin.critical_trace_note_right,
)
critical_trace_flick_note_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.critical_trace_flick_note_left,
    middle=BaseSkin.critical_trace_flick_note_middle,
    right=BaseSkin.critical_trace_flick_note_right,
)
critical_trace_down_flick_note_body_sprites = BodySpriteSet.of_slim(
    left=BaseSkin.critical_trace_down_flick_note_left,
    middle=BaseSkin.critical_trace_down_flick_note_middle,
    right=BaseSkin.critical_trace_down_flick_note_right,
)
damage_note_body_sprites = BodySpriteSet.of_normal(
    left=BaseSkin.damage_note_left,
    middle=BaseSkin.damage_note_middle,
    right=BaseSkin.damage_note_right,
)

active_slide_connector_green_sprites = ActiveConnectionSpriteSet.of_normal(
    normal=BaseSkin.active_slide_connection_green_normal,
    active=BaseSkin.active_slide_connection_green_active,
)
active_slide_connector_green_fallback_sprites = ActiveConnectionSpriteSet.of_fallback(
    fallback=BaseSkin.active_slide_connection_green_fallback,
)
active_slide_connector_yellow_sprites = ActiveConnectionSpriteSet.of_normal(
    normal=BaseSkin.active_slide_connection_yellow_normal,
    active=BaseSkin.active_slide_connection_yellow_active,
)
active_slide_connector_yellow_fallback_sprites = ActiveConnectionSpriteSet.of_fallback(
    fallback=BaseSkin.active_slide_connection_yellow_fallback,
)
normal_active_slide_connector_sprites = ActiveConnectionSpriteSet.of_normal(
    normal=BaseSkin.normal_active_slide_connection_normal,
    active=BaseSkin.normal_active_slide_connection_active,
)
critical_active_slide_connector_sprites = ActiveConnectionSpriteSet.of_normal(
    normal=BaseSkin.critical_active_slide_connection_normal,
    active=BaseSkin.critical_active_slide_connection_active,
)


@level_data
class ActiveSkin:
    cover: Sprite

    lane: Sprite
    judgment_line: Sprite
    stage_left_border: Sprite
    stage_right_border: Sprite

    lane_background: Sprite
    lane_divider: Sprite
    stage_border: Sprite
    lane_background_preview: Sprite
    lane_divider_preview: Sprite
    stage_border_preview: Sprite

    judgment_neutral: JudgmentSpriteSet
    judgment_red: JudgmentSpriteSet
    judgment_green: JudgmentSpriteSet
    judgment_blue: JudgmentSpriteSet
    judgment_yellow: JudgmentSpriteSet
    judgment_purple: JudgmentSpriteSet
    judgment_cyan: JudgmentSpriteSet
    judgment_black: JudgmentSpriteSet

    sekai_stage: Sprite

    sim_line: Sprite

    normal_note: NoteSpriteSet
    slide_note: NoteSpriteSet
    flick_note: NoteSpriteSet
    down_flick_note: NoteSpriteSet
    critical_note: NoteSpriteSet
    critical_slide_note: NoteSpriteSet
    critical_flick_note: NoteSpriteSet
    critical_down_flick_note: NoteSpriteSet
    trace_note: NoteSpriteSet
    trace_flick_note: NoteSpriteSet
    trace_down_flick_note: NoteSpriteSet
    critical_trace_note: NoteSpriteSet
    critical_trace_flick_note: NoteSpriteSet
    critical_trace_down_flick_note: NoteSpriteSet
    normal_slide_tick_note: NoteSpriteSet
    critical_slide_tick_note: NoteSpriteSet
    damage_note: NoteSpriteSet

    active_slide_connector: ActiveConnectorSpriteSet
    critical_active_slide_connector: ActiveConnectorSpriteSet

    guide_green: Sprite
    guide_yellow: Sprite
    guide_red: Sprite
    guide_purple: Sprite
    guide_cyan: Sprite
    guide_blue: Sprite
    guide_neutral: Sprite
    guide_black: Sprite

    damage_slide_connector: Sprite
    damage_slide_connector_active: Sprite

    beat_line: Sprite
    preview_divider: Sprite
    bpm_change_line: Sprite
    timescale_change_line: Sprite
    camera_line: Sprite
    camera_target_line: Sprite


def init_skin():
    ActiveSkin.cover = BaseSkin.cover

    ActiveSkin.lane = BaseSkin.lane
    ActiveSkin.judgment_line = BaseSkin.judgment_line
    ActiveSkin.stage_left_border = BaseSkin.stage_left_border
    ActiveSkin.stage_right_border = BaseSkin.stage_right_border

    ActiveSkin.lane_background = BaseSkin.lane_background
    ActiveSkin.lane_divider = BaseSkin.lane_divider
    ActiveSkin.stage_border = BaseSkin.stage_border
    ActiveSkin.lane_background_preview = BaseSkin.lane_background_preview
    ActiveSkin.lane_divider_preview = BaseSkin.lane_divider_preview
    ActiveSkin.stage_border_preview = BaseSkin.stage_border_preview

    ActiveSkin.judgment_neutral = JudgmentSpriteSet(
        judgment_background=first_available_sprite(
            BaseSkin.judgment_background_neutral,
            BaseSkin.judgment_background,
        ),
        judgment_gradient=BaseSkin.judgment_gradient_neutral,
        judgment_edge=BaseSkin.judgment_edge_neutral,
        judgment_single_line=first_available_sprite(
            BaseSkin.judgment_single_line_neutral,
            BaseSkin.judgment_edge_neutral,
        ),
        judgment_edge_left=first_available_sprite(
            BaseSkin.judgment_edge_left_neutral,
            BaseSkin.judgment_edge_neutral,
        ),
        judgment_center=BaseSkin.judgment_center_neutral,
    )
    ActiveSkin.judgment_red = JudgmentSpriteSet(
        judgment_background=first_available_sprite(
            BaseSkin.judgment_background_red,
            BaseSkin.judgment_background,
        ),
        judgment_gradient=BaseSkin.judgment_gradient_red,
        judgment_edge=BaseSkin.judgment_edge_red,
        judgment_single_line=first_available_sprite(
            BaseSkin.judgment_single_line_red,
            BaseSkin.judgment_edge_red,
        ),
        judgment_edge_left=first_available_sprite(
            BaseSkin.judgment_edge_left_red,
            BaseSkin.judgment_edge_red,
        ),
        judgment_center=BaseSkin.judgment_center_red,
    )
    ActiveSkin.judgment_green = JudgmentSpriteSet(
        judgment_background=first_available_sprite(
            BaseSkin.judgment_background_green,
            BaseSkin.judgment_background,
        ),
        judgment_gradient=BaseSkin.judgment_gradient_green,
        judgment_edge=BaseSkin.judgment_edge_green,
        judgment_single_line=first_available_sprite(
            BaseSkin.judgment_single_line_green,
            BaseSkin.judgment_edge_green,
        ),
        judgment_edge_left=first_available_sprite(
            BaseSkin.judgment_edge_left_green,
            BaseSkin.judgment_edge_green,
        ),
        judgment_center=BaseSkin.judgment_center_green,
    )
    ActiveSkin.judgment_blue = JudgmentSpriteSet(
        judgment_background=first_available_sprite(
            BaseSkin.judgment_background_blue,
            BaseSkin.judgment_background,
        ),
        judgment_gradient=BaseSkin.judgment_gradient_blue,
        judgment_edge=BaseSkin.judgment_edge_blue,
        judgment_single_line=first_available_sprite(
            BaseSkin.judgment_single_line_blue,
            BaseSkin.judgment_edge_blue,
        ),
        judgment_edge_left=first_available_sprite(
            BaseSkin.judgment_edge_left_blue,
            BaseSkin.judgment_edge_blue,
        ),
        judgment_center=BaseSkin.judgment_center_blue,
    )
    ActiveSkin.judgment_yellow = JudgmentSpriteSet(
        judgment_background=first_available_sprite(
            BaseSkin.judgment_background_yellow,
            BaseSkin.judgment_background,
        ),
        judgment_gradient=BaseSkin.judgment_gradient_yellow,
        judgment_edge=BaseSkin.judgment_edge_yellow,
        judgment_single_line=first_available_sprite(
            BaseSkin.judgment_single_line_yellow,
            BaseSkin.judgment_edge_yellow,
        ),
        judgment_edge_left=first_available_sprite(
            BaseSkin.judgment_edge_left_yellow,
            BaseSkin.judgment_edge_yellow,
        ),
        judgment_center=BaseSkin.judgment_center_yellow,
    )
    ActiveSkin.judgment_purple = JudgmentSpriteSet(
        judgment_background=first_available_sprite(
            BaseSkin.judgment_background_purple,
            BaseSkin.judgment_background,
        ),
        judgment_gradient=BaseSkin.judgment_gradient_purple,
        judgment_edge=BaseSkin.judgment_edge_purple,
        judgment_single_line=first_available_sprite(
            BaseSkin.judgment_single_line_purple,
            BaseSkin.judgment_edge_purple,
        ),
        judgment_edge_left=first_available_sprite(
            BaseSkin.judgment_edge_left_purple,
            BaseSkin.judgment_edge_purple,
        ),
        judgment_center=BaseSkin.judgment_center_purple,
    )
    ActiveSkin.judgment_cyan = JudgmentSpriteSet(
        judgment_background=first_available_sprite(
            BaseSkin.judgment_background_cyan,
            BaseSkin.judgment_background,
        ),
        judgment_gradient=BaseSkin.judgment_gradient_cyan,
        judgment_edge=BaseSkin.judgment_edge_cyan,
        judgment_single_line=first_available_sprite(
            BaseSkin.judgment_single_line_cyan,
            BaseSkin.judgment_edge_cyan,
        ),
        judgment_edge_left=first_available_sprite(
            BaseSkin.judgment_edge_left_cyan,
            BaseSkin.judgment_edge_cyan,
        ),
        judgment_center=BaseSkin.judgment_center_cyan,
    )
    ActiveSkin.judgment_black = JudgmentSpriteSet(
        judgment_background=first_available_sprite(
            BaseSkin.judgment_background_black,
            BaseSkin.judgment_background,
        ),
        judgment_gradient=BaseSkin.judgment_gradient_black,
        judgment_edge=BaseSkin.judgment_edge_black,
        judgment_single_line=first_available_sprite(
            BaseSkin.judgment_single_line_black,
            BaseSkin.judgment_edge_black,
        ),
        judgment_edge_left=first_available_sprite(
            BaseSkin.judgment_edge_left_black,
            BaseSkin.judgment_edge_black,
        ),
        judgment_center=BaseSkin.judgment_center_black,
    )

    ActiveSkin.sekai_stage = BaseSkin.sekai_stage

    ActiveSkin.sim_line = BaseSkin.sim_line

    ActiveSkin.normal_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            normal_note_body_sprites,
            note_cyan_body_sprites,
            note_cyan_fallback_body_sprites,
        ),
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=EMPTY_SPRITE,
        slot=first_available_sprite(
            BaseSkin.slot_normal,
            BaseSkin.slot_cyan,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.slot_glow_normal,
            BaseSkin.slot_glow_cyan,
        ),
    )
    ActiveSkin.slide_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            slide_note_body_sprites,
            note_green_body_sprites,
            note_green_fallback_body_sprites,
        ),
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=EMPTY_SPRITE,
        slot=first_available_sprite(
            BaseSkin.slot_slide,
            BaseSkin.slot_green,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.slot_glow_slide,
            BaseSkin.slot_glow_green,
        ),
    )
    ActiveSkin.flick_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            flick_note_body_sprites,
            note_red_body_sprites,
            note_red_fallback_body_sprites,
        ),
        arrow=first_available_arrow_sprite_set(
            flick_arrow_sprites,
            flick_arrow_red_sprites,
            flick_arrow_red_fallback_sprites,
        ),
        tick=EMPTY_SPRITE,
        slot=first_available_sprite(
            BaseSkin.slot_flick,
            BaseSkin.slot_red,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.slot_glow_flick,
            BaseSkin.slot_glow_red,
        ),
    )
    ActiveSkin.down_flick_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            down_flick_note_body_sprites,
            flick_note_body_sprites,
            note_red_body_sprites,
            note_red_fallback_body_sprites,
        ),
        arrow=first_available_arrow_sprite_set(
            flick_arrow_sprites,
            flick_arrow_red_sprites,
            flick_arrow_red_fallback_sprites,
        ),
        tick=EMPTY_SPRITE,
        slot=first_available_sprite(
            BaseSkin.slot_down_flick,
            BaseSkin.slot_flick,
            BaseSkin.slot_red,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.slot_glow_down_flick,
            BaseSkin.slot_glow_flick,
            BaseSkin.slot_glow_red,
        ),
    )
    ActiveSkin.critical_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            critical_note_body_sprites,
            note_yellow_body_sprites,
            note_yellow_fallback_body_sprites,
        ),
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=EMPTY_SPRITE,
        slot=first_available_sprite(
            BaseSkin.slot_critical,
            BaseSkin.slot_yellow,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.slot_glow_critical,
            BaseSkin.slot_glow_yellow,
        ),
    )
    ActiveSkin.critical_slide_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            critical_slide_note_body_sprites,
            critical_note_body_sprites,
            note_yellow_body_sprites,
            note_yellow_fallback_body_sprites,
        ),
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=EMPTY_SPRITE,
        slot=first_available_sprite(
            BaseSkin.slot_critical_slide,
            BaseSkin.slot_yellow_slider,
            BaseSkin.slot_critical,
            BaseSkin.slot_yellow,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.slot_glow_critical_slide,
            BaseSkin.slot_glow_yellow_slider_tap,
            BaseSkin.slot_glow_critical,
            BaseSkin.slot_glow_yellow,
        ),
    )
    ActiveSkin.critical_flick_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            critical_flick_note_body_sprites,
            critical_note_body_sprites,
            note_yellow_body_sprites,
            note_yellow_fallback_body_sprites,
        ),
        arrow=first_available_arrow_sprite_set(
            critical_flick_arrow_sprites,
            flick_arrow_yellow_sprites,
            flick_arrow_yellow_fallback_sprites,
        ),
        tick=EMPTY_SPRITE,
        slot=first_available_sprite(
            BaseSkin.slot_critical_flick,
            BaseSkin.slot_yellow_flick,
            BaseSkin.slot_critical,
            BaseSkin.slot_yellow,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.slot_glow_critical_flick,
            BaseSkin.slot_glow_yellow_flick,
            BaseSkin.slot_glow_critical,
            BaseSkin.slot_glow_yellow,
        ),
    )
    ActiveSkin.critical_down_flick_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            critical_down_flick_note_body_sprites,
            critical_flick_note_body_sprites,
            critical_note_body_sprites,
            note_yellow_body_sprites,
            note_yellow_fallback_body_sprites,
        ),
        arrow=first_available_arrow_sprite_set(
            critical_flick_arrow_sprites,
            flick_arrow_yellow_sprites,
            flick_arrow_yellow_fallback_sprites,
        ),
        tick=EMPTY_SPRITE,
        slot=first_available_sprite(
            BaseSkin.slot_critical_down_flick,
            BaseSkin.slot_critical_flick,
            BaseSkin.slot_yellow_flick,
            BaseSkin.slot_critical,
            BaseSkin.slot_yellow,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.slot_glow_critical_down_flick,
            BaseSkin.slot_glow_critical_flick,
            BaseSkin.slot_glow_yellow_flick,
            BaseSkin.slot_glow_critical,
            BaseSkin.slot_glow_yellow,
        ),
    )
    ActiveSkin.trace_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            normal_trace_note_body_sprites,
            trace_note_green_body_sprites,
            trace_note_green_fallback_body_sprites,
        ),
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=first_available_sprite(
            BaseSkin.normal_trace_note_tick,
            BaseSkin.trace_note_green_tick,
            BaseSkin.trace_note_green_tick_fallback,
        ),
        slot=EMPTY_SPRITE,
        slot_glow=EMPTY_SPRITE,
    )
    ActiveSkin.trace_flick_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            trace_flick_note_body_sprites,
            trace_note_red_body_sprites,
            trace_note_red_fallback_body_sprites,
        ),
        arrow=first_available_arrow_sprite_set(
            flick_arrow_sprites,
            flick_arrow_red_sprites,
            flick_arrow_red_fallback_sprites,
        ),
        tick=first_available_sprite(
            BaseSkin.trace_flick_note_tick,
            BaseSkin.trace_note_red_tick,
            BaseSkin.trace_note_red_tick_fallback,
        ),
        slot=EMPTY_SPRITE,
        slot_glow=EMPTY_SPRITE,
    )
    ActiveSkin.trace_down_flick_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            trace_down_flick_note_body_sprites,
            trace_flick_note_body_sprites,
            trace_note_red_body_sprites,
            trace_note_red_fallback_body_sprites,
        ),
        arrow=first_available_arrow_sprite_set(
            flick_arrow_sprites,
            flick_arrow_red_sprites,
            flick_arrow_red_fallback_sprites,
        ),
        tick=first_available_sprite(
            BaseSkin.trace_down_flick_note_tick,
            BaseSkin.trace_flick_note_tick,
            BaseSkin.trace_note_red_tick,
            BaseSkin.trace_note_red_tick_fallback,
        ),
        slot=EMPTY_SPRITE,
        slot_glow=EMPTY_SPRITE,
    )
    ActiveSkin.critical_trace_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            critical_trace_note_body_sprites,
            trace_note_yellow_body_sprites,
            trace_note_yellow_fallback_body_sprites,
        ),
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=first_available_sprite(
            BaseSkin.critical_trace_note_tick,
            BaseSkin.trace_note_yellow_tick,
            BaseSkin.trace_note_yellow_tick_fallback,
        ),
        slot=EMPTY_SPRITE,
        slot_glow=EMPTY_SPRITE,
    )
    ActiveSkin.critical_trace_flick_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            critical_trace_flick_note_body_sprites,
            critical_trace_note_body_sprites,
            trace_note_yellow_body_sprites,
            trace_note_yellow_fallback_body_sprites,
        ),
        arrow=first_available_arrow_sprite_set(
            critical_flick_arrow_sprites,
            flick_arrow_yellow_sprites,
            flick_arrow_yellow_fallback_sprites,
        ),
        tick=first_available_sprite(
            BaseSkin.critical_trace_flick_note_tick,
            BaseSkin.critical_trace_note_tick,
            BaseSkin.trace_note_yellow_tick,
            BaseSkin.trace_note_yellow_tick_fallback,
        ),
        slot=EMPTY_SPRITE,
        slot_glow=EMPTY_SPRITE,
    )
    ActiveSkin.critical_trace_down_flick_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            critical_trace_down_flick_note_body_sprites,
            critical_trace_flick_note_body_sprites,
            critical_trace_note_body_sprites,
            trace_note_yellow_body_sprites,
            trace_note_yellow_fallback_body_sprites,
        ),
        arrow=first_available_arrow_sprite_set(
            critical_flick_arrow_sprites,
            flick_arrow_yellow_sprites,
            flick_arrow_yellow_fallback_sprites,
        ),
        tick=first_available_sprite(
            BaseSkin.critical_trace_down_flick_note_tick,
            BaseSkin.critical_trace_flick_note_tick,
            BaseSkin.critical_trace_note_tick,
            BaseSkin.trace_note_yellow_tick,
            BaseSkin.trace_note_yellow_tick_fallback,
        ),
        slot=EMPTY_SPRITE,
        slot_glow=EMPTY_SPRITE,
    )
    ActiveSkin.normal_slide_tick_note = NoteSpriteSet(
        body=EMPTY_BODY_SPRITE_SET,
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=first_available_sprite(
            BaseSkin.normal_slide_tick_note, BaseSkin.slide_tick_note_green, BaseSkin.slide_tick_note_green_fallback
        ),
        slot=EMPTY_SPRITE,
        slot_glow=EMPTY_SPRITE,
    )
    ActiveSkin.critical_slide_tick_note = NoteSpriteSet(
        body=EMPTY_BODY_SPRITE_SET,
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=first_available_sprite(
            BaseSkin.critical_slide_tick_note, BaseSkin.slide_tick_note_yellow, BaseSkin.slide_tick_note_yellow_fallback
        ),
        slot=EMPTY_SPRITE,
        slot_glow=EMPTY_SPRITE,
    )
    ActiveSkin.damage_note = NoteSpriteSet(
        body=first_available_body_sprite_set(
            damage_note_body_sprites,
            trace_note_purple_body_sprites,
            trace_note_purple_fallback_body_sprites,
        ),
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=EMPTY_SPRITE,
        slot=EMPTY_SPRITE,
        slot_glow=EMPTY_SPRITE,
    )

    ActiveSkin.active_slide_connector = ActiveConnectorSpriteSet(
        connection=first_available_active_connection_sprite_set(
            normal_active_slide_connector_sprites,
            active_slide_connector_green_sprites,
            active_slide_connector_green_fallback_sprites,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.normal_slide_connector_slot_glow,
            BaseSkin.slot_glow_slide,
            BaseSkin.slot_glow_green,
        ),
    )
    ActiveSkin.critical_active_slide_connector = ActiveConnectorSpriteSet(
        connection=first_available_active_connection_sprite_set(
            critical_active_slide_connector_sprites,
            active_slide_connector_yellow_sprites,
            active_slide_connector_yellow_fallback_sprites,
        ),
        slot_glow=first_available_sprite(
            BaseSkin.critical_slide_connector_slot_glow,
            BaseSkin.slot_glow_critical_slide,
            BaseSkin.slot_glow_yellow_slider_tap,
            BaseSkin.slot_glow_critical,
            BaseSkin.slot_glow_yellow,
        ),
    )

    ActiveSkin.guide_green = first_available_sprite(
        BaseSkin.guide_green,
        BaseSkin.guide_green_fallback,
    )
    ActiveSkin.guide_yellow = first_available_sprite(
        BaseSkin.guide_yellow,
        BaseSkin.guide_yellow_fallback,
    )
    ActiveSkin.guide_red = first_available_sprite(
        BaseSkin.guide_red,
        BaseSkin.guide_red_fallback,
    )
    ActiveSkin.guide_purple = first_available_sprite(
        BaseSkin.guide_purple,
        BaseSkin.guide_purple_fallback,
    )
    ActiveSkin.guide_cyan = first_available_sprite(
        BaseSkin.guide_cyan,
        BaseSkin.guide_cyan_fallback,
    )
    ActiveSkin.guide_blue = first_available_sprite(
        BaseSkin.guide_blue,
        BaseSkin.guide_blue_fallback,
    )
    ActiveSkin.guide_neutral = first_available_sprite(
        BaseSkin.guide_neutral,
        BaseSkin.guide_neutral_fallback,
    )
    ActiveSkin.guide_black = first_available_sprite(
        BaseSkin.guide_black,
        BaseSkin.guide_black_fallback,
    )

    ActiveSkin.damage_slide_connector = first_available_sprite(
        BaseSkin.damage_slide_connection,
        BaseSkin.damage_slide_connection_fallback,
    )

    ActiveSkin.damage_slide_connector_active = first_available_sprite(
        BaseSkin.damage_slide_connection_active,
        BaseSkin.damage_slide_connection_active_fallback,
    )

    ActiveSkin.beat_line = BaseSkin.beat_line
    ActiveSkin.preview_divider = BaseSkin.preview_divider
    ActiveSkin.bpm_change_line = BaseSkin.bpm_change_line
    ActiveSkin.timescale_change_line = BaseSkin.timescale_change_line
    ActiveSkin.camera_line = BaseSkin.camera_line
    ActiveSkin.camera_target_line = BaseSkin.camera_target_line

    init_style_skin()


def _style_sprite(name: str, color: str) -> Sprite:
    """Return the named color sprite from BaseSkin."""
    return BaseSkin.color_sprites[_STYLE_SPRITE_INDEX[f"Sekai {name} {color}"]]


def _style_arrow(critical: bool, color: str) -> ArrowSpriteSet:
    prefix = "Critical Flick Arrow" if critical else "Flick Arrow"
    groups = [SpriteGroup(_style_sprite(f"{prefix} {direction} 1", color).id, 6) for direction in _STYLE_DIRECTIONS]
    return ArrowSpriteSet.of_normal(*groups)


def _style_note(family: NoteVisualFamily, color: str) -> NoteSpriteSet:
    body_name = _STYLE_NOTE_NAMES[family]
    tick_name = _STYLE_TICK_NAMES[family]
    body = +EMPTY_BODY_SPRITE_SET
    if body_name is not None:
        parts = [_style_sprite(f"{body_name} {part}", color) for part in ("Left", "Middle", "Right")]
        body = (
            BodySpriteSet.of_slim(*parts)
            if NoteVisualFamily.TRACE_NOTE <= family <= NoteVisualFamily.CRITICAL_TRACE_DOWN_FLICK_NOTE
            else BodySpriteSet.of_normal(*parts)
        )
    arrow = +EMPTY_ARROW_SPRITE_SET
    if "FLICK" in family.name:
        arrow = _style_arrow("CRITICAL" in family.name, color)
    return NoteSpriteSet(
        body=body,
        arrow=arrow,
        tick=_style_sprite(tick_name, color) if tick_name else EMPTY_SPRITE,
        slot=_style_sprite(f"Slot {_STYLE_SLOT_NAMES[family]}", color) if family < 8 else EMPTY_SPRITE,
        slot_glow=_style_sprite(f"Slot Glow {_STYLE_SLOT_NAMES[family]}", color) if family < 8 else EMPTY_SPRITE,
    )


def _style_connector(family: str, color: str) -> ActiveConnectorSpriteSet:
    if family == "Damage":
        return ActiveConnectorSpriteSet(
            connection=ActiveConnectionSpriteSet.of_normal(
                _style_sprite("Damage Slide Connection", color),
                _style_sprite("Damage Slide Connection Active", color),
            ),
            slot_glow=EMPTY_SPRITE,
        )
    return ActiveConnectorSpriteSet(
        connection=ActiveConnectionSpriteSet.of_normal(
            _style_sprite(f"{family} Active Slide Connection Normal", color),
            _style_sprite(f"{family} Active Slide Connection Active", color),
        ),
        slot_glow=_style_sprite(f"{family} Slide Slot Glow", color),
    )


# Source tables live in ROM; preprocessing selects available sprites.
_STYLE_NOTES = Array(*(Array(*(_style_note(family, color) for color in _STYLE_COLORS)) for family in NoteVisualFamily))
_STYLE_CONNECTORS = Array(
    *(
        Array(*(_style_connector(family, color) for color in _STYLE_COLORS))
        for family in ("Normal", "Critical", "Damage")
    )
)


class StyleNoteSprites(Record):
    """Note sprites without arrows, which are shared to fit the 4096-slot LevelData limit."""

    body: BodySpriteSet
    tick: Sprite
    slot: Sprite
    slot_glow: Sprite

    @classmethod
    def of(cls, sprites: NoteSpriteSet) -> Self:
        return cls(body=sprites.body, tick=sprites.tick, slot=sprites.slot, slot_glow=sprites.slot_glow)


@level_data
class StyleSkin:
    notes: Array[Array[StyleNoteSprites, Dim[9]], Dim[17]]
    arrows: Array[Array[ArrowSpriteSet, Dim[9]], Dim[2]]
    connectors: Array[Array[ActiveConnectorSpriteSet, Dim[9]], Dim[3]]


def _complete_body(body: BodySpriteSet) -> bool:
    return body.left.is_available and body.middle.is_available and body.right.is_available


def _complete_arrow(arrow: ArrowSpriteSet) -> bool:
    available = True
    for width in range(6):
        if not (
            arrow.up[width].is_available
            and arrow.up_left[width].is_available
            and arrow.down[width].is_available
            and arrow.down_left[width].is_available
        ):
            available = False
            break
    return available


def _resolve_style_note(source: NoteSpriteSet, default: NoteSpriteSet) -> NoteSpriteSet:
    result = +default
    if source.body.middle.id >= 0 and _complete_body(source.body):
        result.body @= source.body
        # Damage notes may use slim trace sprites as their default.
        if default.body.middle.id >= 0:
            if default.body.render_type in {BodyRenderType.SLIM, BodyRenderType.SLIM_FALLBACK}:
                result.body.render_type = BodyRenderType.SLIM
            else:
                result.body.render_type = BodyRenderType.NORMAL
    if source.arrow.up[0].id >= 0 and _complete_arrow(source.arrow):
        result.arrow @= source.arrow
    result.tick @= first_available_sprite(source.tick, default.tick)
    result.slot @= first_available_sprite(source.slot, default.slot)
    result.slot_glow @= first_available_sprite(source.slot_glow, default.slot_glow)
    return result


def _resolve_style_connector(
    source: ActiveConnectorSpriteSet, default: ActiveConnectorSpriteSet
) -> ActiveConnectorSpriteSet:
    result = +default
    if source.connection.normal.is_available and source.connection.active.is_available:
        result.connection @= source.connection
    result.slot_glow @= first_available_sprite(source.slot_glow, default.slot_glow)
    return result


def init_style_skin():
    defaults = Array(
        ActiveSkin.normal_note,
        ActiveSkin.slide_note,
        ActiveSkin.flick_note,
        ActiveSkin.down_flick_note,
        ActiveSkin.critical_note,
        ActiveSkin.critical_slide_note,
        ActiveSkin.critical_flick_note,
        ActiveSkin.critical_down_flick_note,
        ActiveSkin.trace_note,
        ActiveSkin.trace_flick_note,
        ActiveSkin.trace_down_flick_note,
        ActiveSkin.critical_trace_note,
        ActiveSkin.critical_trace_flick_note,
        ActiveSkin.critical_trace_down_flick_note,
        ActiveSkin.normal_slide_tick_note,
        ActiveSkin.critical_slide_tick_note,
        ActiveSkin.damage_note,
    )
    for family in range(len(StyleSkin.notes)):
        StyleSkin.notes[family][0] @= StyleNoteSprites.of(defaults[family])
        for style in range(1, len(StyleSkin.notes[family])):
            resolved = _resolve_style_note(_STYLE_NOTES[family][style - 1], defaults[family])
            StyleSkin.notes[family][style] @= StyleNoteSprites.of(resolved)
            if family == NoteVisualFamily.FLICK_NOTE:
                StyleSkin.arrows[0][style] @= resolved.arrow
            elif family == NoteVisualFamily.CRITICAL_FLICK_NOTE:
                StyleSkin.arrows[1][style] @= resolved.arrow
    StyleSkin.arrows[0][0] @= ActiveSkin.flick_note.arrow
    StyleSkin.arrows[1][0] @= ActiveSkin.critical_flick_note.arrow
    connector_defaults = Array(
        ActiveSkin.active_slide_connector,
        ActiveSkin.critical_active_slide_connector,
        ActiveConnectorSpriteSet(
            connection=ActiveConnectionSpriteSet.of_normal(
                ActiveSkin.damage_slide_connector, ActiveSkin.damage_slide_connector_active
            ),
            slot_glow=EMPTY_SPRITE,
        ),
    )
    for family in range(len(StyleSkin.connectors)):
        StyleSkin.connectors[family][0] @= connector_defaults[family]
        for style in range(1, len(StyleSkin.connectors[family])):
            StyleSkin.connectors[family][style] @= _resolve_style_connector(
                _STYLE_CONNECTORS[family][style - 1], connector_defaults[family]
            )


def styled_note_sprites(family: NoteVisualFamily, style: NoteStyle) -> NoteSpriteSet:
    index = int(style)
    if index < 0 or index > 8 or style != index:
        index = 0
    sprites = StyleSkin.notes[family][index]
    result = +NoteSpriteSet(
        body=sprites.body,
        arrow=EMPTY_ARROW_SPRITE_SET,
        tick=sprites.tick,
        slot=sprites.slot,
        slot_glow=sprites.slot_glow,
    )
    if family in {
        NoteVisualFamily.FLICK_NOTE,
        NoteVisualFamily.DOWN_FLICK_NOTE,
        NoteVisualFamily.TRACE_FLICK_NOTE,
        NoteVisualFamily.TRACE_DOWN_FLICK_NOTE,
    }:
        result.arrow @= StyleSkin.arrows[0][index]
    elif family in {
        NoteVisualFamily.CRITICAL_FLICK_NOTE,
        NoteVisualFamily.CRITICAL_DOWN_FLICK_NOTE,
        NoteVisualFamily.CRITICAL_TRACE_FLICK_NOTE,
        NoteVisualFamily.CRITICAL_TRACE_DOWN_FLICK_NOTE,
    }:
        result.arrow @= StyleSkin.arrows[1][index]
    return result


def get_styled_active_connector_sprites(style: int, critical: bool) -> ActiveConnectorSpriteSet:
    index = int(style)
    if index < 0 or index > 8 or style != index:
        index = 0
    return StyleSkin.connectors[int(critical)][index]


def get_styled_damage_connector_sprites(style: int) -> ActiveConnectorSpriteSet:
    index = int(style)
    if index < 0 or index > 8 or style != index:
        index = 0
    return StyleSkin.connectors[2][index]
