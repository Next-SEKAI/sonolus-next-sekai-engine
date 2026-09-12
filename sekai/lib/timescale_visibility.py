from math import inf

from sonolus.script.archetype import EntityRef
from sonolus.script.array import Dim
from sonolus.script.containers import VarArray
from sonolus.script.interval import Interval
from sonolus.script.record import Record

from sekai.lib.ease import EaseType
from sekai.lib.layout import conservative_progress_bounds
from sekai.lib.options import Options
from sekai.lib.timescale import (
    DISTANCE_LIMIT,
    MIN_START_TIME,
    TargetPosition,
    _scroll_speed,
    distance_to_target,
    locate_target,
    locate_time_from,
    timescale_change_archetype,
    timescale_group_archetype,
)
from sekai.lib.timescale_math import integrate_times, speed_at

SPAWN_STEP = 1 / 120
SPAWN_PADDING = 0.01


class VisibilitySource(Record):
    group: int
    hit_time: float
    preempt: float
    offset_min: float
    offset_max: float
    clamp_after_hit: bool


def _distance_bounds(
    source: VisibilitySource, ref: int, anchor: float, distance: float, a: float, b: float
) -> Interval:
    result = Interval(-inf, inf)
    if source.clamp_after_hit and anchor >= source.hit_time:
        result @= Interval(0.0, 0.0)
        return result
    if not -inf < distance < inf:
        return result
    v0 = v1 = 1.0
    start, end = anchor, anchor + 1
    easing = EaseType.NONE
    scroll = False
    if ref > 0:
        event = timescale_change_archetype().at(ref)
        v0 = v1 = event.timescale
        start, end = event.event_start, event.event_start + 1
        scroll = event.transition_style == 1
        if event.next_ref.index > 0:
            v1 = timescale_change_archetype().at(event.next_ref.index).timescale
            end, easing = event.event_end, event.timescale_ease
    va = speed_at(v0, v1, easing, start, end, a)
    vb = speed_at(v0, v1, easing, start, end, b)
    # Allow for rounding in large intermediate values, even when the result is small.
    peak_speed = abs(v0) if easing == EaseType.NONE else max(abs(v0), abs(v1))
    magnitude = max(abs(distance), peak_speed * max(end - start, abs(anchor - start), abs(b - anchor)))
    if scroll:
        # Bound speed and width separately, then find the smallest and largest
        # of the four endpoint products. This also covers sign changes.
        va, vb = _scroll_speed(va), _scroll_speed(vb)
        width = distance / _scroll_speed(speed_at(v0, v1, easing, start, end, anchor))
        magnitude = max(magnitude, (abs(width) + abs(b - anchor)) * max(peak_speed, 1e-4))
        q = width - (a - anchor)
        r = q - (b - a)
        lower = min(va * q, va * r, vb * q, vb * r)
        upper = max(va * q, va * r, vb * q, vb * r)
    else:
        value = distance - integrate_times(v0, v1, easing, start, end, anchor, a)
        lower = value + min(0.0, -max(va, vb) * (b - a))
        upper = value + max(0.0, -min(va, vb) * (b - a))
    if not -inf < lower <= upper < inf:
        return result
    # When timescale speed stays at zero, only rounding needs extra margin.
    # Scroll still moves at zero because _scroll_speed enforces a minimum speed.
    stopped = not scroll and v0 == 0 and (easing == EaseType.NONE or v1 == 0)
    slack = (0.0 if stopped else 0.01) + source.preempt * 1e-4 + max(magnitude, abs(lower), abs(upper)) * 1e-6
    # If the distance was capped, we do not know how far it extends beyond the cap.
    result @= Interval(
        -inf if distance <= -DISTANCE_LIMIT else lower - slack, inf if distance >= DISTANCE_LIMIT else upper + slack
    )
    return result


