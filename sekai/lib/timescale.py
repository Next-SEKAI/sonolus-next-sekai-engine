"""Local distances and fixed caches at the boundaries of linked style runs."""

from __future__ import annotations

from collections.abc import Iterator
from enum import IntEnum
from math import e, inf, log
from typing import Protocol, Self, cast

from sonolus.script import runtime
from sonolus.script.archetype import EntityRef, entity_info_at, get_archetype_by_name
from sonolus.script.debug import error
from sonolus.script.record import Record
from sonolus.script.timing import beat_to_bpm, beat_to_time

from sekai.lib import archetype_names
from sekai.lib.ease import EaseType
from sekai.lib.layout import Layout, preempt_time
from sekai.lib.options import Options
from sekai.lib.timescale_math import TimePosition, integrate_times, speed_at

MIN_START_TIME = -2.0
DISTANCE_LIMIT = 1e20


class TransitionStyle(IntEnum):
    TIMESCALE = 0
    SCROLL = 1


class TimelineError(IntEnum):
    NONE = 0
    REFERENCE = 1
    OWNERSHIP = 2
    CYCLE = 3
    ORDER = 4
    VALUE = 5
    HYBRID = 6


class TargetPosition(Record):
    event_ref: int
    coordinate: TimePosition


class RunSummary(Record):
    """Logarithms of R, D(left, right), and -D(right, left).

    R is the gain in D(left, hit) = D(left, right) + R * D(right, hit).
    Store reverse distance separately to avoid subtracting large logarithms.
    """

    log_ratio: float
    log_forward: float
    log_backward: float

    def then(self, other: Self) -> Self:
        return type(self)(
            self.log_ratio + other.log_ratio,
            _log_add(self.log_forward, self.log_ratio + other.log_forward),
            _log_add(other.log_backward, -other.log_ratio + self.log_backward),
        )


class TrajectoryCache(Record):
    """D(run_end, hit) for future runs, D(run_start, hit) for past runs.

    Rebuilt only when the current run changes; the value never rolls forward.
    Each owning consumer keeps this cache for one immutable target.
    A zero run_ref is uninitialized, while -1 denotes the prelude.
    """

    run_ref: int
    boundary_distance: float


class TimescaleChangeLike(Protocol):
    id: int
    beat: float
    timescale: float
    timescale_skip: float
    timescale_group: EntityRef
    timescale_ease: EaseType
    transition_style: TransitionStyle
    hide_notes: bool
    next_ref: EntityRef
    event_start: float
    event_end: float
    converted_skip: float
    position: TimePosition
    ordinal: int
    prev_ref: int
    run_first: int
    run_end: int
    prev_run: int
    validation_owner: int
    jump_end: int
    jump_width: int
    jump: RunSummary

    @classmethod
    def at(cls, index: int) -> Self: ...

    @property
    def index(self) -> int: ...


class TimescaleGroupLike(Protocol):
    first_ref: EntityRef
    force_note_speed: float
    valid: bool
    has_scroll: bool
    monotone_targets: bool
    error_code: TimelineError
    used: bool
    effective_preempt: float
    needed_start: float
    needed_end: float
    lookup_ref: int
    current_event: int
    current_run: int
    current_speed: float
    current_constant: bool
    coordinate: TimePosition
    time_valid: bool
    last_updated: float
    future_gain: float
    future_offset: float
    past_gain: float
    past_offset: float
    hide_notes: bool
    event_start: float
    event_end: float
    v0: float
    v1: float
    ease: EaseType
    style: TransitionStyle
    last_spawn_target: float
    last_spawn_ceiling: float
    last_spawn_time: float
    spawn_cursor_valid: bool

    @classmethod
    def at(cls, index: int) -> Self: ...

    @property
    def index(self) -> int: ...


def timescale_change_archetype() -> type[TimescaleChangeLike]:
    return cast(type[TimescaleChangeLike], get_archetype_by_name(archetype_names.TIMESCALE_CHANGE))


def timescale_group_archetype() -> type[TimescaleGroupLike]:
    return cast(type[TimescaleGroupLike], get_archetype_by_name(archetype_names.TIMESCALE_GROUP))


def _group_index(group: int | EntityRef) -> int:
    return group.index if isinstance(group, EntityRef) else group


def _marker(index: int) -> TimescaleChangeLike:
    return timescale_change_archetype().at(index)


