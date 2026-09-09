"""Immutable atomic timescale transfers, same-style runs and consumer caches."""

from __future__ import annotations

from collections.abc import Iterator
from enum import IntEnum
from math import inf
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
from sekai.lib.timescale_math import (
    UNIT_ROUNDOFF,
    AccurateScalar,
    AffineTransfer,
    certified_integrate_times,
    certified_speed_at,
    midpoint_parts,
    polynomial_piece_integral,
)

MIN_START_TIME = -2.0


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


class CacheKind(IntEnum):
    IDENTITY = 0
    PRELUDE = 1
    SAME = 2
    FUTURE = 3
    PAST = 4


class TargetPosition(Record):
    event_ref: int


class TrajectoryCache(Record):
    """Cache D(run_start, hit) for SAME and D(run_end, hit) for FUTURE.

    PAST stores -D(run_start, hit), so advancing its anchor adds the run's
    distance before dividing by its ratio. An invalid pending cache instead
    holds its publication allowance in value.hi until cold refresh completes.
    """

    target_ref: int
    run_ref: int
    kind: CacheKind
    anchor_ref: int
    value: AccurateScalar
    valid: bool


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
    tree_left: int
    tree_right: int
    subtree_first: int
    subtree_last: int
    aggregate: AffineTransfer
    run_first: int
    run_end: int
    run_prefix: AccurateScalar
    run_suffix: AccurateScalar
    suffix_r_min: AccurateScalar
    suffix_r_max: AccurateScalar
    suffix_b_max: AccurateScalar
    ratio_or_curve: AccurateScalar
    own_distance: AccurateScalar
    ordinal: int
    prev_ref: int
    tree_parent: int
    validation_owner: int
    run_peak_speed: float
    converted_skip: AccurateScalar
    midpoint_hi: float
    midpoint_lo: float

    @classmethod
    def at(cls, index: int) -> Self: ...

    @property
    def index(self) -> int: ...


class TimescaleGroupLike(Protocol):
    first_ref: EntityRef
    force_note_speed: float
    root: int
    mode: int
    valid: bool
    marker_count: int
    final_ref: int
    error_code: TimelineError
    used: bool
    effective_preempt: float
    needed_start: float
    needed_end: float
    time_valid: bool
    last_updated: float
    current_event: int
    current_run: int
    current_constant: bool
    current_run_end: int
    current_speed: float
    certified_current_speed: AccurateScalar
    hide_notes: bool
    future_ratio: AccurateScalar
    future_distance: AccurateScalar
    past_ratio: AccurateScalar
    past_distance: AccurateScalar
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
    if isinstance(group, EntityRef):
        return group.index
    return group


def _marker(index: int) -> TimescaleChangeLike:
    return timescale_change_archetype().at(index)


def _valid_marker_ref(index: int) -> bool:
    return 0 < index < inf and index % 1 == 0 and entity_info_at(index).archetype_id == timescale_change_archetype().id


def _fail(group: TimescaleGroupLike, code: TimelineError):
    group.valid = False
    group.error_code = code


def _require_group(index: int) -> TimescaleGroupLike:
    group = timescale_group_archetype().at(index)
    if runtime.is_preprocessing():
        if not group.valid:
            error("Invalid timescale group; inspect its validation error code")
    else:
        assert group.valid, "Invalid timescale group; inspect its validation error code"
    return group


def _width(start: float, end: float) -> AccurateScalar:
    return AccurateScalar.difference(end, start)


def _skip(marker: TimescaleChangeLike) -> AccurateScalar:
    return +marker.converted_skip


def _convert_skip(marker: TimescaleChangeLike) -> AccurateScalar:
    result = +AccurateScalar
    if marker.timescale_skip != 0:
        bpm = beat_to_bpm(marker.beat)
        if bpm == 60:
            result @= AccurateScalar.of(marker.timescale_skip)
        else:
            result @= AccurateScalar.of(marker.timescale_skip).scale(60).div(AccurateScalar.of(bpm))
    return result


def _full_integral(marker: TimescaleChangeLike) -> AccurateScalar:
    """Closed full-event easing moments, avoiding the general partial kernel."""
    mean = AccurateScalar.of(marker.timescale)
    if (
        marker.next_ref.index > 0
        and marker.timescale_ease != EaseType.NONE
        and marker.timescale != _marker(marker.next_ref.index).timescale
    ):
        destination = AccurateScalar.of(_marker(marker.next_ref.index).timescale)
        if marker.timescale_ease == EaseType.IN_QUAD:
            mean @= mean.scale(2).add(destination).div(AccurateScalar.of(3))
        elif marker.timescale_ease == EaseType.OUT_QUAD:
            mean @= mean.add(destination.scale(2)).div(AccurateScalar.of(3))
        else:
            mean @= mean.add(destination).scale(0.5)
    return mean.mul(_width(marker.event_start, marker.event_end))


def _atomic_transfer(marker: TimescaleChangeLike) -> AffineTransfer:
    """The TS ratio is exactly one; its unused stored ratio holds curve data."""
    ratio = AccurateScalar.of(1)
    if marker.transition_style == TransitionStyle.SCROLL:
        ratio @= marker.ratio_or_curve
    return AffineTransfer(ratio, +marker.own_distance)


def _scroll_run_ratio(marker: TimescaleChangeLike) -> AccurateScalar:
    """Immutable marker-to-run-end ratio in SCROLL's unused prefix slots."""
    assert marker.transition_style == TransitionStyle.SCROLL
    return +marker.run_prefix


