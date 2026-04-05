from enum import IntEnum
from math import ceil, floor
from typing import assert_never

from sonolus.script.quad import Quad
from sonolus.script.record import Record
from sonolus.script.vec import Vec2

from sekai.lib.effect import SFX_DISTANCE, Effects
from sekai.lib.layer import LAYER_COVER, LAYER_STAGE, get_z, get_z_alt
from sekai.lib.layout import (
    DynamicLayout,
    approach,
    layout_full_width_stage_cover,
    layout_hidden_cover,
    layout_lane,
    layout_lane_by_edges,
    layout_sekai_stage,
    layout_stage_cover,
    layout_stage_cover_and_line,
    perspective_rect,
    transformed_vec_at,
)
from sekai.lib.level_config import LevelConfig
from sekai.lib.options import Options, StageCoverMode
from sekai.lib.particle import ActiveParticles
from sekai.lib.skin import ActiveSkin, JudgmentSpriteSet


class JudgeLineColor(IntEnum):
    NEUTRAL = 0
    RED = 1
    GREEN = 2
    BLUE = 3
    YELLOW = 4
    PURPLE = 5
    CYAN = 6
    BLACK = 7


class DivisionParity(IntEnum):
    EVEN = 0
    ODD = 1


class DivisionProps(Record):
    size: int
    parity: DivisionParity


class StageBorderStyle(IntEnum):
    DEFAULT = 0
    LIGHT = 1
    DISABLED = 2


def draw_stage_and_accessories():
    if not LevelConfig.skip_default_stage:
        draw_basic_stage()
    draw_stage_cover()


class Transition[T](Record):
    start: T
    end: T
    progress: float


def normalize_transition[T](value: Transition[T] | T) -> Transition[T]:
    if isinstance(value, Transition):
        return value
    return Transition(start=value, end=value, progress=0)


def draw_basic_stage():
    if not Options.show_lane:
        return
    if ActiveSkin.sekai_stage.is_available and not LevelConfig.dynamic_stages:
        draw_sekai_stage()
    else:
        draw_dynamic_stage(
            lane=0,
            width=6,
            pivot_lane=0,
            division=DivisionProps(size=2, parity=DivisionParity.EVEN),
            judge_line_color=JudgeLineColor.PURPLE,
            left_border_style=StageBorderStyle.DEFAULT,
            right_border_style=StageBorderStyle.DEFAULT,
            order=0,
            a=1,
        )


def draw_sekai_stage():
    layout = layout_sekai_stage()
    ActiveSkin.sekai_stage.draw(layout, z=get_z(LAYER_STAGE))


def get_judgment_sprites(judge_line_color: JudgeLineColor) -> JudgmentSpriteSet:
    result = +JudgmentSpriteSet
    match judge_line_color:
        case JudgeLineColor.NEUTRAL:
            result @= ActiveSkin.judgment_neutral
        case JudgeLineColor.RED:
            result @= ActiveSkin.judgment_red
        case JudgeLineColor.GREEN:
            result @= ActiveSkin.judgment_green
        case JudgeLineColor.BLUE:
            result @= ActiveSkin.judgment_blue
        case JudgeLineColor.YELLOW:
            result @= ActiveSkin.judgment_yellow
        case JudgeLineColor.PURPLE:
            result @= ActiveSkin.judgment_purple
        case JudgeLineColor.CYAN:
            result @= ActiveSkin.judgment_cyan
        case JudgeLineColor.BLACK:
            result @= ActiveSkin.judgment_black
        case _:
            assert_never(judge_line_color)
    return result


