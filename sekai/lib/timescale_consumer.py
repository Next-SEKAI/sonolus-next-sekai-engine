"""Trajectory evaluation using caches owned by the entity doing the drawing."""

from math import inf
from typing import Any

from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.debug import error
from sonolus.script.interval import Interval
from sonolus.script.record import Record

from sekai.lib.layout import DynamicLayout, conservative_progress_bounds
from sekai.lib.stage import stage_y_offset_bounds
from sekai.lib.timescale import (
    CacheKind,
    TargetPosition,
    TrajectoryCache,
    TransitionStyle,
    complete_trajectory_refresh,
    evaluate_trajectory,
    group_preempt_time,
    prepared_time_matches,
    register_group_window,
    timescale_change_archetype,
    timescale_group_archetype,
    try_prepare_trajectory,
)
from sekai.lib.timescale_math import (
    AccurateScalar,
    clamped_fraction,
    native_affine_progress,
    native_constant_progress,
    native_difference_progress,
    native_scroll_progress,
    published_progress,
)
from sekai.lib.timescale_visibility import VisibilitySource, get_sources_visual_spawn_time

MAX_PROGRESS_ERROR = 1e-4


class TrajectoryDiagnostics(Record):
    accurate_refinements: int
    uncertified_results: int


def register_note_group_window(note: Any, start: float, end: float) -> None:
    """Keep trajectory sources and the note's separate hide group active."""
    register_group_window(note.timescale_group, start, end)
    if note.is_attached:
        # Endpoints may be anchors that never spawn themselves. Their groups
        # must cover the drawing consumer's lifetime, not their own hit times.
        register_group_window(note.attach_head_ref.get().timescale_group, start, end)
        register_group_window(note.attach_tail_ref.get().timescale_group, start, end)


def prepare_note_trajectories(note: Any, first: TrajectoryCache, second: TrajectoryCache, now: float) -> None:
    """Prepare private caches after the groups' early sequential update."""
    if note.is_attached:
        head = note.attach_head_ref.get()
        tail = note.attach_tail_ref.get()
        first_ready = try_prepare_trajectory(
            head.timescale_group, head.target_time, head.target_position, first, now, head.index,
        )
        second_ready = try_prepare_trajectory(
            tail.timescale_group, tail.target_time, tail.target_position, second, now, tail.index,
        )
        if first_ready and second_ready:
            return
    else:
        first_ready = try_prepare_trajectory(
            note.timescale_group, note.target_time, note.target_position, first, now, note.index,
        )
        if first_ready:
            return
        second_ready = True

    # Hits and accepted rolling updates return above. Share the large tree-query
    # kernel only for unresolved refreshes; scratch copies and iteration are cold.
    # While invalid, each pending cache stores its error allowance in value.hi.
    for slot in range(1 if first_ready else 0, 1 if second_ready else 2):
        group = 0
        hit_time = 0.0
        target = +TargetPosition
        pending = +TrajectoryCache
        if slot == 0:
            pending @= first
            if note.is_attached:
                head = note.attach_head_ref.get()
                group = head.timescale_group.index
                hit_time = head.target_time
                target @= head.target_position
            else:
                group = note.timescale_group.index
                hit_time = note.target_time
                target @= note.target_position
        else:
            pending @= second
            tail = note.attach_tail_ref.get()
            group = tail.timescale_group.index
            hit_time = tail.target_time
            target @= tail.target_position
        complete_trajectory_refresh(group, hit_time, target, pending)
        if slot == 0:
            first @= pending
        else:
            second @= pending


def basic_note_distance_fraction(
    note: Any, cache: TrajectoryCache, now: float, accurate: bool = False
) -> AccurateScalar:
    distance = evaluate_trajectory(
        note.timescale_group, note.target_time, note.target_position, cache, now, accurate=accurate
    )
    preempt = AccurateScalar.of(group_preempt_time(note.timescale_group))
    result = +AccurateScalar
    if accurate:
        result @= distance.div(preempt)
    else:
        result @= distance.published_div(preempt)
    return result