def _curve_coefficient(marker: TimescaleChangeLike) -> AccurateScalar:
    """Slope for LINEAR, first-half t**2 coefficient for quadratic eases."""
    result = +AccurateScalar
    if marker.next_ref.index > 0 and marker.event_start < marker.event_end and marker.timescale_ease != EaseType.NONE:
        duration = _width(marker.event_start, marker.event_end)
        result @= AccurateScalar.of(_marker(marker.next_ref.index).timescale).sub(AccurateScalar.of(marker.timescale))
        result @= result.div(duration)
        if marker.timescale_ease != EaseType.LINEAR:
            result @= result.div(duration)
            factor = 1.0
            if marker.timescale_ease == EaseType.OUT_QUAD:
                factor = -1.0
            elif marker.timescale_ease == EaseType.IN_OUT_QUAD:
                factor = 2.0
            elif marker.timescale_ease == EaseType.OUT_IN_QUAD:
                factor = -2.0
            result @= result.scale(factor)
    return result


def _midpoint_delta(marker: TimescaleChangeLike, now: float) -> AccurateScalar:
    return AccurateScalar.difference(now, marker.midpoint_hi).sub(AccurateScalar.of(marker.midpoint_lo))


def event_speed(index: int, now: float) -> AccurateScalar:
    """Outgoing continuous speed, including its left limit at a held endpoint."""
    result = +AccurateScalar
    if index == 0:
        result @= AccurateScalar.of(1)
    else:
        marker = _marker(index)
        if (
            marker.next_ref.index == 0
            or marker.event_end <= marker.event_start
            or marker.timescale_ease == EaseType.NONE
            or marker.timescale == _marker(marker.next_ref.index).timescale
        ):
            result @= AccurateScalar.of(marker.timescale)
        else:
            result @= certified_speed_at(
                marker.timescale,
                _marker(marker.next_ref.index).timescale,
                marker.timescale_ease,
                marker.event_start,
                marker.event_end,
                now,
            )
    return result


def _integral(index: int, start: float, end: float) -> AccurateScalar:
    result = +AccurateScalar
    if index == 0:
        result @= _width(start, end)
    else:
        marker = _marker(index)
        if (
            marker.next_ref.index == 0
            or marker.timescale_ease == EaseType.NONE
            or marker.timescale == _marker(marker.next_ref.index).timescale
        ):
            result @= _width(start, end).scale(marker.timescale)
        else:
            result @= certified_integrate_times(
                marker.timescale,
                _marker(marker.next_ref.index).timescale,
                marker.timescale_ease,
                marker.event_start,
                marker.event_end,
                start,
                end,
            )
    return result


def _fragment(index: int, start: float, end: float) -> AffineTransfer:
    """Continuous interval excluding any destination step/skip."""
    result = AffineTransfer.identity()
    if start != end:
        if index == 0 or _marker(index).transition_style == TransitionStyle.TIMESCALE:
            result @= AffineTransfer(AccurateScalar.of(1), _integral(index, start, end))
        else:
            speed_start = +AccurateScalar
            speed_end = +AccurateScalar
            for point in range(2):
                value = event_speed(index, start if point == 0 else end)
                if point == 0:
                    speed_start @= value
                else:
                    speed_end @= value
            result @= AffineTransfer(speed_start.div(speed_end), speed_start.mul(_width(start, end)))
    return result


def _to_destination(index: int, start: float) -> AffineTransfer:
    result = +AffineTransfer
    marker = _marker(index)
    destination = _marker(marker.next_ref.index)
    if marker.transition_style == TransitionStyle.TIMESCALE:
        result @= AffineTransfer(
            AccurateScalar.of(1), _integral(index, start, marker.event_end).add(_skip(destination))
        )
    else:
        speed_start = event_speed(index, start)
        result @= AffineTransfer(
            speed_start.div(AccurateScalar.of(destination.timescale)), speed_start.mul(_width(start, marker.event_end))
        )
    return result


def _compress_tree(group: TimescaleGroupLike, count: int):
    """Day--Stout--Warren compression: balance the ordered vine without an arena."""
    parent = 0
    for _ in range(count):
        child_ref = group.root if parent == 0 else _marker(parent).tree_right
        child = _marker(child_ref)
        grand_ref = child.tree_right
        grand = _marker(grand_ref)
        if parent == 0:
            group.root = grand_ref
        else:
            _marker(parent).tree_right = grand_ref
        child.tree_right = grand.tree_left
        if child.tree_right > 0:
            _marker(child.tree_right).tree_parent = child_ref
        grand.tree_left = child_ref
        grand.tree_parent = parent
        child.tree_parent = grand_ref
        parent = grand_ref


