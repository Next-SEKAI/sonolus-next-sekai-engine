"""Conservative chronological visibility of polynomial timescale trajectories.

Search continuous pieces independently and test the completed state at every
boundary. Bernstein hulls include interior extrema and tangencies without
interpolating through instantaneous changes. Sources describe a convex hull,
which also encloses clamped attachments and connector interiors.
"""

from enum import IntEnum
from math import inf
from typing import Self

from sonolus.script.archetype import EntityRef
from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.interval import Interval
from sonolus.script.record import Record

from sekai.lib.ease import EaseType
from sekai.lib.layout import conservative_progress_bounds
from sekai.lib.options import Options
from sekai.lib.timescale import (
    MIN_START_TIME,
    distance_between,
    locate_time,
    timescale_change_archetype,
    timescale_group_archetype,
)
from sekai.lib.timescale_math import AccurateScalar, _two_sum

VISIBILITY_TIME_RESOLUTION = 0.00025
MAX_CELL_REFINEMENTS = 4096


class VisibilitySource(Record):
    group: int
    hit_time: float
    preempt: float
    offset_min: float
    offset_max: float
    clamp_after_hit: bool


class SpawnStatus(IntEnum):
    NO_ENTRY = 0
    VERIFIED_ENTRY = 1
    POSSIBLE_ENTRY = 2


class SpawnReason(IntEnum):
    EXCLUDED = 0
    INTERIOR_POINT = 1
    HULL_OR_ROUNDING = 2
    TIME_RESOLUTION = 3
    WORK_LIMIT = 4
    UNRESOLVED_BOUNDARY = 5


class SpawnResult(Record):
    time: float
    status: SpawnStatus
    bracket: Interval
    reason: SpawnReason
    cells: int
    refinements: int


class DistanceRegion(Record):
    low: AccurateScalar
    high: AccurateScalar


class SubtreeCandidate(Record):
    index: int
    end: float
    next_index: int
    mode: int


class CubicBounds(Record):
    b0: AccurateScalar
    b1: AccurateScalar
    b2: AccurateScalar
    b3: AccurateScalar

    def values(self) -> VarArray[AccurateScalar, Dim[4]]:
        result = VarArray[AccurateScalar, Dim[4]].new()
        result.append(self.b0)
        result.append(self.b1)
        result.append(self.b2)
        result.append(self.b3)
        return result

    def hull(self, other: Self) -> Self:
        left = self.values()
        right = other.values()
        for i in range(4):
            left[i] = left[i].hull(right[i])
        return type(self)(left[0], left[1], left[2], left[3])

    def split(self, fraction: AccurateScalar, keep_right: bool) -> Self:
        result = +type(self)
        points = VarArray[AccurateScalar, Dim[4]].new()
        points.append(self.b0)
        points.append(self.b1)
        points.append(self.b2)
        points.append(self.b3)
        left = VarArray[AccurateScalar, Dim[4]].new()
        right = VarArray[AccurateScalar, Dim[4]].new()
        left.append(self.b0)
        right.append(self.b3)
        for level in range(3):
            for i in range(3 - level):
                points[i] = _mix(points[i], points[i + 1], fraction)
            left.append(points[0])
            right.append(points[2 - level])
        if keep_right:
            result @= type(self)(right[3], right[2], right[1], right[0])
        else:
            result @= type(self)(left[0], left[1], left[2], left[3])
        return result

    def restrict(self, start: float, end: float) -> Self:
        result = +self
        if start == 1.0:
            result @= type(self)(self.b3, self.b3, self.b3, self.b3)
            return result
        fraction = +AccurateScalar
        for part in range(2):
            split = False
            keep_right = False
            if part == 0 and start > 0.0:
                fraction @= AccurateScalar.of(start)
                keep_right = True
                split = True
            elif part == 1 and end < 1.0:
                fraction @= (
                    AccurateScalar.of(end)
                    .sub(AccurateScalar.of(start))
                    .div(AccurateScalar.of(1.0).sub(AccurateScalar.of(start)))
                )
                split = True
            if split:
                result @= result.split(fraction, keep_right)
        return result