def draw_dynamic_stage(
    lane: float,
    width: float,
    pivot_lane: float,
    division: Transition[DivisionProps] | DivisionProps,
    judge_line_color: Transition[JudgeLineColor] | JudgeLineColor,
    left_border_style: Transition[StageBorderStyle] | StageBorderStyle,
    right_border_style: Transition[StageBorderStyle] | StageBorderStyle,
    order: int,
    a: float,
    lane_alpha: float = 1,
    y_offset: float = 0,
):
    division = normalize_transition(division)
    judge_line_color = normalize_transition(judge_line_color)
    left_border_style = normalize_transition(left_border_style)
    right_border_style = normalize_transition(right_border_style)

    sprites_same = judge_line_color.start == judge_line_color.end
    sprites_a = get_judgment_sprites(judge_line_color.start)
    sprites_b = get_judgment_sprites(judge_line_color.end)
    p_sprites = judge_line_color.progress

    if not sprites_b.available:
        draw_fallback_stage(lane, width, division.end.size, division.end.parity, pivot_lane, order, a, y_offset=y_offset)
        return

    travel = approach(1 - y_offset)
    l = lane - width
    r = lane + width
    z_bg0 = get_z_alt(LAYER_STAGE, order * 14)
    z_bg1 = get_z_alt(LAYER_STAGE, order * 14 + 1)
    z_lane0 = get_z_alt(LAYER_STAGE, order * 14 + 2)
    z_lane1 = get_z_alt(LAYER_STAGE, order * 14 + 3)
    z_a0 = get_z_alt(LAYER_STAGE, order * 14 + 4)
    z_a1 = get_z_alt(LAYER_STAGE, order * 14 + 5)
    z_a2 = get_z_alt(LAYER_STAGE, order * 14 + 6)
    z_a3 = get_z_alt(LAYER_STAGE, order * 14 + 7)
    z_b0 = get_z_alt(LAYER_STAGE, order * 14 + 8)
    z_b1 = get_z_alt(LAYER_STAGE, order * 14 + 9)
    z_b2 = get_z_alt(LAYER_STAGE, order * 14 + 10)
    z_b3 = get_z_alt(LAYER_STAGE, order * 14 + 11)
    z_a4 = get_z_alt(LAYER_STAGE, order * 14 + 12)
    z_b4 = get_z_alt(LAYER_STAGE, order * 14 + 13)

    f = 5  # sizing factor for judge line border

    def draw_left_border(style: StageBorderStyle, z: float, a: float):
        match style:
            case StageBorderStyle.DEFAULT:
                layout_b = layout_lane_by_edges(l - 0.08, l)  # Artificially thicken the top so it renders better
                layout_t = layout_lane_by_edges(l - 0.64, l)
                ActiveSkin.stage_border.draw(
                    Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z, a=a
                )
            case StageBorderStyle.LIGHT:
                layout_b = layout_lane_by_edges(l - 0.0125, l + 0.0125)
                layout_t = layout_lane_by_edges(l - 0.1, l + 0.1)
                ActiveSkin.lane_divider.draw(
                    Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z, a=a
                )
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_right_border(style: StageBorderStyle, z: float, a: float):
        match style:
            case StageBorderStyle.DEFAULT:
                layout_b = layout_lane_by_edges(r + 0.08, r)  # Flip horizontally
                layout_t = layout_lane_by_edges(r + 0.64, r)
                ActiveSkin.stage_border.draw(
                    Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z, a=a
                )
            case StageBorderStyle.LIGHT:
                layout_b = layout_lane_by_edges(r - 0.0125, r + 0.0125)
                layout_t = layout_lane_by_edges(r - 0.1, r + 0.1)
                ActiveSkin.lane_divider.draw(
                    Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z, a=a
                )
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_dividers(division_size: int, parity: DivisionParity, pivot: float, z: float, a: float):
        eps = 0.001
        parity_offset = division_size / 2 if parity == DivisionParity.ODD else 0
        shifted_pivot = pivot + parity_offset

        if division_size <= 0:
            return

        k_start = floor((l - shifted_pivot + eps) / division_size) + 1
        k_end = ceil((r - shifted_pivot - eps) / division_size) - 1

        for k in range(k_start, k_end + 1):
            pos = shifted_pivot + k * division_size
            div_layout_b = layout_lane_by_edges(pos - 0.0125, pos + 0.0125)
            div_layout_t = layout_lane_by_edges(pos - 0.1, pos + 0.1)
            ActiveSkin.lane_divider.draw(
                Quad(bl=div_layout_b.bl, tl=div_layout_t.tl, tr=div_layout_t.tr, br=div_layout_b.br), z=z, a=a
            )

    thickness_scale = clamp(1 / travel, 1, 4) if travel > 0 else 4
    judgment_divider_size = transformed_vec_at(0.014 * thickness_scale, travel).x

    def layout_judgment_divider(lane: float):
        b = transformed_vec_at(lane, (1 + DynamicLayout.note_h - DynamicLayout.note_h / f + 0.001) * travel)
        t = transformed_vec_at(lane, (1 - DynamicLayout.note_h + DynamicLayout.note_h / f - 0.001) * travel)
        return Quad(
            bl=b - Vec2(judgment_divider_size, 0),
            tl=t - Vec2(judgment_divider_size, 0),
            tr=t + Vec2(judgment_divider_size, 0),
            br=b + Vec2(judgment_divider_size, 0),
        )

    def draw_judgment_dividers(
        sprites: JudgmentSpriteSet, half_offset: bool, pivot: float, z_lo: float, z_hi: float, a: float
    ):
        eps = 0.001
        shifted_pivot = pivot + (0.5 if half_offset else 0)

        k_start = floor(l - shifted_pivot + eps) + 1
        k_end = ceil(r - shifted_pivot - eps) - 1

        for k in range(k_start, k_end + 1):
            pos = shifted_pivot + k
            div_layout = layout_judgment_divider(pos)
            edge_weight = abs(pos - lane) / width if width > 0 else 0
            sprites.judgment_center.draw(div_layout, z=z_lo, a=a)
            sprites.judgment_edge.draw(div_layout, z=z_hi, a=a * edge_weight)

    def draw_left_judgment_border(sprites: JudgmentSpriteSet, style: StageBorderStyle, z: float, a: float):
        match style:
            case StageBorderStyle.DEFAULT:
                layout = perspective_rect(
                    l,
                    l + 1 / f / 2,
                    1 - DynamicLayout.note_h + DynamicLayout.note_h / f,
                    1 + DynamicLayout.note_h - DynamicLayout.note_h / f,
                    travel,
                )
                sprites.judgment_edge.draw(layout, z=z, a=a)
            case StageBorderStyle.LIGHT:
                layout = layout_judgment_divider(l)
                sprites.judgment_edge.draw(layout, z=z, a=a)
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_right_judgment_border(sprites: JudgmentSpriteSet, style: StageBorderStyle, z: float, a: float):
        match style:
            case StageBorderStyle.DEFAULT:
                layout = perspective_rect(
                    r - 1 / f / 2,
                    r,
                    1 - DynamicLayout.note_h + DynamicLayout.note_h / f,
                    1 + DynamicLayout.note_h - DynamicLayout.note_h / f,
                    travel,
                )
                sprites.judgment_edge.draw(layout, z=z, a=a)
            case StageBorderStyle.LIGHT:
                layout = layout_judgment_divider(r)
                sprites.judgment_edge.draw(layout, z=z, a=a)
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_gradient(sprites: JudgmentSpriteSet, z: float, a: float):
        layout = perspective_rect(
            l, lane, 1 + DynamicLayout.note_h - DynamicLayout.note_h / f, 1 + DynamicLayout.note_h, travel
        )
        sprites.judgment_gradient.draw(layout, z=z, a=a)
        layout = perspective_rect(
            r, lane, 1 + DynamicLayout.note_h - DynamicLayout.note_h / f, 1 + DynamicLayout.note_h, travel
        )
        sprites.judgment_gradient.draw(layout, z=z, a=a)
        layout = perspective_rect(
            l, lane, 1 - DynamicLayout.note_h, 1 - DynamicLayout.note_h + DynamicLayout.note_h / f, travel
        )
        sprites.judgment_gradient.draw(layout, z=z, a=a)
        layout = perspective_rect(
            r, lane, 1 - DynamicLayout.note_h, 1 - DynamicLayout.note_h + DynamicLayout.note_h / f, travel
        )
        sprites.judgment_gradient.draw(layout, z=z, a=a)

    if lane_alpha > 0:
        la = a * lane_alpha
        ActiveSkin.lane_background.draw(layout_lane_by_edges(l, r), z=z_bg0, a=la)

        p_left = left_border_style.progress
        if left_border_style.start == left_border_style.end:
            draw_left_border(left_border_style.start, z_lane0, la)
        else:
            draw_left_border(left_border_style.start, z_lane0, la * (1 - p_left))
            draw_left_border(left_border_style.end, z_lane1, la * p_left)

        p_right = right_border_style.progress
        if right_border_style.start == right_border_style.end:
            draw_right_border(right_border_style.start, z_lane0, la)
        else:
            draw_right_border(right_border_style.start, z_lane0, la * (1 - p_right))
            draw_right_border(right_border_style.end, z_lane1, la * p_right)

        p_div = division.progress
        if division.start == division.end:
            draw_dividers(division.start.size, division.start.parity, pivot_lane, z_lane0, la)
        else:
            if 1 - p_div > 0:
                draw_dividers(division.start.size, division.start.parity, pivot_lane, z_lane0, la * (1 - p_div))
            if p_div > 0:
                draw_dividers(division.end.size, division.end.parity, pivot_lane, z_lane1, la * p_div)

    ActiveSkin.judgment_background.draw(
        perspective_rect(l, r, 1 - DynamicLayout.note_h, 1 + DynamicLayout.note_h, travel), z=z_bg1, a=a
    )

    p_left = left_border_style.progress
    p_right = right_border_style.progress
    p_div = division.progress

    start_has_half_offset = division.start.parity == DivisionParity.ODD and division.start.size % 2 == 1
    end_has_half_offset = division.end.parity == DivisionParity.ODD and division.end.size % 2 == 1
    judgment_dividers_same = start_has_half_offset == end_has_half_offset

    if judgment_dividers_same and sprites_same:
        draw_judgment_dividers(sprites_a, start_has_half_offset, pivot_lane, z_a0, z_a1, a)
    elif judgment_dividers_same:
        draw_judgment_dividers(sprites_a, start_has_half_offset, pivot_lane, z_a0, z_a1, a * (1 - p_sprites))
        draw_judgment_dividers(sprites_b, start_has_half_offset, pivot_lane, z_b0, z_b1, a * p_sprites)
    elif sprites_same:
        draw_judgment_dividers(sprites_a, start_has_half_offset, pivot_lane, z_a0, z_a1, a * (1 - p_div))
        draw_judgment_dividers(sprites_a, end_has_half_offset, pivot_lane, z_a2, z_a3, a * p_div)
    else:
        alpha_aa = (1 - p_sprites) * (1 - p_div)
        alpha_ab = (1 - p_sprites) * p_div
        alpha_ba = p_sprites * (1 - p_div)
        alpha_bb = p_sprites * p_div
        if alpha_aa > 0:
            draw_judgment_dividers(sprites_a, start_has_half_offset, pivot_lane, z_a0, z_a1, a * alpha_aa)
        if alpha_ab > 0:
            draw_judgment_dividers(sprites_a, end_has_half_offset, pivot_lane, z_a2, z_a3, a * alpha_ab)
        if alpha_ba > 0:
            draw_judgment_dividers(sprites_b, start_has_half_offset, pivot_lane, z_b0, z_b1, a * alpha_ba)
        if alpha_bb > 0:
            draw_judgment_dividers(sprites_b, end_has_half_offset, pivot_lane, z_b2, z_b3, a * alpha_bb)

    if sprites_same:
        draw_gradient(sprites_a, z_a4, a)
    else:
        draw_gradient(sprites_a, z_a4, a * (1 - p_sprites))
        draw_gradient(sprites_b, z_b4, a * p_sprites)

    if sprites_same and left_border_style.start == left_border_style.end:
        draw_left_judgment_border(sprites_a, left_border_style.start, z_a0, a)
    else:
        alpha_aa = (1 - p_sprites) * (1 - p_left)
        alpha_ab = (1 - p_sprites) * p_left
        alpha_ba = p_sprites * (1 - p_left)
        alpha_bb = p_sprites * p_left
        if alpha_aa > 0:
            draw_left_judgment_border(sprites_a, left_border_style.start, z_a0, a * alpha_aa)
        if alpha_ab > 0:
            draw_left_judgment_border(sprites_a, left_border_style.end, z_a2, a * alpha_ab)
        if alpha_ba > 0:
            draw_left_judgment_border(sprites_b, left_border_style.start, z_b0, a * alpha_ba)
        if alpha_bb > 0:
            draw_left_judgment_border(sprites_b, left_border_style.end, z_b2, a * alpha_bb)

    if sprites_same and right_border_style.start == right_border_style.end:
        draw_right_judgment_border(sprites_a, right_border_style.start, z_a0, a)
    else:
        alpha_aa = (1 - p_sprites) * (1 - p_right)
        alpha_ab = (1 - p_sprites) * p_right
        alpha_ba = p_sprites * (1 - p_right)
        alpha_bb = p_sprites * p_right
        if alpha_aa > 0:
            draw_right_judgment_border(sprites_a, right_border_style.start, z_a0, a * alpha_aa)
        if alpha_ab > 0:
            draw_right_judgment_border(sprites_a, right_border_style.end, z_a2, a * alpha_ab)
        if alpha_ba > 0:
            draw_right_judgment_border(sprites_b, right_border_style.start, z_b0, a * alpha_ba)
        if alpha_bb > 0:
            draw_right_judgment_border(sprites_b, right_border_style.end, z_b2, a * alpha_bb)