def _require_group(index: int) -> TimescaleGroupLike:
    group = timescale_group_archetype().at(index)
    if runtime.is_preprocessing() and not group.valid:
        error("Invalid timescale group; inspect its validation error code")
    assert group.valid, "Invalid timescale group"
    return group


def _valid_marker_ref(index: int) -> bool:
    return 0 < index < inf and index % 1 == 0 and entity_info_at(index).archetype_id == timescale_change_archetype().id


def _fail(group: TimescaleGroupLike, code: TimelineError) -> None:
    group.valid, group.error_code = False, code


def iter_timescale_changes(index: int) -> Iterator[TimescaleChangeLike]:
    while index > 0:
        marker = _marker(index)
        yield marker
        index = marker.next_ref.index


def _integral(ref: int, left: float, right: float) -> float:
    if ref == 0:
        return right - left
    marker = _marker(ref)
    if marker.next_ref.index == 0:
        return marker.timescale * (right - left)
    return integrate_times(
        marker.timescale,
        _marker(marker.next_ref.index).timescale,
        marker.timescale_ease,
        marker.event_start,
        marker.event_end,
        left,
        right,
    )


def event_speed(ref: int, now: float) -> float:
    if ref == 0:
        return 1.0
    marker = _marker(ref)
    if marker.next_ref.index == 0:
        return marker.timescale
    return speed_at(
        marker.timescale,
        _marker(marker.next_ref.index).timescale,
        marker.timescale_ease,
        marker.event_start,
        marker.event_end,
        now,
    )


def _coordinate(ref: int, now: float) -> TimePosition:
    result = TimePosition.of(now)
    if ref > 0:
        marker = _marker(ref)
        # Anchor at the nearer endpoint to keep near-hit partial integrals local.
        if marker.next_ref.index > 0 and now - marker.event_start > marker.event_end - now:
            following = _marker(marker.next_ref.index)
            result @= following.position.add(-following.converted_skip).add(-_integral(ref, now, marker.event_end))
        else:
            result @= marker.position.add(_integral(ref, marker.event_start, now))
    return result


def initialize_timescale_group(group: TimescaleGroupLike) -> None:
    group.valid, group.has_scroll, group.error_code = False, False, TimelineError.NONE
    group.monotone_targets = True
    group.used, group.time_valid, group.spawn_cursor_valid = False, False, False
    group.needed_start, group.needed_end = inf, -inf
    group.lookup_ref, group.current_event, group.current_run = 0, 0, 0
    group.effective_preempt = preempt_time(group.force_note_speed)
    ref, previous, previous_time, ordinal = group.first_ref.index, 0, -inf, 0
    while ref != 0:
        if not _valid_marker_ref(ref):
            _fail(group, TimelineError.REFERENCE)
            return
        marker = _marker(ref)
        if marker.validation_owner != 0:
            code = TimelineError.CYCLE if marker.validation_owner == group.index else TimelineError.OWNERSHIP
            _fail(group, code)
            if code == TimelineError.OWNERSHIP:
                _fail(timescale_group_archetype().at(marker.validation_owner), code)
            return
        if marker.timescale_group.index not in (0, group.index):
            _fail(group, TimelineError.OWNERSHIP)
            return
        marker.validation_owner = group.index
        if not (
            abs(marker.beat) < inf
            and abs(marker.timescale) < inf
            and abs(marker.timescale_skip) < inf
            and 0 <= marker.timescale_ease <= 5
            and marker.timescale_ease % 1 == 0
            and 0 <= marker.transition_style <= 1
            and marker.transition_style % 1 == 0
        ):
            _fail(group, TimelineError.VALUE)
            return
        converted = beat_to_time(marker.beat)
        if not abs(converted) < inf or converted < previous_time:
            _fail(group, TimelineError.ORDER if converted < previous_time else TimelineError.VALUE)
            return
        marker.converted_skip = 0
        if marker.timescale_skip != 0:
            bpm = beat_to_bpm(marker.beat)
            if not 0 < bpm < inf:
                _fail(group, TimelineError.VALUE)
                return
            marker.converted_skip = marker.timescale_skip * (60 / bpm)
        ordinal += 1
        group.monotone_targets = group.monotone_targets and marker.timescale >= 0 and marker.converted_skip >= 0
        marker.ordinal, marker.prev_ref = ordinal, previous
        marker.event_start, marker.event_end = converted, converted
        if previous > 0:
            _marker(previous).event_end = converted
        if marker.transition_style == TransitionStyle.SCROLL:
            group.has_scroll = True
        previous, previous_time, ref = ref, converted, marker.next_ref.index
    run, previous_run, run_count = 0, -1, 0
    for marker in iter_timescale_changes(group.first_ref.index):
        if group.has_scroll and (marker.timescale <= 0 or marker.timescale_skip != 0):
            _fail(group, TimelineError.HYBRID)
            return
        if marker.prev_ref == 0:
            marker.position = TimePosition.of(marker.event_start).add(marker.converted_skip)
        else:
            prior = _marker(marker.prev_ref)
            marker.position = prior.position.add(_integral(prior.index, prior.event_start, prior.event_end)).add(
                marker.converted_skip
            )
        if run == 0 or marker.transition_style != _marker(run).transition_style:
            if run > 0:
                _marker(run).run_end = marker.index
                previous_run = run
            run = marker.index
            run_count += 1
            marker.run_end = 0
        marker.run_first, marker.prev_run = run, previous_run
    if group.has_scroll:
        _initialize_run_index(run, run_count)
    group.valid = True