def _mix(a: AccurateScalar, b: AccurateScalar, fraction: AccurateScalar) -> AccurateScalar:
    return a.mul(AccurateScalar.of(1.0).sub(fraction)).add(b.mul(fraction))


def _earlier_mapped_time(start: float, end: float, fraction: float, floor: float) -> float:
    if fraction == 0.0:
        return start
    mapped = start + (end - start) * fraction
    # Cover binary32 subtraction/multiplication/addition and final storage. An
    # authored boundary (fraction zero) is already an exact quantized input.
    rounding = max(1.0, abs(start), abs(end)) * (2.0**-21)
    return max(floor, mapped - rounding)


def _clock_midpoint_side(t: float, start: float, end: float) -> int:
    """Compare a clock input with the exact midpoint, preserving its low bit.

    TwoSum followed by exact binary scaling retains an unrepresentable half
    clock tick. Near the midpoint the final subtraction is exact by Sterbenz;
    farther away its sign cannot be changed by the small midpoint residual.
    """
    pair = _two_sum(start, end)
    delta = t - pair.hi * 0.5
    correction = pair.lo * 0.5
    if delta < correction:
        return -1
    if delta > correction:
        return 1
    return 0


def _speed_at(event_index: int, t: AccurateScalar, half: int = 0) -> AccurateScalar:
    result = +AccurateScalar
    if event_index <= 0:
        result @= AccurateScalar.of(1.0)
        return result
    event = timescale_change_archetype().at(event_index)
    if event.next_ref.index <= 0 or event.timescale_ease == EaseType.NONE:
        result @= AccurateScalar.of(event.timescale)
        return result
    next_event = timescale_change_archetype().at(event.next_ref.index)
    duration = AccurateScalar.of(event.event_end).sub(AccurateScalar.of(event.event_start))
    u = t.sub(AccurateScalar.of(event.event_start)).div(duration)
    one = AccurateScalar.of(1.0)
    complement = one.sub(u)
    shape = +u
    match event.timescale_ease:
        case EaseType.IN_QUAD:
            shape @= u.mul(u)
        case EaseType.OUT_QUAD:
            shape @= one.sub(complement.mul(complement))
        case EaseType.IN_OUT_QUAD:
            if half < 0 or (half == 0 and _clock_midpoint_side(t.to_float(), event.event_start, event.event_end) <= 0):
                shape @= u.mul(u).scale(2.0)
            else:
                shape @= one.sub(complement.mul(complement).scale(2.0))
        case EaseType.OUT_IN_QUAD:
            if half < 0 or (half == 0 and _clock_midpoint_side(t.to_float(), event.event_start, event.event_end) <= 0):
                shape @= u.mul(complement).scale(2.0)
            else:
                shifted = u.sub(AccurateScalar.of(0.5))
                shape @= shifted.mul(shifted).scale(2.0).add(AccurateScalar.of(0.5))
    result @= AccurateScalar.of(event.timescale).add(
        AccurateScalar.of(next_event.timescale).sub(AccurateScalar.of(event.timescale)).mul(shape)
    )
    return result


def _controls_for_half(
    initial: AccurateScalar,
    start: float,
    end: float,
    event_index: int,
    half: int,
) -> CubicBounds:
    result = +CubicBounds
    a = AccurateScalar.of(start)
    duration = AccurateScalar.of(end).sub(a)
    scroll = False
    if event_index > 0:
        scroll = timescale_change_archetype().at(event_index).transition_style == 1
    values = VarArray[AccurateScalar, Dim[4]].new()
    point = +a
    samples = 3
    if scroll:
        samples = 4
    for sample in range(samples):
        point @= a
        sample_half = half
        if sample == 1:
            point @= a.add(duration.scale(0.5))
        elif sample == 2:
            point @= a.add(duration)
        elif sample == 3:
            sample_half = 0
        values.append(_speed_at(event_index, point, sample_half))
    v0 = values[0]
    vm = values[1]
    v2 = values[2]
    v1 = vm.scale(2.0).sub(v0.add(v2).scale(0.5))
    if scroll:
        k0 = initial.div(values[3])
        k1 = k0.sub(duration)
        result @= CubicBounds(
            v0.mul(k0),
            v1.mul(k0).scale(2.0).add(v0.mul(k1)).div(AccurateScalar.of(3.0)),
            v2.mul(k0).add(v1.mul(k1).scale(2.0)).div(AccurateScalar.of(3.0)),
            v2.mul(k1),
        )
        return result
    third = duration.div(AccurateScalar.of(3.0))
    b1 = initial.sub(v0.mul(third))
    b2 = b1.sub(v1.mul(third))
    b3 = b2.sub(v2.mul(third))
    result @= CubicBounds(initial, b1, b2, b3)
    return result