def initialize_timescale_group(group: TimescaleGroupLike):
    group.valid = False
    group.mode = 0
    group.error_code = TimelineError.NONE
    group.marker_count = 0
    group.final_ref = 0
    group.root = 0
    group.time_valid = False
    group.spawn_cursor_valid = False
    group.used = False
    group.needed_start = inf
    group.needed_end = -inf
    group.effective_preempt = preempt_time(group.force_note_speed)
    ref = group.first_ref.index
    previous = 0
    previous_time = -inf
    while ref != 0:
        if not _valid_marker_ref(ref):
            _fail(group, TimelineError.REFERENCE)
            return
        marker = _marker(ref)
        if marker.validation_owner != 0:
            if marker.validation_owner != group.index:
                _fail(timescale_group_archetype().at(marker.validation_owner), TimelineError.OWNERSHIP)
                _fail(group, TimelineError.OWNERSHIP)
            else:
                _fail(group, TimelineError.CYCLE)
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
        if not abs(converted) < inf:
            _fail(group, TimelineError.VALUE)
            return
        if converted < previous_time:
            _fail(group, TimelineError.ORDER)
            return
        marker.converted_skip = _convert_skip(marker)
        group.marker_count += 1
        marker.ordinal = group.marker_count
        marker.prev_ref = previous
        marker.tree_parent = previous
        marker.tree_left = 0
        marker.tree_right = marker.next_ref.index
        marker.event_start = converted
        marker.event_end = converted
        if previous > 0:
            _marker(previous).event_end = converted
        if marker.transition_style == TransitionStyle.SCROLL:
            group.mode = 1
        previous = ref
        previous_time = converted
        ref = marker.next_ref.index
    group.final_ref = previous
    if group.marker_count == 0:
        group.valid = True
        return
    run_first = group.first_ref.index
    for marker in iter_timescale_changes(group.first_ref.index):
        if group.mode == 1 and (marker.timescale <= 0 or marker.timescale_skip != 0):
            _fail(group, TimelineError.HYBRID)
            return
        if marker.prev_ref > 0 and _marker(marker.prev_ref).transition_style != marker.transition_style:
            run_first = marker.index
        marker.run_first = run_first
        midpoint = midpoint_parts(marker.event_start, marker.event_end)
        marker.midpoint_hi = midpoint.hi
        marker.midpoint_lo = midpoint.lo
        if marker.transition_style == TransitionStyle.TIMESCALE:
            marker.ratio_or_curve = _curve_coefficient(marker)
        else:
            marker.ratio_or_curve = AccurateScalar.of(1)
        marker.own_distance = AccurateScalar.of(0)
        if marker.next_ref.index > 0:
            destination = _marker(marker.next_ref.index)
            if marker.transition_style == TransitionStyle.SCROLL:
                marker.ratio_or_curve = AccurateScalar.of(marker.timescale).div(AccurateScalar.of(destination.timescale))
                marker.own_distance = _width(marker.event_start, marker.event_end).scale(marker.timescale)
            else:
                marker.own_distance = _full_integral(marker).add(_skip(destination))
        marker.run_prefix = AccurateScalar.of(0)
        if marker.index != marker.run_first:
            prev = _marker(marker.prev_ref)
            if marker.transition_style == TransitionStyle.SCROLL:
                first = _marker(marker.run_first)
                marker.run_prefix = _width(first.event_start, marker.event_start).scale(first.timescale)
            else:
                marker.run_prefix = prev.run_prefix.add(prev.own_distance)
    ref = group.final_ref
    run_end = 0
    while ref > 0:
        marker = _marker(ref)
        if marker.next_ref.index > 0 and _marker(marker.next_ref.index).transition_style != marker.transition_style:
            run_end = marker.next_ref.index
        marker.run_end = run_end
        marker.run_peak_speed = abs(marker.timescale)
        if marker.next_ref.index > 0:
            marker.run_peak_speed = max(marker.run_peak_speed, abs(_marker(marker.next_ref.index).timescale))
            if marker.next_ref.index != run_end:
                marker.run_peak_speed = max(marker.run_peak_speed, _marker(marker.next_ref.index).run_peak_speed)
        end = _marker(group.final_ref if run_end == 0 else run_end)
        marker.run_suffix = AccurateScalar.of(0)
        if marker.transition_style == TransitionStyle.SCROLL:
            marker.run_suffix = _width(marker.event_start, end.event_start).scale(marker.timescale)
            # SCROLL coordinates use elapsed time directly. Its otherwise
            # unused prefix record stores the immutable remaining run ratio.
            marker.run_prefix = AccurateScalar.of(marker.timescale).div(AccurateScalar.of(end.timescale))
        elif marker.next_ref.index > 0:
            marker.run_suffix = +marker.own_distance
            if marker.next_ref.index != run_end:
                marker.run_suffix = marker.run_suffix.add(_marker(marker.next_ref.index).run_suffix)
        ref = marker.prev_ref
    group.root = group.first_ref.index
    size = 1
    while size <= group.marker_count + 1:
        size *= 2
    size = size // 2 - 1
    _compress_tree(group, group.marker_count - size)
    while size > 1:
        size //= 2
        _compress_tree(group, size)
    _build_aggregates(group)
    _refine_run_coordinates(group)
    group.valid = True


def _refine_run_coordinates(group: TimescaleGroupLike):
    """Replace wide sequential certificates with balanced accurate range sums.

    This intentionally spends O(E log E) loading work when necessary. Subtracting
    two late-song linear prefixes must not inherit O(E squared) error radii.
    """
    for marker in iter_timescale_changes(group.first_ref.index):
        if marker.transition_style == TransitionStyle.TIMESCALE:
            if not marker.run_prefix.error_at_most(1e-8):
                first = _marker(marker.run_first)
                marker.run_prefix = _range_transfer(group, first.ordinal, marker.ordinal - 1).distance
            if not marker.run_suffix.error_at_most(1e-8):
                end = _marker(group.final_ref if marker.run_end == 0 else marker.run_end)
                marker.run_suffix = _range_transfer(group, marker.ordinal, end.ordinal - 1).distance