def _locate(group: TimescaleGroupLike, now: float, ref: int) -> int:
    while ref > 0 and now < _marker(ref).event_start:
        ref = _marker(ref).prev_ref
    following = group.first_ref.index if ref == 0 else _marker(ref).next_ref.index
    while following > 0 and _marker(following).event_start <= now:
        ref = following
        following = _marker(ref).next_ref.index
    return ref


def locate_time(group: int | EntityRef, now: float) -> int:
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return 0
    entity = _require_group(index)
    entity.lookup_ref = _locate(entity, now, entity.lookup_ref)
    return entity.lookup_ref


def locate_target(group: int | EntityRef, hit_time: float) -> TargetPosition:
    ref = locate_time(group, hit_time)
    return TargetPosition(ref, _coordinate(ref, hit_time))


def locate_time_from(group: int | EntityRef, now: float, ref: int) -> int:
    """Advance a caller-owned locator without moving the group's shared cursor."""
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return 0
    return _locate(_require_group(index), now, ref)


def _run(ref: int) -> int:
    return -1 if ref == 0 else _marker(ref).run_first


def _log_add(left: float, right: float) -> float:
    high, low = max(left, right), min(left, right)
    if high == -inf:
        return -inf
    return high + log(1 + e ** (low - high))


def _timescale_distance(ref: int, now: float, target: TargetPosition, hit: float) -> float:
    """Use a local integral in one event; otherwise subtract split positions."""
    if ref == target.event_ref:
        return _integral(ref, now, hit)
    return target.coordinate.difference(_coordinate(ref, now))


def _distance_from(
    group: TimescaleGroupLike,
    ref: int,
    now: float,
    target: TargetPosition,
    hit: float,
    distance_limit: float = DISTANCE_LIMIT,
) -> float:
    if group.has_scroll and _run(ref) != _run(target.event_ref):
        return _mixed_run_distance(group, ref, now, target, hit, distance_limit)
    if ref > 0 and _marker(ref).transition_style == TransitionStyle.SCROLL:
        value = event_speed(ref, now) * (hit - now)
    else:
        value = _timescale_distance(ref, now, target, hit)
    return max(-distance_limit, min(distance_limit, value))


def _piece_summary(ref: int, start: float, end_ref: int, end: float) -> RunSummary:
    width = end - start
    result = RunSummary(0, -inf, -inf)
    if ref > 0 and _marker(ref).transition_style == TransitionStyle.SCROLL:
        left_speed, right_speed = event_speed(ref, start), event_speed(end_ref, end)
        result.log_ratio = log(left_speed) - log(right_speed)
        if width > 0:
            result.log_forward, result.log_backward = log(left_speed) + log(width), log(right_speed) + log(width)
    else:
        distance = _coordinate(end_ref, end).difference(_coordinate(ref, start))
        if distance > 0:
            result.log_forward = log(distance)
            result.log_backward = result.log_forward
    return result