def _source_controls(source: VisibilitySource, start: float, end: float) -> CubicBounds:
    initial = AccurateScalar.of(0.0)
    if not source.clamp_after_hit or start < source.hit_time:
        initial @= distance_between(source.group, start, source.hit_time)
    return _source_controls_at_distance(source, start, end, initial)


def _source_controls_at_distance(
    source: VisibilitySource, start: float, end: float, initial: AccurateScalar
) -> CubicBounds:
    result = +CubicBounds
    if start == end:
        result @= CubicBounds(initial, initial, initial, initial)
        return result
    if source.clamp_after_hit and start >= source.hit_time:
        zero = AccurateScalar.of(0.0)
        result @= CubicBounds(zero, zero, zero, zero)
        return result
    event_index = locate_time(source.group, start)
    half = 0
    straddles = False
    if event_index > 0:
        event = timescale_change_archetype().at(event_index)
        if event.next_ref.index > 0 and event.timescale_ease in (EaseType.IN_OUT_QUAD, EaseType.OUT_IN_QUAD):
            if _clock_midpoint_side(end, event.event_start, event.event_end) <= 0:
                half = -1
            elif _clock_midpoint_side(start, event.event_start, event.event_end) >= 0:
                half = 1
            else:
                half = -1
                straddles = True
    passes = 1
    if straddles:
        passes = 2
    for part in range(passes):
        current_half = half
        if part > 0:
            current_half = 1
        current = _controls_for_half(initial, start, end, event_index, current_half)
        if part == 0:
            result @= current
        else:
            # The real speed lies between both quadratic continuations.
            # Integrating from the common anchor encloses timescale distance;
            # common D(start)/v_actual(start) encloses scroll distance.
            result @= result.hull(current)
    return result


def _next_piece_end(source: VisibilitySource, start: float, latest: float) -> float:
    result = latest
    if start < source.hit_time:
        result = min(result, source.hit_time)
    if source.clamp_after_hit and start >= source.hit_time:
        return result
    event_index = locate_time(source.group, start)
    if event_index > 0:
        event = timescale_change_archetype().at(event_index)
        if event.next_ref.index > 0:
            result = min(result, event.event_end)
            if event.timescale_ease in (EaseType.IN_OUT_QUAD, EaseType.OUT_IN_QUAD):
                midpoint = _two_sum(event.event_start, event.event_end)
                middle = midpoint.hi * 0.5
                tick = 2.0 ** (AccurateScalar.of(middle).exponent - 24)
                lower = middle
                upper = middle
                if midpoint.lo < 0:
                    lower -= tick
                elif midpoint.lo > 0:
                    upper += tick
                if start < lower:
                    result = min(result, lower)
                elif start < upper:
                    result = min(result, upper)
    elif source.group > 0 and not Options.disable_timescale:
        first = timescale_group_archetype().at(source.group).first_ref.index
        if first > 0:
            result = min(result, timescale_change_archetype().at(first).event_start)
    return result


def _source_distance_region(
    source: VisibilitySource, progress_min: float, progress_max: float, outward: bool = True
) -> DistanceRegion:
    """Convert progress guards, optionally widening them for conservative search."""
    preempt = AccurateScalar.of(source.preempt)
    low = AccurateScalar.of(1.0).sub(AccurateScalar.of(progress_max)).sub(AccurateScalar.of(source.offset_max)).mul(preempt)
    high = (
        AccurateScalar.of(1.0).sub(AccurateScalar.of(progress_min)).sub(AccurateScalar.of(source.offset_min)).mul(preempt)
    )
    if outward:
        low @= low.lower_bound()
        high @= high.upper_bound()
    return DistanceRegion(low, high)


