from enum import IntEnum
from math import ceil, floor
from typing import assert_never

from sonolus.script.quad import Quad

from sekai.lib.effect import SFX_DISTANCE, Effects
from sekai.lib.layer import LAYER_COVER, LAYER_STAGE, get_z, get_z_alt
from sekai.lib.layout import (
    DynamicLayout,
    layout_full_width_stage_cover,
    layout_hidden_cover,
    layout_lane,
    layout_lane_by_edges,
    layout_sekai_stage,
    layout_stage_cover,
    layout_stage_cover_and_line,
    perspective_rect,
)
from sekai.lib.level_config import LevelConfig
from sekai.lib.options import Options, StageCoverMode
from sekai.lib.particle import ActiveParticles
from sekai.lib.skin import ActiveSkin, StageSpriteSet


class JudgeLineStyle(IntEnum):
    PRIMARY = 0
    SECONDARY = 1
    ACCENT = 2


class DivisionParity(IntEnum):
    EVEN = 0
    ODD = 1


class StageBorderStyle(IntEnum):
    STANDARD = 0
    LIGHT = 1
    DISABLED = 2


def draw_stage_and_accessories():
    draw_basic_stage()
    draw_stage_cover()


type Transition[T] = tuple[T, T] | T


def normalize_transition[T](transition: Transition[T]) -> tuple[T, T]:
    if isinstance(transition, tuple):
        return transition
    return (transition, transition)


def draw_basic_stage():
    if not Options.show_lane:
        return
    if ActiveSkin.sekai_stage.is_available and not LevelConfig.dynamic_stages:
        draw_sekai_stage()
    else:
        draw_dynamic_stage(
            lane=0,
            width=6,
            anchor_lane=0,
            division_size=2,
            division_parity=DivisionParity.EVEN,
            judge_line_style=JudgeLineStyle.PRIMARY,
            left_border_style=StageBorderStyle.STANDARD,
            right_border_style=StageBorderStyle.STANDARD,
            progress=1,
            order=0,
            a=1,
        )


def draw_sekai_stage():
    layout = layout_sekai_stage()
    ActiveSkin.sekai_stage.draw(layout, z=get_z(LAYER_STAGE))


def get_stage_sprites(judge_line_style: JudgeLineStyle) -> StageSpriteSet:
    result = +StageSpriteSet
    match judge_line_style:
        case JudgeLineStyle.PRIMARY:
            result @= ActiveSkin.stage_primary
        case JudgeLineStyle.SECONDARY:
            result @= ActiveSkin.stage_secondary
        case JudgeLineStyle.ACCENT:
            result @= ActiveSkin.stage_accent
        case _:
            assert_never(judge_line_style)
    return result