def attachment_remaining(
    head_remaining: AccurateScalar,
    tail_remaining: AccurateScalar,
    head_target_time: float,
    tail_target_time: float,
    target_time: float,
    now: float,
    accurate: bool,
) -> AccurateScalar:
    """Preserve attachment fractions and certify their contribution to distance."""
    head_time = AccurateScalar.of(head_target_time)
    tail_time = AccurateScalar.of(tail_target_time)
    head_frac = AccurateScalar.of(0)
    if now >= head_target_time:
        head_frac @= clamped_fraction(head_time, tail_time, AccurateScalar.of(now), accurate=accurate)
    target_frac = clamped_fraction(head_time, tail_time, AccurateScalar.of(target_time), accurate=accurate)
    frac = +target_frac
    if now >= head_target_time:
        frac @= clamped_fraction(head_frac, AccurateScalar.of(1), target_frac, accurate=accurate)
    remaining = +AccurateScalar
    # Combine in extended range before materializing either endpoint.
    if accurate:
        remaining @= head_remaining.mul(AccurateScalar.of(1).sub(frac)).add(tail_remaining.mul(frac))
    else:
        remaining @= head_remaining.published_mul(AccurateScalar.of(1).published_add(frac.neg())).published_add(
            tail_remaining.published_mul(frac)
        )
    return remaining


def _note_progress(
    note: Any, first: TrajectoryCache, second: TrajectoryCache, now: float, accurate: bool
) -> AccurateScalar:
    remaining = +AccurateScalar
    if note.is_attached:
        head = note.attach_head_ref.get()
        tail = note.attach_tail_ref.get()
        head_remaining = AccurateScalar.of(0)
        if now < head.target_time:
            head_remaining @= basic_note_distance_fraction(head, first, now, accurate)
        tail_remaining = basic_note_distance_fraction(tail, second, now, accurate)
        remaining @= attachment_remaining(
            head_remaining, tail_remaining, head.target_time, tail.target_time, note.target_time, now, accurate
        )
    else:
        remaining @= basic_note_distance_fraction(note, first, now, accurate)
    result = +AccurateScalar
    if accurate:
        result @= AccurateScalar.of(1).sub(remaining)
    else:
        result @= AccurateScalar.of(1).published_add(remaining.neg())
    return result


def _needs_refinement(value: AccurateScalar, visual_offset: float) -> bool:
    if value.error_at_most(MAX_PROGRESS_ERROR):
        return False
    bounds = conservative_progress_bounds()
    lower = AccurateScalar.of(bounds.start).add(AccurateScalar.of(visual_offset))
    upper = AccurateScalar.of(bounds.end).add(AccurateScalar.of(visual_offset))
    return not value.definitely_less(lower) and not value.definitely_greater(upper)


def _consumer_progress(
    note: Any,
    first: TrajectoryCache,
    second: TrajectoryCache,
    now: float,
    visual: bool,
    diagnostics: TrajectoryDiagnostics | None,
) -> AccurateScalar:
    """Publish a cheap result, refining only an uncertain potentially visible one."""
    offset = note.visual_y_offset
    result = +AccurateScalar
    if note.is_attached:
        result @= _note_progress(note, first, second, now, False)
        if visual:
            result @= result.published_add(AccurateScalar.of(-offset))
    else:
        distance = evaluate_trajectory(note.timescale_group, note.target_time, note.target_position, first, now)
        result @= published_progress(
            distance,
            group_preempt_time(note.timescale_group),
            offset if visual else 0.0,
        )
    clipping_offset = 0.0 if visual else offset
    if _needs_refinement(result, clipping_offset):
        if diagnostics is not None:
            diagnostics.accurate_refinements += 1
        # This uses the stored accurate cache and current group coefficients. It
        # never walks a tree or modifies source caches during rendering.
        result @= _note_progress(note, first, second, now, True)
        if visual:
            result @= result.sub(AccurateScalar.of(offset))
        # Publishing includes the discarded low component in the certificate;
        # the final ordinary scalar conversion must not add an unbudgeted sum.
        result @= result.published()
        if _needs_refinement(result, clipping_offset):
            if diagnostics is not None:
                diagnostics.uncertified_results += 1
            error("Timescale consumer cannot certify visible progress")
    return result


def note_progress_value(
    note: Any,
    first: TrajectoryCache,
    second: TrajectoryCache,
    now: float,
    diagnostics: TrajectoryDiagnostics | None = None,
) -> AccurateScalar:
    """Read source metadata while using only the drawing entity's private caches."""
    return _consumer_progress(note, first, second, now, False, diagnostics)