def _cell_classification(
    sources: VarArray[VisibilitySource, Dim[4]],
    controls: VarArray[CubicBounds, Dim[4]],
    start: float,
    end: float,
    progress_min: float,
    progress_max: float,
) -> int:
    """Return -1 excluded, 1 possible at start, 2 verified interior, or zero."""
    entirely_above = True
    entirely_below = True
    starts_above = True
    starts_below = True
    first_value = +AccurateScalar
    for i in range(len(sources)):
        source = sources[i]
        bounds = controls[i].restrict(start, end)
        region = _source_distance_region(source, progress_min, progress_max)
        low = region.low
        high = region.high
        values = bounds.values()
        for j in range(4):
            above = values[j].definitely_greater(high)
            below = values[j].definitely_less(low)
            entirely_above = entirely_above and above
            entirely_below = entirely_below and below
            if j == 0:
                starts_above = starts_above and above
                starts_below = starts_below and below
                if i == 0:
                    first_value @= values[j]
    if entirely_above or entirely_below:
        return -1
    if not starts_above and not starts_below:
        if len(sources) == 1 and sources[0].offset_min == sources[0].offset_max:
            # Outward search bounds permit early spawning, but cannot prove
            # entry into the requested interval. Verify its original bounds.
            requested = _source_distance_region(sources[0], progress_min, progress_max, outward=False)
            if first_value.definitely_greater(requested.low) and first_value.definitely_less(requested.high):
                return 2
        return 1
    return 0


def _subtree_last(index: int) -> int:
    current = index
    while timescale_change_archetype().at(current).tree_right > 0:
        current = timescale_change_archetype().at(current).tree_right
    return current


def _subtree_excluded_at_distances(
    sources: VarArray[VisibilitySource, Dim[4]],
    candidate: SubtreeCandidate,
    distances: VarArray[AccurateScalar, Dim[4]],
    progress_min: float,
    progress_max: float,
) -> bool:
    node = timescale_change_archetype().at(candidate.index)
    entirely_above = True
    entirely_below = True
    for i in range(len(sources)):
        at_end = distances[i]
        low = +at_end
        high = +at_end
        if candidate.mode == 1:
            low @= node.suffix_r_min.mul(at_end)
            high @= node.suffix_r_max.mul(at_end).add(node.suffix_b_max)
        else:
            low @= at_end.add(node.suffix_r_min)
            high @= at_end.add(node.suffix_r_max)
        region = _source_distance_region(sources[i], progress_min, progress_max)
        entirely_above = entirely_above and low.definitely_greater(region.high)
        entirely_below = entirely_below and high.definitely_less(region.low)
    return entirely_above or entirely_below


def _initial_subtree_cursor(sources: VarArray[VisibilitySource, Dim[4]]) -> int:
    source_group = sources[0].group
    if source_group <= 0 or Options.disable_timescale:
        return 0
    for source in sources:
        if source.group != source_group or source.clamp_after_hit:
            return 0
    return timescale_group_archetype().at(source_group).root


def _next_subtree_candidate(
    sources: VarArray[VisibilitySource, Dim[4]], start: float, latest: float, node_index: int
) -> SubtreeCandidate:
    """Find a complete-batch subtree on the path containing the search cursor."""
    result = SubtreeCandidate(0, start, 0, 0)
    if node_index <= 0:
        return result
    source_group = sources[0].group
    group = timescale_group_archetype().at(source_group)
    ceiling = latest
    if group.mode == 1:
        for source in sources:
            ceiling = min(ceiling, source.hit_time)
    current = locate_time(source_group, start)
    if current <= 0:
        return result
    ordinal = timescale_change_archetype().at(current).ordinal
    while node_index > 0:
        node = timescale_change_archetype().at(node_index)
        next_index = 0
        if ordinal < node.ordinal:
            next_index = node.tree_left
        elif ordinal > node.ordinal:
            next_index = node.tree_right
        last = timescale_change_archetype().at(_subtree_last(node_index))
        end = last.event_end
        # distance_between(end,h) uses the completed batch state. A subtree
        # whose transfer ends at an intermediate state cannot share its anchor.
        completed_end = False
        if last.next_ref.index > 0:
            destination = timescale_change_archetype().at(last.next_ref.index)
            if destination.next_ref.index <= 0:
                completed_end = True
            else:
                completed_end = timescale_change_archetype().at(destination.next_ref.index).event_start > end
        if completed_end and start < end <= ceiling:
            result @= SubtreeCandidate(node_index, end, next_index, group.mode)
            return result
        node_index = next_index
    return result