def _initialize_run_index(run: int, ordinal: int) -> None:
    """Each run stores one forward block, sized by its ordinal's lowest set bit."""
    # Widths are 1, 2, 1, 4, ...; build right to left so child blocks are ready.
    while run > 0:
        marker = _marker(run)
        width, divisor = 1, ordinal
        while divisor % 2 == 0:
            width *= 2
            divisor //= 2
        marker.jump_end, marker.jump_width = marker.run_end, 0
        marker.jump = RunSummary(0, -inf, -inf)
        if marker.run_end > 0:
            endpoint = _marker(marker.run_end)
            marker.jump = _piece_summary(run, marker.event_start, endpoint.index, endpoint.event_start)
            marker.jump_width = 1
            cursor = marker.run_end
            while marker.jump_width < width and _marker(cursor).jump_end > 0:
                following = _marker(cursor)
                assert marker.jump_width + following.jump_width <= width
                marker.jump = marker.jump.then(following.jump)
                marker.jump_width += following.jump_width
                marker.jump_end = following.jump_end
                cursor = following.jump_end
        run, ordinal = marker.prev_run, ordinal - 1


def _mixed_run_distance(
    group: TimescaleGroupLike,
    ref: int,
    now: float,
    target: TargetPosition,
    hit: float,
    distance_limit: float,
) -> float:
    """Cover the chronological interval with precomputed forward run blocks."""
    reverse = now > hit or (
        now == hit
        and (0 if ref == 0 else _marker(ref).ordinal)
        > (0 if target.event_ref == 0 else _marker(target.event_ref).ordinal)
    )
    left_ref, left, right_ref, right = ref, now, target.event_ref, hit
    if reverse:
        left_ref, left, right_ref, right = right_ref, right, left_ref, left
    target_run = _run(right_ref)
    total = RunSummary(0, -inf, -inf)
    while _run(left_ref) != target_run:
        current_run = _run(left_ref)
        boundary = group.first_ref.index if current_run < 0 else _marker(current_run).run_end
        assert boundary > 0
        part = RunSummary(0, -inf, -inf)
        indexed = False
        if left_ref == current_run and left == _marker(left_ref).event_start:
            marker = _marker(left_ref)
            if marker.jump_end > 0 and _marker(marker.jump_end).ordinal <= _marker(target_run).ordinal:
                part @= marker.jump
                boundary, indexed = marker.jump_end, True
        if not indexed:
            part @= _piece_summary(left_ref, left, boundary, _marker(boundary).event_start)
        total @= total.then(part)
        left_ref, left = boundary, _marker(boundary).event_start
    total @= total.then(_piece_summary(left_ref, left, right_ref, right))
    logarithm = total.log_backward if reverse else total.log_forward
    value = distance_limit if logarithm >= log(distance_limit) else e**logarithm
    return -value if reverse else value


def distance_between(group: int | EntityRef, now: float, hit: float, distance_limit: float = DISTANCE_LIMIT) -> float:
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return max(-distance_limit, min(distance_limit, hit - now))
    entity = _require_group(index)
    ref = locate_time(index, now)
    return _distance_from(entity, ref, now, locate_target(index, hit), hit, distance_limit)


def distance_to_target(
    group: int | EntityRef,
    ref: int,
    now: float,
    target: TargetPosition,
    hit: float,
    distance_limit: float = DISTANCE_LIMIT,
) -> float:
    """Evaluate from an already located current state and immutable target."""
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return max(-distance_limit, min(distance_limit, hit - now))
    return _distance_from(_require_group(index), ref, now, target, hit, distance_limit)


def prepared_time_matches(stored: float, now: float) -> bool:
    return abs(stored - now) <= 2.0**-23 * max(abs(stored), abs(now)) + 2.0**-149


