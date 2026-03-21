from typing import assert_never

from sonolus.script.quad import Quad

from sekai.lib.effect import SFX_DISTANCE, Effects
from sekai.lib.layer import LAYER_COVER, LAYER_JUDGMENT_LINE, LAYER_STAGE, get_z, get_z_alt
from sekai.lib.layout import (
    layout_fallback_judge_line,
    layout_full_width_stage_cover,
    layout_hidden_cover,
    layout_lane,
    layout_lane_by_edges,
    layout_sekai_stage,
    layout_stage_cover,
    layout_stage_cover_and_line, layout_note_body_by_edges, NOTE_H, perspective_rect,
)
from sekai.lib.options import Options, StageCoverMode
from sekai.lib.particle import ActiveParticles
from sekai.lib.skin import ActiveSkin, StageSpriteSet


def draw_stage_and_accessories():
    draw_stage()
    draw_stage_cover()


def draw_stage():
    if not Options.show_lane:
        return
    draw_dynamic_stage(
        ActiveSkin.dynamic_stage_primary,
        lane=0,
        width=6,
        divisions=6,
        subdivisions=2,
        z=0,
        a=1,
    )
    return
    if ActiveSkin.sekai_stage.is_available:
        draw_sekai_stage()
    else:
        draw_fallback_stage()


def draw_sekai_stage():
    layout = layout_sekai_stage()
    ActiveSkin.sekai_stage.draw(layout, z=get_z(LAYER_STAGE))


def draw_fallback_stage():
    layout = layout_lane_by_edges(-6.5, -6)
    ActiveSkin.stage_left_border.draw(layout, z=get_z(LAYER_STAGE))
    layout = layout_lane_by_edges(6, 6.5)
    ActiveSkin.stage_right_border.draw(layout, z=get_z(LAYER_STAGE))

    for lane in (-5, -3, -1, 1, 3, 5):
        layout = layout_lane(lane, 1)
        ActiveSkin.lane.draw(layout, z=get_z(LAYER_STAGE))

    layout = layout_fallback_judge_line()
    ActiveSkin.judgment_line.draw(layout, z=get_z(LAYER_JUDGMENT_LINE))


def draw_dynamic_stage(sprites: StageSpriteSet, lane: float, width: float, divisions: int, subdivisions: int, z: int,
                       a: float):
    l = lane - width
    r = lane + width
    z_lo = get_z_alt(LAYER_STAGE, z * 3)
    z_mid = get_z_alt(LAYER_STAGE, z * 3 + 1)
    z_hi = get_z_alt(LAYER_STAGE, z * 3 + 2)
    layout_b = layout_lane_by_edges(l - 0.25, l)  # Artificially thicken the top so it renders better
    layout_t = layout_lane_by_edges(l - 1, l)
    sprites.left_border.draw(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br),
                             z=get_z(LAYER_STAGE, z_mid))
    layout_b = layout_lane_by_edges(r, r + 0.25)
    layout_t = layout_lane_by_edges(r, r + 1)
    sprites.right_border.draw(Quad(bl=layout_b.bl, tl=layout_t.tl, tr=layout_t.tr, br=layout_b.br),
                              z=get_z(LAYER_STAGE, z_mid))

    lane_w = 2 * width / divisions
    subdiv_w = lane_w / subdivisions
    total_subdivs = divisions * subdivisions
    half_subdivs = total_subdivs / 2
    for i in range(divisions):
        lane_l = l + i * lane_w
        if i > 0:
            div_layout_b = layout_lane_by_edges(lane_l - 0.025, lane_l + 0.025)
            div_layout_t = layout_lane_by_edges(lane_l - 0.1, lane_l + 0.1)
            sprites.lane_divider.draw(
                Quad(bl=div_layout_b.bl, tl=div_layout_t.tl, tr=div_layout_t.tr, br=div_layout_b.br),
                z=z_mid, a=a)
        for j in range(subdivisions):
            subdiv_l = lane_l + j * subdiv_w
            if i == 0 and j == 0:
                pass
            else:
                div_layout = perspective_rect(subdiv_l - 0.015, subdiv_l + 0.015, 1 - NOTE_H, 1 + NOTE_H)
                edge_weight = abs(half_subdivs - (i * subdivisions + j)) / half_subdivs
                sprites.judgment_center.draw(div_layout, z=z_mid, a=a)
                sprites.judgment_edge.draw(div_layout, z=z_hi, a=a * edge_weight)

    sprites.middle.draw(layout_lane_by_edges(l, r), z=z_lo, a=a)

    p = 0.02
    f = 5
    layout = perspective_rect(l + p, lane, 1 + NOTE_H - NOTE_H / f, 1 + NOTE_H)
    sprites.judgment_gradient.draw(layout, z=z_mid, a=a)
    layout = perspective_rect(r - p, lane, 1 + NOTE_H - NOTE_H / f, 1 + NOTE_H)
    sprites.judgment_gradient.draw(layout, z=z_mid, a=a)
    layout = perspective_rect(l + p, lane, 1 - NOTE_H, 1 - NOTE_H + NOTE_H / f)
    sprites.judgment_gradient.draw(layout, z=z_mid, a=a)
    layout = perspective_rect(r - p, lane, 1 - NOTE_H, 1 - NOTE_H + NOTE_H / f)
    sprites.judgment_gradient.draw(layout, z=z_mid, a=a)
    layout = perspective_rect(l + p, l + 1 / f / 2, 1 - NOTE_H + NOTE_H / f, 1 + NOTE_H - NOTE_H / f)
    sprites.judgment_edge.draw(layout, z=z_mid, a=a)
    layout = perspective_rect(r - 1 / f / 2, r - p, 1 - NOTE_H + NOTE_H / f, 1 + NOTE_H - NOTE_H / f)
    sprites.judgment_edge.draw(layout, z=z_mid, a=a)

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