def note_visual_progress_value(
    note: Any,
    first: TrajectoryCache,
    second: TrajectoryCache,
    now: float,
    diagnostics: TrajectoryDiagnostics | None = None,
) -> AccurateScalar:
    return _consumer_progress(note, first, second, now, True, diagnostics)


def note_visual_progress(
    note: Any,
    first: TrajectoryCache,
    second: TrajectoryCache,
    now: float,
    diagnostics: TrajectoryDiagnostics | None = None,
) -> float:
    return note_visual_progress_value(note, first, second, now, diagnostics).to_float()


def note_draw_progress(
    note: Any,
    first: TrajectoryCache,
    second: TrajectoryCache,
    now: float,
    diagnostics: TrajectoryDiagnostics | None = None,
) -> float:
    """Certify ordinary note geometry without constructing a scaled number.

    Endpoint consumers retain their scaled values for cancellation. A note's own
    body only needs a visible scalar or a proven offscreen sentinel.
    """
    assert first.valid, "Trajectory must be prepared by its consumer before drawing"
    if not note.is_attached:
        constant = False
        speed = 1.0
        if first.kind in (CacheKind.IDENTITY, CacheKind.PRELUDE):
            constant = True
        elif first.kind == CacheKind.SAME:
            group = timescale_group_archetype().at(note.timescale_group.index)
            assert group.valid
            assert group.time_valid
            assert prepared_time_matches(group.last_updated, now)
            assert group.current_run == first.run_ref
            if group.current_constant and group.current_event == note.target_position.event_ref:
                constant = True
                speed = group.current_speed
            elif timescale_change_archetype().at(group.current_event).transition_style == TransitionStyle.SCROLL:
                scroll = native_scroll_progress(
                    note.target_time, now, group.certified_current_speed,
                    group.effective_preempt, note.visual_y_offset,
                )
                if scroll.error <= MAX_PROGRESS_ERROR:
                    return scroll.value
                if scroll.value + 2 * scroll.error < DynamicLayout.progress_start:
                    return -inf
                if scroll.value - 2 * scroll.error > DynamicLayout.progress_cutoff:
                    return inf
            elif (
                -60 <= first.value.exponent <= 60 and -60 <= group.past_distance.exponent <= 60
                and 2.0**-30 <= group.effective_preempt <= 2.0**30 and abs(note.visual_y_offset) <= 2.0**60
            ):
                difference = native_difference_progress(
                    first.value, group.past_distance, group.effective_preempt, note.visual_y_offset
                )
                if difference.error <= MAX_PROGRESS_ERROR:
                    return difference.value
                if difference.value + 2 * difference.error < DynamicLayout.progress_start:
                    return -inf
                if difference.value - 2 * difference.error > DynamicLayout.progress_cutoff:
                    return inf
        elif first.kind in (CacheKind.FUTURE, CacheKind.PAST):
            affine_group = timescale_group_archetype().at(note.timescale_group.index)
            assert affine_group.valid
            assert affine_group.time_valid
            assert prepared_time_matches(affine_group.last_updated, now)
            assert affine_group.current_run == first.run_ref
            past = first.kind == CacheKind.PAST
            distance = +affine_group.future_distance
            # TIMESCALE groups reuse their ratio slots for curve coefficients.
            ratio = AccurateScalar.of(1)
            if past:
                distance @= affine_group.past_distance
            if timescale_change_archetype().at(affine_group.current_event).transition_style == TransitionStyle.SCROLL:
                if past:
                    ratio @= affine_group.past_ratio
                else:
                    ratio @= affine_group.future_ratio
            if (
                -60 <= first.value.exponent <= 60 and -60 <= distance.exponent <= 60
                and -10 <= ratio.exponent <= 10 and 2.0**-30 <= affine_group.effective_preempt <= 2.0**30
                and abs(note.visual_y_offset) <= 2.0**60
            ):
                affine = native_affine_progress(
                    first.value, ratio, distance, affine_group.effective_preempt, note.visual_y_offset, past
                )
                if affine.error <= MAX_PROGRESS_ERROR:
                    return affine.value
                if affine.value + 2 * affine.error < DynamicLayout.progress_start:
                    return -inf
                if affine.value - 2 * affine.error > DynamicLayout.progress_cutoff:
                    return inf
        if constant:
            preempt = group_preempt_time(note.timescale_group)
            offset = note.visual_y_offset
            if note.native_progress_certified and abs(now) <= 2.0**30:
                return 1.0 - ((note.target_time - now) * speed) / preempt - offset
            if (
                abs(note.target_time) <= 2.0**30 and abs(now) <= 2.0**30
                and abs(speed) <= 2.0**30 and 2.0**-30 <= preempt <= 2.0**30 and abs(offset) <= 2.0**60
            ):
                native = native_constant_progress(note.target_time, now, speed, preempt, offset)
                if native.error <= MAX_PROGRESS_ERROR:
                    return native.value
                # Compare with outward slack so the ordinary subtraction used
                # for clipping cannot invalidate an otherwise sound interval.
                slack = native.error * 2
                if native.value + slack < DynamicLayout.progress_start:
                    return -inf
                if native.value - slack > DynamicLayout.progress_cutoff:
                    return inf
    value = note_visual_progress_value(note, first, second, now, diagnostics)
    if value.definitely_less(AccurateScalar.of(DynamicLayout.progress_start)):
        return -inf
    if value.definitely_greater(AccurateScalar.of(DynamicLayout.progress_cutoff)):
        return inf
    return value.to_float()