def _build_aggregates(group: TimescaleGroupLike):
    ref = group.root
    previous = 0
    while ref > 0:
        marker = _marker(ref)
        next_ref = marker.tree_parent
        ready = False
        if previous == marker.tree_parent:
            if marker.tree_left > 0:
                next_ref = marker.tree_left
            elif marker.tree_right > 0:
                next_ref = marker.tree_right
            else:
                ready = True
        elif previous == marker.tree_left and marker.tree_right > 0:
            next_ref = marker.tree_right
        else:
            ready = True
        if ready:
            _aggregate_node(marker, group.mode)
        previous = ref
        ref = next_ref


def _aggregate_node(marker: TimescaleChangeLike, mode: int):
    marker.subtree_first = marker.ordinal
    marker.subtree_last = marker.ordinal
    marker.aggregate = _atomic_transfer(marker)
    if marker.tree_left > 0:
        left = _marker(marker.tree_left)
        marker.aggregate = left.aggregate.then(marker.aggregate)
        marker.subtree_first = left.subtree_first
    if marker.tree_right > 0:
        right = _marker(marker.tree_right)
        marker.aggregate = marker.aggregate.then(right.aggregate)
        marker.subtree_last = right.subtree_last
    first_ref = marker.index
    while _marker(first_ref).tree_left > 0:
        first_ref = _marker(first_ref).tree_left
    last_ref = marker.index
    while _marker(last_ref).tree_right > 0:
        last_ref = _marker(last_ref).tree_right
    first = _marker(first_ref)
    last = _marker(last_ref)
    if first.run_first == last.run_first and first.transition_style == TransitionStyle.TIMESCALE:
        # The timescale ratio is exactly one, including signed/zero speeds and
        # skips. Multiplying approximate identities invents historical R error.
        distance = +marker.own_distance
        if marker.tree_left > 0:
            distance @= _marker(marker.tree_left).aggregate.distance.add(distance)
        if marker.tree_right > 0:
            distance @= distance.add(_marker(marker.tree_right).aggregate.distance)
        marker.aggregate = AffineTransfer(AccurateScalar.of(1), distance)
    if first.run_first == last.run_first and first.transition_style == TransitionStyle.SCROLL:
        end_ref = last.index if last.next_ref.index == 0 else last.next_ref.index
        end = _marker(end_ref)
        marker.aggregate = AffineTransfer(
            AccurateScalar.of(first.timescale).div(AccurateScalar.of(end.timescale)),
            _width(first.event_start, end.event_start).scale(first.timescale),
        )
    _node_envelope(marker, mode)


def _node_envelope(marker: TimescaleChangeLike, mode: int):
    speed_max = abs(marker.timescale)
    speed_min = marker.timescale
    if marker.next_ref.index > 0:
        speed_max = max(speed_max, abs(_marker(marker.next_ref.index).timescale))
        speed_min = min(speed_min, _marker(marker.next_ref.index).timescale)
    bound = _width(marker.event_start, marker.event_end).scale(speed_max)
    if marker.next_ref.index > 0:
        skip = _skip(_marker(marker.next_ref.index))
        if skip.hi < 0:
            skip @= skip.neg()
        bound @= bound.add(skip)
    marker.suffix_r_min = AccurateScalar.of(1)
    marker.suffix_r_max = AccurateScalar.of(1)
    marker.suffix_b_max = bound
    if mode == 1 and marker.transition_style == TransitionStyle.SCROLL and marker.next_ref.index > 0:
        end_speed = AccurateScalar.of(_marker(marker.next_ref.index).timescale)
        marker.suffix_r_min = AccurateScalar.of(speed_min).div(end_speed)
        marker.suffix_r_max = AccurateScalar.of(speed_max).div(end_speed)
    if mode == 0:
        if marker.tree_left > 0:
            bound @= bound.add(_marker(marker.tree_left).suffix_b_max)
        if marker.tree_right > 0:
            bound @= bound.add(_marker(marker.tree_right).suffix_b_max)
        marker.suffix_b_max = bound
        marker.suffix_r_min = bound.neg()
        marker.suffix_r_max = +bound
    else:
        if marker.tree_right > 0:
            right = _marker(marker.tree_right)
            marker.suffix_b_max = _upper_max(
                marker.suffix_b_max.add(marker.suffix_r_max.mul(right.aggregate.distance)), right.suffix_b_max
            )
            marker.suffix_r_max = _upper_max(marker.suffix_r_max.mul(right.aggregate.ratio), right.suffix_r_max)
            marker.suffix_r_min = _lower_min(marker.suffix_r_min.mul(right.aggregate.ratio), right.suffix_r_min)
        if marker.tree_left > 0:
            left = _marker(marker.tree_left)
            following = _atomic_transfer(marker)
            if marker.tree_right > 0:
                following @= following.then(_marker(marker.tree_right).aggregate)
            marker.suffix_b_max = _upper_max(
                marker.suffix_b_max, left.suffix_b_max.add(left.suffix_r_max.mul(following.distance))
            )
            marker.suffix_r_max = _upper_max(marker.suffix_r_max, left.suffix_r_max.mul(following.ratio))
            marker.suffix_r_min = _lower_min(marker.suffix_r_min, left.suffix_r_min.mul(following.ratio))


def _upper_max(a: AccurateScalar, b: AccurateScalar) -> AccurateScalar:
    result = a.upper_bound()
    other = b.upper_bound()
    if result.compare(other) < 0:
        result @= other
    return result


def _lower_min(a: AccurateScalar, b: AccurateScalar) -> AccurateScalar:
    result = a.lower_bound()
    other = b.lower_bound()
    if result.compare(other) > 0:
        result @= other
    return result