def _skip_excluded_subtree(
    sources: VarArray[VisibilitySource, Dim[4]],
    start: float,
    latest: float,
    progress_min: float,
    progress_max: float,
) -> float:
    """Independent subtree query helper; the complete search shares its query loop."""
    cursor = _initial_subtree_cursor(sources)
    while cursor > 0:
        candidate = _next_subtree_candidate(sources, start, latest, cursor)
        if candidate.index <= 0:
            break
        distances = VarArray[AccurateScalar, Dim[4]].new()
        for source in sources:
            distances.append(distance_between(source.group, candidate.end, source.hit_time))
        if _subtree_excluded_at_distances(sources, candidate, distances, progress_min, progress_max):
            return candidate.end
        cursor = candidate.next_index
    return start


def first_visible_result(
    sources: VarArray[VisibilitySource, Dim[4]],
    progress_min: float,
    progress_max: float,
    earliest: float,
    latest: float,
) -> SpawnResult:
    """Share one compiled distance query for subtree ends and polynomial starts.

    Refine cached controls; test the final completed boundary as a constant cell.
    """
    result = +SpawnResult
    if len(sources) == 0 or latest < earliest:
        result @= SpawnResult(inf, SpawnStatus.NO_ENTRY, Interval(latest, latest), SpawnReason.EXCLUDED, 0, 0)
        return result
    start = earliest
    cell_count = 0
    refinement_count = 0
    while start <= latest:
        cursor = _initial_subtree_cursor(sources)
        advanced = False
        while not advanced:
            candidate = _next_subtree_candidate(sources, start, latest, cursor)
            end = latest
            query_time = start
            if candidate.index > 0:
                query_time = candidate.end
            elif start < latest:
                for source in sources:
                    end = min(end, _next_piece_end(source, start, latest))
                if end <= start:
                    result @= SpawnResult(
                        start,
                        SpawnStatus.POSSIBLE_ENTRY,
                        Interval(start, end),
                        SpawnReason.UNRESOLVED_BOUNDARY,
                        cell_count,
                        refinement_count,
                    )
                    return result

            distances = VarArray[AccurateScalar, Dim[4]].new()
            for source in sources:
                value = AccurateScalar.of(0.0)
                if not source.clamp_after_hit or query_time < source.hit_time:
                    value @= distance_between(source.group, query_time, source.hit_time)
                distances.append(value)

            if candidate.index > 0:
                if _subtree_excluded_at_distances(sources, candidate, distances, progress_min, progress_max):
                    start = candidate.end
                    advanced = True
                else:
                    cursor = candidate.next_index
                continue

            controls = VarArray[CubicBounds, Dim[4]].new()
            for i in range(len(sources)):
                controls.append(_source_controls_at_distance(sources[i], start, end, distances[i]))
            cell_count += 1
            pending = VarArray[Interval, Dim[64]].new()
            pending.append(Interval(0.0, 1.0))
            visits = 0
            while len(pending) > 0:
                cell = pending.pop()
                classification = _cell_classification(
                    sources, controls, cell.start, cell.end, progress_min, progress_max
                )
                cell_start = _earlier_mapped_time(start, end, cell.start, earliest)
                cell_end = start + (end - start) * cell.end
                refinement_count += 1
                if classification >= 1:
                    status = SpawnStatus.POSSIBLE_ENTRY
                    reason = SpawnReason.HULL_OR_ROUNDING
                    if classification == 2 and cell.start == 0.0:
                        status = SpawnStatus.VERIFIED_ENTRY
                        reason = SpawnReason.INTERIOR_POINT
                    bracket_end = start + (end - start) * cell.start
                    result @= SpawnResult(
                        cell_start, status, Interval(cell_start, bracket_end), reason, cell_count, refinement_count
                    )
                    return result
                if classification == 0:
                    resolution = max(VISIBILITY_TIME_RESOLUTION, abs(cell_start) * (2.0**-22))
                    if (end - start) * (cell.end - cell.start) <= resolution or visits >= MAX_CELL_REFINEMENTS:
                        reason = SpawnReason.TIME_RESOLUTION
                        if visits >= MAX_CELL_REFINEMENTS:
                            reason = SpawnReason.WORK_LIMIT
                        result @= SpawnResult(
                            cell_start,
                            SpawnStatus.POSSIBLE_ENTRY,
                            Interval(cell_start, cell_end),
                            reason,
                            cell_count,
                            refinement_count,
                        )
                        return result
                    middle = cell.start + (cell.end - cell.start) * 0.5
                    if middle <= cell.start or middle >= cell.end or len(pending) >= 62:
                        result @= SpawnResult(
                            cell_start,
                            SpawnStatus.POSSIBLE_ENTRY,
                            Interval(cell_start, cell_end),
                            SpawnReason.TIME_RESOLUTION,
                            cell_count,
                            refinement_count,
                        )
                        return result
                    pending.append(Interval(middle, cell.end))
                    pending.append(Interval(cell.start, middle))
                visits += 1
            if start == latest:
                result @= SpawnResult(
                    inf,
                    SpawnStatus.NO_ENTRY,
                    Interval(latest, latest),
                    SpawnReason.EXCLUDED,
                    cell_count,
                    refinement_count,
                )
                return result
            start = end
            advanced = True
    result @= SpawnResult(
        inf, SpawnStatus.NO_ENTRY, Interval(latest, latest), SpawnReason.EXCLUDED, cell_count, refinement_count
    )
    return result