def certify_note_native_progress(note: Any) -> bool:
    """Prove the native constant formula throughout this note's visible region.

    For binary32 unit roundoff u, substituting the final visible magnitude M
    and full animated offset magnitude O into the five rounded operations gives
    error <= 8u(1+O+M)(1+16u). This holds for either the computed or exact result
    inside the draw interval, including an apparent crossing of its boundary.
    """
    if note.is_attached or abs(note.target_time) > 2.0**30:
        return False
    if note.target_position.event_ref > 0:
        marker = timescale_change_archetype().at(note.target_position.event_ref)
        if abs(marker.timescale) > 2.0**30:
            return False
    preempt = group_preempt_time(note.timescale_group)
    if not 2.0**-30 <= preempt <= 2.0**30:
        return False
    offsets = note_offset_bounds(note)
    bounds = conservative_progress_bounds()
    magnitude = max(abs(bounds.start), abs(bounds.end))
    offset = max(abs(offsets.start), abs(offsets.end))
    if offset > 2.0**60:
        return False
    # The extra outward factor covers rounding the certificate itself; 2^-60
    # also covers flushed subnormals throughout the supported native ranges.
    bound = (8 * 2.0**-24) * (1 + offset + magnitude) * (1 + 32 * 2.0**-24) + 2.0**-60
    return bound <= MAX_PROGRESS_ERROR


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


def append_note_visibility_sources(note: Any, sources: VarArray[VisibilitySource, Dim[4]]) -> None:
    offsets = note_offset_bounds(note)
    if note.is_attached:
        head = note.attach_head_ref.get()
        tail = note.attach_tail_ref.get()
        # Offset interpolation has a different fraction after the head hit. Apply
        # the note's complete offset enclosure to both progress sources.
        sources.append(
            VisibilitySource(
                head.timescale_group.index,
                head.target_time,
                group_preempt_time(head.timescale_group),
                offsets.start,
                offsets.end,
                True,
            )
        )
        sources.append(
            VisibilitySource(
                tail.timescale_group.index,
                tail.target_time,
                group_preempt_time(tail.timescale_group),
                offsets.start,
                offsets.end,
                False,
            )
        )
    else:
        sources.append(
            VisibilitySource(
                note.timescale_group.index,
                note.target_time,
                group_preempt_time(note.timescale_group),
                offsets.start,
                offsets.end,
                False,
            )
        )


def note_visual_spawn_time(note: Any, latest: float) -> float:
    sources = +VarArray[VisibilitySource, Dim[4]]
    append_note_visibility_sources(note, sources)
    return get_sources_visual_spawn_time(sources, latest)


def segment_visual_spawn_time(head: Any, tail: Any, latest: float) -> float:
    sources = +VarArray[VisibilitySource, Dim[4]]
    append_note_visibility_sources(head, sources)
    append_note_visibility_sources(tail, sources)
    return get_sources_visual_spawn_time(sources, latest)