def iter_timescale_changes(index: int) -> Iterator[TimescaleChangeLike]:
    while index > 0:
        marker = _marker(index)
        yield marker
        index = marker.next_ref.index


def locate_time(group: int | EntityRef, now: float) -> int:
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return 0
    ref = _require_group(index).root
    found = 0
    while ref > 0:
        marker = _marker(ref)
        if marker.event_start <= now:
            found = ref
            ref = marker.tree_right
        else:
            ref = marker.tree_left
    return found


def _published_then(left: AffineTransfer, right: AffineTransfer) -> AffineTransfer:
    return AffineTransfer(
        left.ratio.published_mul(right.ratio), left.distance.published_add(left.ratio.published_mul(right.distance))
    )


def _range_transfer(group: TimescaleGroupLike, first: int, last: int, published: bool = False) -> AffineTransfer:
    """Inclusive ordinal cover, traversed right-to-left using parent links."""
    result = AffineTransfer.identity()
    ref = group.root
    previous = 0
    while ref > 0:
        marker = _marker(ref)
        next_ref = marker.tree_parent
        entering = previous == marker.tree_parent
        covered = first <= marker.subtree_first and marker.subtree_last <= last
        excluded = marker.subtree_last < first or marker.subtree_first > last
        if entering and covered:
            if published:
                result @= _published_then(marker.aggregate, result)
            elif group.mode == 0:
                result.distance @= marker.aggregate.distance.add(result.distance)
            else:
                result @= marker.aggregate.then(result)
        elif not excluded:
            if entering and marker.tree_right > 0:
                next_ref = marker.tree_right
            elif entering or previous == marker.tree_right:
                if first <= marker.ordinal <= last:
                    if published:
                        result @= _published_then(_atomic_transfer(marker), result)
                    elif group.mode == 0:
                        result.distance @= marker.own_distance.add(result.distance)
                    else:
                        result @= _atomic_transfer(marker).then(result)
                if marker.tree_left > 0:
                    next_ref = marker.tree_left
        previous = ref
        ref = next_ref
    return result


def _range_apply(group: TimescaleGroupLike, first: int, last: int, value: AccurateScalar) -> AccurateScalar:
    """Cheap published future query: apply the canonical cover, never build R."""
    result = +value
    ref = group.root
    previous = 0
    while ref > 0:
        marker = _marker(ref)
        next_ref = marker.tree_parent
        entering = previous == marker.tree_parent
        covered = first <= marker.subtree_first and marker.subtree_last <= last
        excluded = marker.subtree_last < first or marker.subtree_first > last
        if entering and covered:
            result @= marker.aggregate.published_apply(result)
        elif not excluded:
            if entering and marker.tree_right > 0:
                next_ref = marker.tree_right
            elif entering or previous == marker.tree_right:
                if first <= marker.ordinal <= last:
                    result @= _atomic_transfer(marker).published_apply(result)
                if marker.tree_left > 0:
                    next_ref = marker.tree_left
        previous = ref
        ref = next_ref
    return result


def _forward_transfer(
    group: TimescaleGroupLike, start: float, start_ref: int, end: float, end_ref: int, published: bool = False
) -> AffineTransfer:
    result = AffineTransfer.identity()
    local_start = start
    if start_ref != end_ref:
        first_ordinal = 1
        if start_ref == 0:
            first = _marker(group.first_ref.index)
            result @= AffineTransfer(AccurateScalar.of(1), _width(start, first.event_start).add(_skip(first)))
        else:
            result @= _to_destination(start_ref, start)
            first_ordinal = _marker(start_ref).ordinal + 1
        if end_ref > 0:
            destination = _marker(end_ref)
            local_start = destination.event_start
            if first_ordinal < destination.ordinal:
                interval = _range_transfer(group, first_ordinal, destination.ordinal - 1, published)
                if published:
                    result @= _published_then(result, interval)
                else:
                    result @= result.then(interval)
    final = _fragment(end_ref, local_start, end)
    if start_ref == end_ref:
        result @= final
    elif published:
        result @= _published_then(result, final)
    else:
        result @= result.then(final)
    return result


def distance_between(group: int | EntityRef, now: float, hit_time: float) -> AccurateScalar:
    result = +AccurateScalar
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        result @= _width(now, hit_time)
    else:
        entity = _require_group(index)
        if entity.marker_count == 0:
            result @= _width(now, hit_time)
        else:
            now_ref = locate_time(index, now)
            hit_ref = locate_time(index, hit_time)
            reverse = now > hit_time
            start = hit_time if reverse else now
            end = now if reverse else hit_time
            start_ref = hit_ref if reverse else now_ref
            end_ref = now_ref if reverse else hit_ref
            transfer = _forward_transfer(entity, start, start_ref, end, end_ref)
            if reverse:
                result @= transfer.distance.neg().div(transfer.ratio)
            else:
                result @= transfer.distance
    return result


def locate_target(group: int | EntityRef, hit_time: float) -> TargetPosition:
    """Create immutable target metadata, including for inactive anchor notes."""
    ref = locate_time(group, hit_time)
    return TargetPosition(ref)


def register_group_window(group: int | EntityRef, start: float, end: float) -> None:
    """Extend a group's lifetime by a real consumer's preprocessing window."""
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale or not (-inf < start <= end < inf):
        return
    assert runtime.is_preprocessing(), "Group lifetimes must be registered during preprocessing"
    entity = _require_group(index)
    entity.needed_start = min(entity.needed_start, start)
    entity.needed_end = max(entity.needed_end, end)
    entity.used = True