def first_visible(
    sources: VarArray[VisibilitySource, Dim[4]], low: float, high: float, earliest: float, latest: float
) -> float:
    """Find an early spawn time by rejecting intervals that cannot be visible.

    Search earlier halves first as we subdivide the remaining intervals.
    Add a small margin so notes spawn before they might become visible.
    """
    if len(sources) == 0 or latest < earliest:
        return inf
    targets = VarArray[TargetPosition, Dim[4]].new()
    refs = VarArray[int, Dim[4]].new()
    for source in sources:
        target = locate_target(source.group, source.hit_time)
        targets.append(target)
        refs.append(target.event_ref)
    anchor = earliest
    while anchor <= latest:
        distances = VarArray[float, Dim[4]].new()
        piece_end = latest
        for i in range(len(sources)):
            source = sources[i]
            ref = locate_time_from(source.group, anchor, refs[i])
            refs[i] = ref
            clamped = source.clamp_after_hit and anchor >= source.hit_time
            distances.append(
                0.0 if clamped else distance_to_target(source.group, ref, anchor, targets[i], source.hit_time)
            )
            if anchor < source.hit_time:
                piece_end = min(piece_end, source.hit_time)
            if not clamped:
                if ref > 0:
                    event = timescale_change_archetype().at(ref)
                    if event.next_ref.index > 0:
                        piece_end = min(piece_end, event.event_end)
                elif source.group > 0 and not Options.disable_timescale:
                    first = timescale_group_archetype().at(source.group).first_ref.index
                    if first > 0:
                        piece_end = min(piece_end, timescale_change_archetype().at(first).event_start)
        left, right = anchor, piece_end
        while True:
            # Reject only when all sources stay on the same side of the visible range.
            # A connector can be visible between two offscreen endpoints on opposite sides.
            above = below = True
            for i in range(len(sources)):
                source = sources[i]
                bounds = _distance_bounds(source, refs[i], anchor, distances[i], left, right)
                above = above and bounds.start > source.preempt * (1 - low - source.offset_min)
                below = below and bounds.end < source.preempt * (1 - high - source.offset_max)
            if above or below:
                if right == piece_end:
                    break
                left, right = right, piece_end
            else:
                middle = left + (right - left) * 0.5
                if right - left <= SPAWN_STEP or middle <= left or middle >= right:
                    return max(earliest, left - SPAWN_PADDING)
                # Search the earlier half first to find the earliest possible visibility.
                right = middle
        if anchor == latest:
            break
        # Apply all markers at this boundary before searching the next interval.
        anchor = piece_end
    return inf


def get_sources_visual_spawn_time(sources: VarArray[VisibilitySource, Dim[4]], latest: float) -> float:
    bounds = conservative_progress_bounds()
    if len(sources) > 1:
        first = sources[0]
        if first.group > 0 and not Options.disable_timescale:
            group = timescale_group_archetype().at(first.group)
            proxy = VisibilitySource(
                first.group, first.hit_time, first.preempt, first.offset_min, first.offset_max, False
            )
            reusable = group.monotone_targets and first.preempt > 0
            for source in sources:
                floor = source.preempt * (1 - bounds.end - source.offset_max)
                ceiling = source.preempt * (1 - bounds.start - source.offset_min)
                reusable = (
                    reusable
                    and source.group == proxy.group
                    and source.preempt == proxy.preempt
                    and floor <= 0 <= ceiling
                )
                proxy.hit_time = min(proxy.hit_time, source.hit_time)
                proxy.offset_min = min(proxy.offset_min, source.offset_min)
                proxy.offset_max = max(proxy.offset_max, source.offset_max)
            if reusable and proxy.hit_time >= MIN_START_TIME:
                # Before the earliest hit, no source is clamped or closer than the proxy.
                # The proxy also has the widest visible distance range. All sources are
                # therefore out of view until the proxy could be visible. The proxy is
                # within its range at its hit time because the range includes zero, so
                # its spawn time is a safe starting point for the segment search.
                proxies = VarArray[VisibilitySource, Dim[4]].new()
                proxies.append(proxy)
                earliest = _search_with_spawn_cursor(proxies, bounds, latest)
                # Only the proxy search updates the cursor. Using the segment's later
                # spawn time could skip visible intervals in future searches.
                return first_visible(sources, bounds.start, bounds.end, earliest, latest)
    return _search_with_spawn_cursor(sources, bounds, latest)


def _search_with_spawn_cursor(sources: VarArray[VisibilitySource, Dim[4]], bounds: Interval, latest: float) -> float:
    """Find a spawn time, using the group's previous result when it is safe to reuse."""
    earliest = MIN_START_TIME
    cache_group = 0
    ceiling = 0.0
    if len(sources) == 1:
        source = sources[0]
        if source.group > 0 and not source.clamp_after_hit and not Options.disable_timescale:
            group = timescale_group_archetype().at(source.group)
            floor = source.preempt * (1 - bounds.end - source.offset_max)
            ceiling = source.preempt * (1 - bounds.start - source.offset_min)
            # With nonnegative speeds and skips, a later hit cannot have a smaller distance.
            # If its distance ceiling does not grow, its first visibility cannot move earlier.
            if group.monotone_targets and floor <= 0 <= ceiling:
                cache_group = source.group
                if (
                    group.spawn_cursor_valid
                    and source.hit_time >= group.last_spawn_target
                    and ceiling <= group.last_spawn_ceiling
                    and group.last_spawn_time <= latest
                ):
                    earliest = max(earliest, group.last_spawn_time)
    result = first_visible(sources, bounds.start, bounds.end, earliest, latest)
    if cache_group > 0 and result < inf:
        group = timescale_group_archetype().at(cache_group)
        group.last_spawn_target = sources[0].hit_time
        group.last_spawn_ceiling = ceiling
        group.last_spawn_time = result
        group.spawn_cursor_valid = True
    return result


def group_index(group: int | EntityRef) -> int:
    return group.index if isinstance(group, EntityRef) else group