def draw_dynamic_stage(
    lane: float,
    width: float,
    anchor_lane: float,
    division_size: Transition[int],
    division_parity: Transition[DivisionParity],
    judge_line_style: Transition[JudgeLineStyle],
    left_border_style: Transition[StageBorderStyle],
    right_border_style: Transition[StageBorderStyle],
    progress: float,
    order: int,
    a: float,
):
    division_size_a, division_size_b = normalize_transition(division_size)
    division_parity_a, division_parity_b = normalize_transition(division_parity)
    judge_line_style_a, judge_line_style_b = normalize_transition(judge_line_style)
    left_border_style_a, left_border_style_b = normalize_transition(left_border_style)
    right_border_style_a, right_border_style_b = normalize_transition(right_border_style)

    sprites_same = judge_line_style_a == judge_line_style_b
    sprites_a = get_stage_sprites(judge_line_style_a)
    sprites_b = get_stage_sprites(judge_line_style_b)

    if not sprites_b.available:
        draw_fallback_stage(lane, width, division_size_b, division_parity_b, anchor_lane, order, a)
        return

    l = lane - width
    r = lane + width
    z_bg0 = get_z_alt(LAYER_STAGE, order * 6)
    z_bg1 = get_z_alt(LAYER_STAGE, order * 6 + 1)
    z_a0 = get_z_alt(LAYER_STAGE, order * 6 + 2)
    z_a1 = get_z_alt(LAYER_STAGE, order * 6 + 3)
    z_b0 = get_z_alt(LAYER_STAGE, order * 6 + 4)
    z_b1 = get_z_alt(LAYER_STAGE, order * 6 + 5)

    f = 5  # sizing factor for judge line border

    def draw_left_border(sprites: StageSpriteSet, style: StageBorderStyle, z: float, a: float):
        match style:
            case StageBorderStyle.STANDARD:
                layout_b = layout_lane_by_edges(l - 0.08, l)  # Artificially thicken the top so it renders better
                layout_t = layout_lane_by_edges(l - 0.64, l)
                sprites.stage_border.draw(
                    Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z, a=a
                )
            case StageBorderStyle.LIGHT:
                layout_b = layout_lane_by_edges(l - 0.0125, l + 0.0125)
                layout_t = layout_lane_by_edges(l - 0.1, l + 0.1)
                sprites.lane_divider.draw(
                    Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z, a=a
                )
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_right_border(sprites: StageSpriteSet, style: StageBorderStyle, z: float, a: float):
        match style:
            case StageBorderStyle.STANDARD:
                layout_b = layout_lane_by_edges(r + 0.08, r)  # Flip horizontally
                layout_t = layout_lane_by_edges(r + 0.64, r)
                sprites.stage_border.draw(
                    Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z, a=a
                )
            case StageBorderStyle.LIGHT:
                layout_b = layout_lane_by_edges(r - 0.0125, r + 0.0125)
                layout_t = layout_lane_by_edges(r - 0.1, r + 0.1)
                sprites.lane_divider.draw(
                    Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z, a=a
                )
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_dividers(sprites: StageSpriteSet, division_size: int, parity: DivisionParity, anchor: float, z_lo: float, z_hi: float, a: float):
        eps = 0.001
        parity_offset = division_size / 2 if parity == DivisionParity.ODD else 0
        shifted_anchor = anchor + parity_offset

        # Subdivision lines: every 1 unit aligned to shifted anchor
        k_start = floor(l - shifted_anchor + eps) + 1
        k_end = ceil(r - shifted_anchor - eps) - 1

        for k in range(k_start, k_end + 1):
            pos = shifted_anchor + k

            # Draw division line if division_size > 0 and position aligns
            if division_size > 0 and k % division_size == 0:
                div_layout_b = layout_lane_by_edges(pos - 0.0125, pos + 0.0125)
                div_layout_t = layout_lane_by_edges(pos - 0.1, pos + 0.1)
                sprites.lane_divider.draw(
                    Quad(bl=div_layout_b.bl, tl=div_layout_t.tl, tr=div_layout_t.tr, br=div_layout_b.br), z=z_lo, a=a
                )

            # Draw subdivision tick on judgment line
            div_layout = perspective_rect(
                pos - 0.01, pos + 0.01, 1 - DynamicLayout.note_h, 1 + DynamicLayout.note_h
            )
            edge_weight = abs(pos - lane) / width if width > 0 else 0
            sprites.judgment_center.draw(div_layout, z=z_lo, a=a)
            sprites.judgment_edge.draw(div_layout, z=z_hi, a=a * edge_weight)

    def draw_left_judgment_border(sprites: StageSpriteSet, style: StageBorderStyle, z: float, a: float):
        match style:
            case StageBorderStyle.STANDARD:
                layout = perspective_rect(
                    l,
                    l + 1 / f / 2,
                    1 - DynamicLayout.note_h + DynamicLayout.note_h / f,
                    1 + DynamicLayout.note_h - DynamicLayout.note_h / f,
                )
                sprites.judgment_edge.draw(layout, z=z, a=a)
            case StageBorderStyle.LIGHT:
                layout = perspective_rect(l - 0.01, l + 0.01, 1 - DynamicLayout.note_h, 1 + DynamicLayout.note_h)
                sprites.judgment_edge.draw(layout, z=z, a=a)
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_right_judgment_border(sprites: StageSpriteSet, style: StageBorderStyle, z: float, a: float):
        match style:
            case StageBorderStyle.STANDARD:
                layout = perspective_rect(
                    r - 1 / f / 2,
                    r,
                    1 - DynamicLayout.note_h + DynamicLayout.note_h / f,
                    1 + DynamicLayout.note_h - DynamicLayout.note_h / f,
                )
                sprites.judgment_edge.draw(layout, z=z, a=a)
            case StageBorderStyle.LIGHT:
                layout = perspective_rect(r - 0.01, r + 0.01, 1 - DynamicLayout.note_h, 1 + DynamicLayout.note_h)
                sprites.judgment_edge.draw(layout, z=z, a=a)
            case StageBorderStyle.DISABLED:
                pass
            case _:
                assert_never(style)

    def draw_gradient(sprites: StageSpriteSet, z: float, a: float):
        layout = perspective_rect(
            l, lane, 1 + DynamicLayout.note_h - DynamicLayout.note_h / f, 1 + DynamicLayout.note_h
        )
        sprites.judgment_gradient.draw(layout, z=z, a=a)
        layout = perspective_rect(
            r, lane, 1 + DynamicLayout.note_h - DynamicLayout.note_h / f, 1 + DynamicLayout.note_h
        )
        sprites.judgment_gradient.draw(layout, z=z, a=a)
        layout = perspective_rect(
            l, lane, 1 - DynamicLayout.note_h, 1 - DynamicLayout.note_h + DynamicLayout.note_h / f
        )
        sprites.judgment_gradient.draw(layout, z=z, a=a)
        layout = perspective_rect(
            r, lane, 1 - DynamicLayout.note_h, 1 - DynamicLayout.note_h + DynamicLayout.note_h / f
        )
        sprites.judgment_gradient.draw(layout, z=z, a=a)

    sprites_a.lane_background.draw(layout_lane_by_edges(l, r), z=z_bg0, a=a)
    sprites_a.judgment_background.draw(
        perspective_rect(l, r, 1 - DynamicLayout.note_h, 1 + DynamicLayout.note_h), z=z_bg1, a=a
    )

    if left_border_style_a == left_border_style_b:
        draw_left_border(sprites_a, left_border_style_a, z_a0, a)
    else:
        draw_left_border(sprites_a, left_border_style_a, z_a0, a * (1 - progress))
        draw_left_border(sprites_b, left_border_style_b, z_b0, a * progress)

    if right_border_style_a == right_border_style_b:
        draw_right_border(sprites_a, right_border_style_a, z_a0, a)
    else:
        draw_right_border(sprites_a, right_border_style_a, z_a0, a * (1 - progress))
        draw_right_border(sprites_b, right_border_style_b, z_b0, a * progress)

    if division_size_a == division_size_b and division_parity_a == division_parity_b and sprites_same:
        draw_dividers(sprites_a, division_size_a, division_parity_a, anchor_lane, z_a0, z_a1, a)
    else:
        draw_dividers(sprites_a, division_size_a, division_parity_a, anchor_lane, z_a0, z_a1, a * (1 - progress))
        draw_dividers(sprites_b, division_size_b, division_parity_b, anchor_lane, z_b0, z_b1, a * progress)

    if sprites_same:
        draw_gradient(sprites_a, z_a0, a)
    else:
        draw_gradient(sprites_a, z_a0, a * (1 - progress))
        draw_gradient(sprites_b, z_b0, a * progress)

    if left_border_style_a == left_border_style_b and sprites_same:
        draw_left_judgment_border(sprites_a, left_border_style_a, z_a0, a)
    else:
        draw_left_judgment_border(sprites_a, left_border_style_a, z_a0, a * (1 - progress))
        draw_left_judgment_border(sprites_b, left_border_style_b, z_b0, a * progress)

    if right_border_style_a == right_border_style_b and sprites_same:
        draw_right_judgment_border(sprites_a, right_border_style_a, z_a0, a)
    else:
        draw_right_judgment_border(sprites_a, right_border_style_a, z_a0, a * (1 - progress))
        draw_right_judgment_border(sprites_b, right_border_style_b, z_b0, a * progress)


def draw_fallback_stage(lane: float, width: float, division_size: int, parity: DivisionParity, anchor: float, z: int, a: float):
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
    shifted_anchor = anchor + parity_offset
    prev = l
    if division_size > 0:
        k_start = floor((l - shifted_anchor + eps) / division_size) + 1
        k_end = ceil((r - shifted_anchor - eps) / division_size) - 1
        for k in range(k_start, k_end + 1):
            pos = shifted_anchor + k * division_size
            ActiveSkin.lane.draw(layout_lane_by_edges(prev, pos), a=a, z=z_lo)
            prev = pos
    ActiveSkin.lane.draw(layout_lane_by_edges(prev, r), a=a, z=z_lo)

    layout = perspective_rect(l, r, t=1 - DynamicLayout.note_h, b=1 + DynamicLayout.note_h)
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