def _target_from_anchor(
    group: TimescaleGroupLike, anchor: int, hit_time: float, target: TargetPosition, published: bool = False
) -> AccurateScalar:
    result = +AccurateScalar
    marker = _marker(anchor)
    target_ordinal = 0 if target.event_ref == 0 else _marker(target.event_ref).ordinal
    reverse = marker.ordinal > target_ordinal
    partial = AffineTransfer.identity()
    first_ordinal = marker.ordinal
    last_ordinal = target_ordinal - 1
    if reverse:
        first_ordinal = target_ordinal + 1
        last_ordinal = marker.ordinal - 1
        if target.event_ref == 0:
            first = _marker(group.first_ref.index)
            partial.distance @= _width(hit_time, first.event_start).add(_skip(first))
        else:
            partial @= _to_destination(target.event_ref, hit_time)
    else:
        destination = _marker(target.event_ref)
        partial.distance @= _fragment(target.event_ref, destination.event_start, hit_time).distance
    # An immutable anchor is already an atomic marker state. The intervening
    # complete links come directly from the index, without reintegrating its
    # first event or evaluating a zero-width fragment at the final anchor.
    if published and not reverse:
        result @= partial.distance
        if first_ordinal <= last_ordinal:
            result @= _range_apply(group, first_ordinal, last_ordinal, result)
    else:
        transfer = AffineTransfer.identity()
        if first_ordinal <= last_ordinal:
            transfer @= _range_transfer(group, first_ordinal, last_ordinal, published)
        if reverse:
            if published:
                transfer @= _published_then(partial, transfer)
                result @= transfer.distance.neg().published_div(transfer.ratio)
            else:
                transfer @= partial.then(transfer)
                result @= transfer.distance.neg().div(transfer.ratio)
        else:
            result @= transfer.apply(partial.distance)
    return result


def _run_coordinate(ref: int, now: float) -> AccurateScalar:
    result = +AccurateScalar
    marker = _marker(ref)
    if marker.transition_style == TransitionStyle.SCROLL:
        start = _marker(marker.run_first)
        result @= _width(start.event_start, now).scale(start.timescale)
    else:
        result @= marker.run_prefix.add(_integral(ref, marker.event_start, now))
    return result


def _locate_frame(group: TimescaleGroupLike, now: float) -> int:
    """Constant work within an event; bounded forward walk before indexed seek."""
    found = group.current_event if group.time_valid else 0
    settled = False
    if group.time_valid:
        for _ in range(4):
            next_ref = group.first_ref.index if found == 0 else _marker(found).next_ref.index
            start_ok = found == 0 or _marker(found).event_start <= now
            if start_ok and (next_ref == 0 or now < _marker(next_ref).event_start):
                settled = True
                break
            if next_ref > 0 and _marker(next_ref).event_start <= now:
                found = next_ref
            else:
                break
    if not settled:
        found = locate_time(group.index, now)
    return found


def _prepare_timescale_curve(entity: TimescaleGroupLike, marker: TimescaleChangeLike, now: float):
    """Use immutable slope/curvature; evaluate one short polynomial piece.

    TIMESCALE has unit transfer ratios, so future_ratio/past_ratio hold the
    current quadratic coefficient and midpoint speed respectively in this mode.
    SCROLL continues to store its actual ratios in those fields.
    """
    entity.certified_current_speed = AccurateScalar.of(marker.timescale)
    local = +AccurateScalar
    if entity.current_constant:
        local @= _width(marker.event_start, now).scale(marker.timescale)
    else:
        destination = _marker(marker.next_ref.index)
        middle = _midpoint_delta(marker, now)
        right_piece = middle.hi >= 0
        if marker.timescale_ease == EaseType.LINEAR:
            entity.future_ratio = AccurateScalar.of(0)
            entity.certified_current_speed = AccurateScalar.of(marker.timescale).add(
                marker.ratio_or_curve.mul(_width(marker.event_start, now)))
        else:
            entity.future_ratio = +marker.ratio_or_curve
            if marker.timescale_ease >= EaseType.IN_OUT_QUAD and right_piece:
                entity.future_ratio = entity.future_ratio.neg()
            anchor_speed = AccurateScalar.of(marker.timescale)
            offset = _width(marker.event_start, now)
            if marker.timescale_ease == EaseType.OUT_QUAD or (
                marker.timescale_ease == EaseType.IN_OUT_QUAD and right_piece
            ):
                anchor_speed @= AccurateScalar.of(destination.timescale)
                offset @= _width(marker.event_end, now)
            elif marker.timescale_ease == EaseType.OUT_IN_QUAD:
                entity.past_ratio = AccurateScalar.of(marker.timescale).add(
                    AccurateScalar.of(destination.timescale)).scale(.5)
                anchor_speed @= entity.past_ratio
                offset @= middle
            entity.certified_current_speed = anchor_speed.add(entity.future_ratio.mul(offset).mul(offset))
        endpoint_speed = AccurateScalar.of(marker.timescale if not right_piece else destination.timescale)
        width = +AccurateScalar
        if right_piece:
            width @= _width(now, marker.event_end)
        else:
            width @= _width(marker.event_start, now)
        local @= polynomial_piece_integral(endpoint_speed, entity.certified_current_speed, entity.future_ratio, width)
        if right_piece:
            local @= marker.own_distance.sub(_skip(destination)).sub(local)
    if entity.current_constant:
        entity.current_speed = marker.timescale
    else:
        entity.current_speed = entity.certified_current_speed.to_float()
    entity.past_distance = marker.run_prefix.add(local)
    if marker.run_end > 0:
        entity.future_distance = marker.run_suffix.sub(local)


