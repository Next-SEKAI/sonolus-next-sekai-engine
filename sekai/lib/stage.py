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


def draw_stage_and_accessories():
    draw_stage()
    draw_stage_cover()


def draw_stage():
    if not Options.show_lane:
        return
    if ActiveSkin.sekai_stage.is_available and not LevelConfig.dynamic_stages:
        draw_sekai_stage()
    else:
        draw_dynamic_stage(
            ActiveSkin.dynamic_stage_primary,
            lane=0,
            width=6,
            divisions=6,
            subdivisions=2,
            z=0,
            a=1,
        )


def draw_sekai_stage():
    layout = layout_sekai_stage()
    ActiveSkin.sekai_stage.draw(layout, z=get_z(LAYER_STAGE))


def draw_dynamic_stage(
    sprites: StageSpriteSet, lane: float, width: float, divisions: int, subdivisions: int, z: int, a: float
):
    if not sprites.available:
        draw_fallback_dynamic_stage(lane, width, divisions, z, a)
        return

    l = lane - width
    r = lane + width
    z0 = get_z_alt(LAYER_STAGE, z * 4)
    z1 = get_z_alt(LAYER_STAGE, z * 4 + 1)
    z2 = get_z_alt(LAYER_STAGE, z * 4 + 2)
    z3 = get_z_alt(LAYER_STAGE, z * 4 + 3)
    layout_b = layout_lane_by_edges(l - 0.08, l)  # Artificially thicken the top so it renders better
    layout_t = layout_lane_by_edges(l - 0.64, l)
    sprites.stage_border.draw(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z2, a=a)
    layout_b = layout_lane_by_edges(r + 0.08, r)  # Flip horizontally
    layout_t = layout_lane_by_edges(r + 0.64, r)
    sprites.stage_border.draw(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br), z=z2, a=a)

    lane_w = 2 * width / divisions
    subdiv_w = lane_w / subdivisions
    total_subdivs = divisions * subdivisions
    half_subdivs = total_subdivs / 2
    for i in range(divisions):
        lane_l = l + i * lane_w
        if i > 0:
            div_layout_b = layout_lane_by_edges(lane_l - 0.0125, lane_l + 0.0125)
            div_layout_t = layout_lane_by_edges(lane_l - 0.1, lane_l + 0.1)
            sprites.lane_divider.draw(
                Quad(bl=div_layout_b.bl, tl=div_layout_t.tl, tr=div_layout_t.tr, br=div_layout_b.br), z=z2, a=a
            )
        for j in range(subdivisions):
            subdiv_l = lane_l + j * subdiv_w
            if i == 0 and j == 0:
                pass
            else:
                div_layout = perspective_rect(
                    subdiv_l - 0.01, subdiv_l + 0.01, 1 - DynamicLayout.note_h, 1 + DynamicLayout.note_h
                )
                edge_weight = abs(half_subdivs - (i * subdivisions + j)) / half_subdivs
                sprites.judgment_center.draw(div_layout, z=z2, a=a)
                sprites.judgment_edge.draw(div_layout, z=z3, a=a * edge_weight)

    sprites.lane_background.draw(layout_lane_by_edges(l, r), z=z0, a=a)

    layout = perspective_rect(l, r, 1 - DynamicLayout.note_h, 1 + DynamicLayout.note_h)
    sprites.judgment_background.draw(layout, z=z1, a=a)

    f = 5
    layout = perspective_rect(l, lane, 1 + DynamicLayout.note_h - DynamicLayout.note_h / f, 1 + DynamicLayout.note_h)
    sprites.judgment_gradient.draw(layout, z=z2, a=a)
    layout = perspective_rect(r, lane, 1 + DynamicLayout.note_h - DynamicLayout.note_h / f, 1 + DynamicLayout.note_h)
    sprites.judgment_gradient.draw(layout, z=z2, a=a)
    layout = perspective_rect(l, lane, 1 - DynamicLayout.note_h, 1 - DynamicLayout.note_h + DynamicLayout.note_h / f)
    sprites.judgment_gradient.draw(layout, z=z2, a=a)
    layout = perspective_rect(r, lane, 1 - DynamicLayout.note_h, 1 - DynamicLayout.note_h + DynamicLayout.note_h / f)
    sprites.judgment_gradient.draw(layout, z=z2, a=a)
    layout = perspective_rect(
        l,
        l + 1 / f / 2,
        1 - DynamicLayout.note_h + DynamicLayout.note_h / f,
        1 + DynamicLayout.note_h - DynamicLayout.note_h / f,
    )
    sprites.judgment_edge.draw(layout, z=z2, a=a)
    layout = perspective_rect(
        r - 1 / f / 2,
        r,
        1 - DynamicLayout.note_h + DynamicLayout.note_h / f,
        1 + DynamicLayout.note_h - DynamicLayout.note_h / f,
    )
    sprites.judgment_edge.draw(layout, z=z2, a=a)


def draw_fallback_dynamic_stage(lane: float, width: float, divisions: int, z: int, a: float):
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

    lane_w = 2 * width / divisions
    for i in range(divisions):
        lane_l = l + i * lane_w
        lane_r = lane_l + lane_w
        lane_layout = layout_lane_by_edges(lane_l, lane_r)
        ActiveSkin.lane.draw(lane_layout, a=a, z=z_lo)

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
