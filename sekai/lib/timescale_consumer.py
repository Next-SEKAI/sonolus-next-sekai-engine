"""Compute note progress and visibility using each drawing entity's own caches."""

from typing import Any

from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.interval import Interval, lerp

from sekai.lib.ease import safe_unlerp_clamped
from sekai.lib.stage import stage_y_offset_bounds
from sekai.lib.timescale import (
    TrajectoryCache,
    evaluate_trajectory,
    group_preempt_time,
    prepare_trajectory,
    register_group_window,
)
from sekai.lib.timescale_visibility import VisibilitySource, get_sources_visual_spawn_time


def register_note_group_window(note: Any, start: float, end: float) -> None:
    """Keep the note's group and its attachment groups active for the caller."""
    register_group_window(note.timescale_group, start, end)
    if note.is_attached:
        # An anchor's group must stay active while another entity draws it,
        # even if the anchor never spawns.
        register_group_window(note.attach_head_ref.get().timescale_group, start, end)
        register_group_window(note.attach_tail_ref.get().timescale_group, start, end)


def prepare_note_trajectories(note: Any, first: TrajectoryCache, second: TrajectoryCache, now: float) -> None:
    if note.is_attached:
        head = note.attach_head_ref.get()
        tail = note.attach_tail_ref.get()
        if now < head.target_time:
            prepare_trajectory(head.timescale_group, head.target_time, head.target_position, first, now)
        prepare_trajectory(tail.timescale_group, tail.target_time, tail.target_position, second, now)
    else:
        prepare_trajectory(note.timescale_group, note.target_time, note.target_position, first, now)


def _basic_progress(note: Any, cache: TrajectoryCache, now: float) -> float:
    distance = evaluate_trajectory(note.timescale_group, note.target_time, note.target_position, cache, now)
    return 1.0 - distance / group_preempt_time(note.timescale_group)


def note_progress(note: Any, first: TrajectoryCache, second: TrajectoryCache, now: float) -> float:
    """Compute note progress from endpoint data and the caller's trajectory caches."""
    if not note.is_attached:
        return _basic_progress(note, first, now)
    head = note.attach_head_ref.get()
    tail = note.attach_tail_ref.get()
    head_progress = _basic_progress(head, first, now) if now < head.target_time else 1.0
    tail_progress = _basic_progress(tail, second, now)
    head_frac = 0.0 if now < head.target_time else safe_unlerp_clamped(head.target_time, tail.target_time, now)
    target_frac = safe_unlerp_clamped(head.target_time, tail.target_time, note.target_time)
    return lerp(head_progress, tail_progress, safe_unlerp_clamped(head_frac, 1.0, target_frac))


def note_visual_progress(note: Any, first: TrajectoryCache, second: TrajectoryCache, now: float) -> float:
    return note_progress(note, first, second, now) - note.visual_y_offset


def basic_note_offset_bounds(note: Any) -> Interval:
    result = Interval(0, 0)
    if note.stage_ref.index > 0:
        result @= stage_y_offset_bounds(note.stage_ref.get())
    return result


def note_offset_bounds(note: Any) -> Interval:
    result = +Interval
    if note.is_attached:
        head = basic_note_offset_bounds(note.attach_head_ref.get())
        tail = basic_note_offset_bounds(note.attach_tail_ref.get())
        result @= Interval(min(head.start, tail.start), max(head.end, tail.end))
    else:
        result @= basic_note_offset_bounds(note)
    return result


def _append_visibility_source(
    note: Any, sources: VarArray[VisibilitySource, Dim[4]], offsets: Interval, clamp_after_hit: bool
) -> None:
    sources.append(
        VisibilitySource(
            note.timescale_group.index,
            note.target_time,
            group_preempt_time(note.timescale_group),
            offsets.start,
            offsets.end,
            clamp_after_hit,
        )
    )


def append_note_visibility_sources(note: Any, sources: VarArray[VisibilitySource, Dim[4]]) -> None:
    offsets = note_offset_bounds(note)
    if note.is_attached:
        # Progress and offset use different interpolation fractions after the
        # head's hit time. Both sources need the attached note's full offset range.
        _append_visibility_source(note.attach_head_ref.get(), sources, offsets, True)
        _append_visibility_source(note.attach_tail_ref.get(), sources, offsets, False)
    else:
        _append_visibility_source(note, sources, offsets, False)


def note_visual_spawn_time(note: Any, latest: float) -> float:
    sources = +VarArray[VisibilitySource, Dim[4]]
    append_note_visibility_sources(note, sources)
    return get_sources_visual_spawn_time(sources, latest)


def segment_visual_spawn_time(head: Any, tail: Any, latest: float) -> float:
    sources = +VarArray[VisibilitySource, Dim[4]]
    append_note_visibility_sources(head, sources)
    append_note_visibility_sources(tail, sources)
    return get_sources_visual_spawn_time(sources, latest)