def prepared_time_matches(stored: float, now: float) -> bool:
    """Development assertion only: allow one binary32 entity-storage rounding."""
    return abs(stored - now) <= 2 * UNIT_ROUNDOFF * max(abs(stored), abs(now)) + 2.0**-149


def prepare_group(group: int | EntityRef, now: float):
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return
    entity = _require_group(index)
    if entity.time_valid and entity.last_updated == now:
        return
    current_event = _locate_frame(entity, now)
    entity.last_updated = now
    entity.time_valid = True
    entity.current_event = current_event
    if entity.current_event == 0:
        entity.current_run = 0
        entity.current_constant = True
        entity.current_run_end = entity.first_ref.index
        entity.current_speed = 1.0
        entity.certified_current_speed = AccurateScalar.of(1)
        entity.hide_notes = False
        entity.future_distance = AccurateScalar.of(0)
        if entity.first_ref.index > 0:
            first = _marker(entity.first_ref.index)
            entity.future_distance = _width(now, first.event_start).add(_skip(first))
        return
    marker = _marker(entity.current_event)
    entity.current_run = marker.run_first
    entity.current_constant = (
        marker.next_ref.index == 0 or marker.timescale_ease == EaseType.NONE
        or marker.timescale == _marker(marker.next_ref.index).timescale
    )
    entity.current_run_end = marker.run_end
    entity.hide_notes = marker.hide_notes
    if marker.transition_style == TransitionStyle.SCROLL:
        entity.certified_current_speed = event_speed(marker.index, now)
        entity.current_speed = entity.certified_current_speed.to_float()
        start = _marker(marker.run_first)
        entity.past_distance = _width(start.event_start, now).scale(start.timescale)
        current_speed = +entity.certified_current_speed
        entity.past_ratio = AccurateScalar.of(start.timescale).div(current_speed)
        if marker.run_end > 0:
            end = _marker(marker.run_end)
            entity.future_ratio = current_speed.div(AccurateScalar.of(end.timescale))
            entity.future_distance = current_speed.mul(_width(now, end.event_start))
    else:
        _prepare_timescale_curve(entity, marker, now)


def try_prepare_trajectory(
    group: int | EntityRef,
    target_time: float,
    target_position: TargetPosition,
    cache: TrajectoryCache,
    now: float,
    target_ref: int = 0,
    distance_tolerance: float = -1,
) -> bool:
    """Complete cheap work, or leave an explicit invalid cold-refresh request.

    On False the cache metadata is current, and value.hi temporarily carries
    the publication allowance. Its remaining value fields must not be read.
    """
    index = _group_index(group)
    kind = CacheKind.IDENTITY
    run = 0
    anchor = 0
    if index > 0 and not Options.disable_timescale:
        entity = _require_group(index)
        assert entity.time_valid, "Timescale group must update before its consumers"
        assert prepared_time_matches(entity.last_updated, now), "Timescale group must update before its consumers"
        if target_ref > 0 and cache.valid and cache.target_ref == target_ref and cache.run_ref == entity.current_run:
            return True
        if entity.marker_count > 0:
            run = entity.current_run
            target_run = 0 if target_position.event_ref == 0 else _marker(target_position.event_ref).run_first
            if target_run == run:
                kind = CacheKind.SAME if run > 0 else CacheKind.PRELUDE
                anchor = run
            elif target_position.event_ref == 0 or (
                run > 0 and _marker(target_position.event_ref).ordinal < _marker(run).ordinal
            ):
                kind = CacheKind.PAST
                anchor = run
            else:
                kind = CacheKind.FUTURE
                anchor = entity.current_run_end
    if (
        target_ref > 0
        and cache.valid
        and cache.target_ref == target_ref
        and cache.run_ref == run
        and cache.kind == kind
        and cache.anchor_ref == anchor
    ):
        return True
    if distance_tolerance < 0 and kind in (CacheKind.SAME, CacheKind.FUTURE, CacheKind.PAST):
        distance_tolerance = _require_group(index).effective_preempt * 1e-5
    allowance = distance_tolerance * (1 - 8 * UNIT_ROUNDOFF)
    if kind in (CacheKind.FUTURE, CacheKind.PAST) and run > 0 and _marker(run).transition_style == TransitionStyle.SCROLL:
        relative_speed = _marker(anchor).timescale / _marker(run).run_peak_speed
        if relative_speed < 2.0**-100:
            allowance = 0
        else:
            allowance *= relative_speed
    # The relative-error guard assumes normal arithmetic. Extremely small
    # positive allowances reject inexact reuse rather than round upward at
    # the subnormal floor; the accurate immutable query remains available.
    if allowance < 2.0**-100:
        allowance = 0
    reused = False
    if target_ref > 0 and cache.valid and cache.target_ref == target_ref:
        rebase_run = 0
        if cache.kind == CacheKind.FUTURE and cache.anchor_ref == run:
            if kind == CacheKind.SAME:
                reused = cache.value.error_at_most(allowance)
            elif kind == CacheKind.FUTURE:
                rebase_run = run
        elif (
            cache.kind in (CacheKind.SAME, CacheKind.PAST) and kind == CacheKind.PAST and cache.run_ref > 0
            and _marker(cache.run_ref).run_end == run
        ):
            rebase_run = cache.run_ref
        if rebase_run > 0:
            source = _marker(rebase_run)
            candidate = +AccurateScalar
            if cache.kind == CacheKind.SAME:
                candidate @= source.run_suffix.sub(cache.value)
            elif kind == CacheKind.PAST:
                candidate @= cache.value.add(source.run_suffix)
            else:
                candidate @= cache.value.sub(source.run_suffix)
            if source.transition_style == TransitionStyle.SCROLL:
                candidate @= candidate.div(_scroll_run_ratio(source))
            reused = candidate.error_at_most(allowance)
            if reused:
                cache.value = +candidate
    cache.target_ref = target_ref
    cache.run_ref = run
    cache.kind = kind
    cache.anchor_ref = anchor
    if kind in (CacheKind.IDENTITY, CacheKind.PRELUDE):
        cache.value = AccurateScalar.of(0)
        reused = True
    cache.valid = reused
    if not reused:
        cache.value.hi = allowance
    return reused