def first_visible(
    sources: VarArray[VisibilitySource, Dim[4]],
    progress_min: float,
    progress_max: float,
    earliest: float,
    latest: float,
) -> float:
    return first_visible_result(sources, progress_min, progress_max, earliest, latest).time


def get_sources_visual_spawn_time(sources: VarArray[VisibilitySource, Dim[4]], latest: float) -> float:
    bounds = conservative_progress_bounds()
    earliest = MIN_START_TIME
    cache_group = 0
    ceiling = 0.0
    if len(sources) == 1:
        source = sources[0]
        if source.group > 0 and not source.clamp_after_hit and not Options.disable_timescale:
            group = timescale_group_archetype().at(source.group)
            region = _source_distance_region(source, bounds.start, bounds.end)
            zero = AccurateScalar.of(0.0)
            if group.mode == 1 and region.low.compare(zero) <= 0 and region.high.compare(zero) >= 0:
                cache_group = source.group
                # Search bounds are outward single-mantissa endpoints. Their
                # ordinary representations are exact cache keys, not rounded
                # approximations to the previous region's unrecorded bound.
                ceiling = region.high.to_float()
                if (
                    group.spawn_cursor_valid
                    and source.hit_time >= group.last_spawn_target
                    and ceiling <= group.last_spawn_ceiling
                    and group.last_spawn_time <= latest
                ):
                    earliest = max(earliest, group.last_spawn_time)
    result = first_visible_result(sources, bounds.start, bounds.end, earliest, latest)
    if cache_group > 0 and result.status != SpawnStatus.NO_ENTRY:
        group = timescale_group_archetype().at(cache_group)
        group.last_spawn_target = sources[0].hit_time
        group.last_spawn_ceiling = ceiling
        group.last_spawn_time = result.time
        group.spawn_cursor_valid = True
    return result.time


def group_index(group: int | EntityRef) -> int:
    if isinstance(group, EntityRef):
        return group.index
    return group