def prepare_group(group: int | EntityRef, now: float) -> None:
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return
    entity = _require_group(index)
    if entity.time_valid and entity.last_updated == now:
        return
    ref = _locate(entity, now, entity.current_event)
    entity.current_event, entity.current_run = ref, _run(ref)
    entity.last_updated, entity.time_valid = now, True
    entity.coordinate, entity.current_speed = _coordinate(ref, now), event_speed(ref, now)
    entity.event_start, entity.event_end = -inf, inf
    entity.v0, entity.v1, entity.ease, entity.style = 1, 1, EaseType.NONE, TransitionStyle.TIMESCALE
    entity.hide_notes = False
    future = entity.first_ref.index
    if ref > 0:
        marker = _marker(ref)
        entity.event_start, entity.v0, entity.v1 = marker.event_start, marker.timescale, marker.timescale
        entity.ease, entity.style, entity.hide_notes = marker.timescale_ease, marker.transition_style, marker.hide_notes
        if marker.next_ref.index > 0:
            entity.event_end, entity.v1 = marker.event_end, _marker(marker.next_ref.index).timescale
        else:
            entity.ease = EaseType.NONE
        future = _marker(entity.current_run).run_end
    elif future > 0:
        entity.event_end = _marker(future).event_start
    entity.current_constant = entity.ease == EaseType.NONE or entity.v0 == entity.v1
    entity.future_gain, entity.past_gain, entity.future_offset, entity.past_offset = 1, 1, 0, 0
    for side in range(2):
        anchor = future if side == 0 else entity.current_run
        if anchor > 0:
            endpoint = _marker(anchor)
            gain, offset = 1.0, endpoint.position.difference(entity.coordinate)
            if entity.style == TransitionStyle.SCROLL:
                gain = entity.current_speed / endpoint.timescale
                offset = entity.current_speed * (endpoint.event_start - now)
            if side == 0:
                entity.future_gain, entity.future_offset = gain, offset
            else:
                entity.past_gain, entity.past_offset = gain, offset


def prepare_trajectory(
    group: int | EntityRef, hit: float, target: TargetPosition, cache: TrajectoryCache, now: float
) -> None:
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return
    entity = _require_group(index)
    assert entity.time_valid
    assert prepared_time_matches(entity.last_updated, now)
    if cache.run_ref == entity.current_run:
        return
    cache.run_ref, cache.boundary_distance = entity.current_run, 0
    target_run = _run(target.event_ref)
    if target_run != entity.current_run:
        past = target_run < 0 or (
            entity.current_run > 0 and _marker(target_run).ordinal < _marker(entity.current_run).ordinal
        )
        anchor = (
            entity.current_run
            if past
            else (entity.first_ref.index if entity.current_run < 0 else _marker(entity.current_run).run_end)
        )
        cache.boundary_distance = _distance_from(entity, anchor, _marker(anchor).event_start, target, hit)


def evaluate_trajectory(
    group: int | EntityRef, hit: float, target: TargetPosition, cache: TrajectoryCache, now: float
) -> float:
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return hit - now
    entity = _require_group(index)
    assert cache.run_ref == entity.current_run
    target_run = _run(target.event_ref)
    if target_run == entity.current_run:
        if entity.style == TransitionStyle.SCROLL:
            return entity.current_speed * (hit - now)
        if target.event_ref == entity.current_event:
            if entity.current_constant:
                return entity.current_speed * (hit - now)
            return integrate_times(entity.v0, entity.v1, entity.ease, entity.event_start, entity.event_end, now, hit)
        return target.coordinate.difference(entity.coordinate)
    past = target_run < 0 or (
        entity.current_run > 0 and _marker(target_run).ordinal < _marker(entity.current_run).ordinal
    )
    if past:
        return entity.past_gain * cache.boundary_distance + entity.past_offset
    return entity.future_gain * cache.boundary_distance + entity.future_offset


def register_group_window(group: int | EntityRef, start: float, end: float) -> None:
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale or not (-inf < start <= end < inf):
        return
    assert runtime.is_preprocessing(), "Group lifetimes must be registered during preprocessing"
    entity = _require_group(index)
    entity.needed_start, entity.needed_end, entity.used = (
        min(entity.needed_start, start),
        max(entity.needed_end, end),
        True,
    )


def group_hide_notes(group: int | EntityRef) -> bool:
    index = _group_index(group)
    return index > 0 and not Options.disable_timescale and _require_group(index).hide_notes


def group_force_note_speed(group: int | EntityRef) -> float:
    index = _group_index(group)
    return timescale_group_archetype().at(index).force_note_speed if index > 0 else 0.0


def group_preempt_time(group: int | EntityRef) -> float:
    index = _group_index(group)
    return timescale_group_archetype().at(index).effective_preempt if index > 0 else Layout.default_preempt


def iter_timescale_changes_in_group_from_time(group: int | EntityRef, now: float) -> Iterator[TimescaleChangeLike]:
    index = _group_index(group)
    if index > 0 and not Options.disable_timescale:
        entity = _require_group(index)
        ref = locate_time(index, now)
        yield from iter_timescale_changes(entity.first_ref.index if ref == 0 else ref)