def complete_trajectory_refresh(
    group: int | EntityRef, target_time: float, target_position: TargetPosition, cache: TrajectoryCache
):
    """Complete one request left by try_prepare_trajectory in this callback."""
    assert not cache.valid, "Cold trajectory refresh requires an outstanding request"
    allowance = cache.value.hi
    if cache.kind == CacheKind.SAME:
        cache.value = _run_coordinate(target_position.event_ref, target_time)
    elif cache.kind in (CacheKind.FUTURE, CacheKind.PAST):
        entity = _require_group(_group_index(group))
        # Keep the large cold query at one compiler callsite. Cache hits return
        # before this loop, and an accepted publication takes only one pass.
        for attempt in range(2):
            cache.value = _target_from_anchor(entity, cache.anchor_ref, target_time, target_position, published=attempt == 0)
            if attempt == 1 or cache.value.error_at_most(allowance):
                break
        if cache.kind == CacheKind.PAST:
            cache.value = cache.value.neg()
    cache.valid = True


def prepare_trajectory(
    group: int | EntityRef,
    target_time: float,
    target_position: TargetPosition,
    cache: TrajectoryCache,
    now: float,
    target_ref: int = 0,
    distance_tolerance: float = -1,
):
    if not try_prepare_trajectory(group, target_time, target_position, cache, now, target_ref, distance_tolerance):
        complete_trajectory_refresh(group, target_time, target_position, cache)


def evaluate_trajectory(
    group: int | EntityRef,
    target_time: float,
    target_position: TargetPosition,
    cache: TrajectoryCache,
    now: float,
    accurate: bool = False,
) -> AccurateScalar:
    result = +AccurateScalar
    index = _group_index(group)
    assert cache.valid, "Trajectory must be prepared by its consumer before evaluation"
    if cache.kind in (CacheKind.IDENTITY, CacheKind.PRELUDE):
        result @= _width(now, target_time)
    else:
        entity = _require_group(index)
        assert entity.time_valid, "Trajectory group was not prepared for the current frame"
        assert prepared_time_matches(entity.last_updated, now), "Trajectory group was not prepared for the current frame"
        assert entity.current_run == cache.run_ref, "Trajectory group was not prepared for the current run"
        scroll = entity.current_event > 0 and _marker(entity.current_event).transition_style == TransitionStyle.SCROLL
        if cache.kind == CacheKind.FUTURE:
            if not scroll:
                if accurate:
                    result @= cache.value.add(entity.future_distance)
                else:
                    result @= cache.value.published_add(entity.future_distance)
            elif accurate:
                result @= entity.future_ratio.mul(cache.value).add(entity.future_distance)
            else:
                result @= entity.future_ratio.published_mul(cache.value).published_add(entity.future_distance)
        elif cache.kind == CacheKind.PAST:
            if not scroll:
                if accurate:
                    result @= cache.value.add(entity.past_distance).neg()
                else:
                    result @= cache.value.published_add(entity.past_distance).neg()
            elif accurate:
                result @= cache.value.add(entity.past_distance).div(entity.past_ratio).neg()
            else:
                result @= cache.value.published_add(entity.past_distance).published_div(entity.past_ratio).neg()
        else:
            marker = _marker(entity.current_event)
            if scroll:
                if accurate:
                    result @= entity.certified_current_speed.mul(_width(now, target_time))
                else:
                    result @= entity.certified_current_speed.published_mul(_width(now, target_time))
            elif accurate and entity.current_event == target_position.event_ref:
                result @= _integral(marker.index, now, target_time)
            else:
                result @= cache.value.sub(entity.past_distance)
    return result


def group_hide_notes(group: int | EntityRef) -> bool:
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return False
    return _require_group(index).hide_notes


def group_force_note_speed(group: int | EntityRef) -> float:
    index = _group_index(group)
    if index <= 0:
        return 0.0
    return timescale_group_archetype().at(index).force_note_speed


def group_preempt_time(group: int | EntityRef) -> float:
    index = _group_index(group)
    if index <= 0:
        return Layout.default_preempt
    return timescale_group_archetype().at(index).effective_preempt


def iter_timescale_changes_in_group_from_time(group: int | EntityRef, now: float) -> Iterator[TimescaleChangeLike]:
    index = _group_index(group)
    if index <= 0 or Options.disable_timescale:
        return
    entity = _require_group(index)
    ref = locate_time(index, now)
    if ref == 0:
        ref = entity.first_ref.index
    yield from iter_timescale_changes(ref)