def draw_fallback_stage(
    lane: float, width: float, division_size: int, parity: DivisionParity, pivot: float, z: int, a: float,
    y_offset: float = 0,
):
    travel = approach(1 - y_offset)
    l = lane - width
    r = lane + width
    z_lo = get_z_alt(LAYER_STAGE, z * 3)
    z_mid = get_z_alt(LAYER_STAGE, z * 3 + 1)
    z_hi = get_z_alt(LAYER_STAGE, z * 3 + 2)
    layout_b = layout_lane_by_edges(l - 0.25, l)  # Artificially thicken the top so it renders better
    layout_t = layout_lane_by_edges(l - 1, l)
    ActiveSkin.stage_left_border.draw(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z_mid)
    layout_b = layout_lane_by_edges(r, r + 0.25)
    layout_t = layout_lane_by_edges(r, r + 1)
    ActiveSkin.stage_right_border.draw(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z_mid)

    eps = 0.001
    parity_offset = division_size / 2 if parity == DivisionParity.ODD else 0
    shifted_pivot = pivot + parity_offset
    prev = l
    if division_size > 0:
        k_start = floor((l - shifted_pivot + eps) / division_size) + 1
        k_end = ceil((r - shifted_pivot - eps) / division_size) - 1
        for k in range(k_start, k_end + 1):
            pos = shifted_pivot + k * division_size
            ActiveSkin.lane.draw(layout_lane_by_edges(prev, pos), a=a, z=z_lo)
            prev = pos
    ActiveSkin.lane.draw(layout_lane_by_edges(prev, r), a=a, z=z_lo)

    layout = perspective_rect(l, r, t=1 - DynamicLayout.note_h, b=1 + DynamicLayout.note_h, travel=travel)
    ActiveSkin.judgment_line.draw(layout, z=z_hi, a=a)


def draw_stage_cover():
    if Options.stage_cover > 0:
        match Options.stage_cover_mode:
            case StageCoverMode.STAGE:
                layout = layout_stage_cover()
                ActiveSkin.cover.draw(layout, z=get_z(LAYER_COVER), a=Options.stage_cover_alpha)
            case StageCoverMode.STAGE_AND_LINE:
                cover_layout, line_layout = layout_stage_cover_and_line()
                ActiveSkin.cover.draw(cover_layout, z=get_z(LAYER_COVER), a=Options.stage_cover_alpha)
                ActiveSkin.guide_neutral.draw(line_layout, z=get_z(LAYER_COVER, etc=1), a=0.75)
            case StageCoverMode.FULL_WIDTH:
                layout = layout_full_width_stage_cover()
                ActiveSkin.cover.draw(layout, z=get_z(LAYER_COVER), a=Options.stage_cover_alpha)
            case _:
                assert_never(Options.stage_cover_mode)
    if Options.hidden > 0:
        layout = layout_hidden_cover()
        ActiveSkin.cover.draw(layout, z=get_z(LAYER_COVER), a=1)


def play_lane_hit_effects(lane: float, sfx: bool = True):
    if sfx:
        play_lane_sfx(lane)
    play_lane_particle(lane)


def play_lane_sfx(lane: float):
    if Options.sfx_enabled:
        Effects.stage.play(SFX_DISTANCE)


def schedule_lane_sfx(lane: float, target_time: float):
    if Options.sfx_enabled:
        Effects.stage.schedule(target_time, SFX_DISTANCE)


def play_lane_particle(lane: float):
    if Options.lane_effect_enabled:
        layout = layout_lane(lane, 0.5)
        ActiveParticles.lane.spawn(layout, duration=0.3 / Options.effect_animation_speed)
