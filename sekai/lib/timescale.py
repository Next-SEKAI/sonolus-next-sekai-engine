from __future__ import annotations

from collections.abc import Iterator
from math import inf
from typing import Protocol, assert_never, cast

from sonolus.script import runtime
from sonolus.script.archetype import EntityRef, get_archetype_by_name
from sonolus.script.interval import remap
from sonolus.script.record import Record
from sonolus.script.timing import TimescaleEase, beat_to_time

from sekai.lib.options import Options

MIN_START_TIME = -2.0


TIMESCALE_CHANGE_NAME = "TimeScaleChange"
TIMESCALE_GROUP_NAME = "TimeScaleGroup"


class TimescaleChangeLike(Protocol):
    beat: float
    timescale: float
    timescale_skip: float
    timescale_ease: TimescaleEase
    next_ref: EntityRef

    @classmethod
    def at(cls, index: int) -> TimescaleChangeLike: ...

    @property
    def index(self) -> int: ...


class TimescaleGroupLike(Protocol):
    first_ref: EntityRef
    time_to_scaled_time: CachedTimeToScaledTime
    scaled_time_to_first_time: CachedScaledTimeToFirstTime
    current_scaled_time: float

    @classmethod
    def at(cls, index: int) -> TimescaleGroupLike: ...


class CachedTimeToScaledTime(Record):
    last_timescale: float
    last_time: float
    last_scaled_time: float
    first_change_index: int
    next_change_index: int

    def init(self, next_index: int):
        self.last_timescale = 1.0
        self.last_time = MIN_START_TIME
        self.last_scaled_time = MIN_START_TIME
        self.first_change_index = next_index
        self.next_change_index = next_index

    def get(self, time: float) -> float:
        if time <= MIN_START_TIME or Options.disable_timescale:
            return time
        if time < self.last_time:
            self.init(self.first_change_index)
        for change in iter_timescale_changes(self.next_change_index):
            next_timescale = change.timescale
            next_time = beat_to_time(change.beat)
            match change.timescale_ease:
                case TimescaleEase.NONE:
                    next_scaled_time = self.last_scaled_time + (next_time - self.last_time) * self.last_timescale
                case TimescaleEase.LINEAR:
                    next_scaled_time = (
                        self.last_scaled_time
                        + (next_time - self.last_time) * (next_timescale + self.last_timescale) / 2
                    )
                case _:
                    assert_never(change.timescale_ease)
            skip_scaled_time = beat_to_time(change.beat + change.timescale_skip) - beat_to_time(change.beat)
            if time <= next_time:
                if abs(next_time - self.last_time) < 1e-6:
                    return self.last_scaled_time
                match change.timescale_ease:
                    case TimescaleEase.NONE:
                        return remap(self.last_time, next_time, self.last_scaled_time, next_scaled_time, time)
                    case TimescaleEase.LINEAR:
                        avg_timescale = (
                            self.last_timescale
                            + remap(self.last_time, next_time, self.last_timescale, next_timescale, time)
                        ) / 2
                        return self.last_scaled_time + (time - self.last_time) * avg_timescale
                    case _:
                        assert_never(change.timescale_ease)
            self.last_timescale = next_timescale
            self.last_time = next_time
            self.last_scaled_time = next_scaled_time + skip_scaled_time
            self.next_change_index = change.next_ref.index
        return self.last_scaled_time + (time - self.last_time) * self.last_timescale


class CachedScaledTimeToFirstTime(Record):
    last_timescale: float
    last_time: float
    last_scaled_time: float
    first_change_index: int
    next_change_index: int

    def init(self, next_index: int):
        self.last_timescale = 1.0
        self.last_time = MIN_START_TIME
        self.last_scaled_time = MIN_START_TIME
        self.first_change_index = next_index
        self.next_change_index = next_index

    def get(self, scaled_time: float) -> float:
        if Options.disable_timescale:
            return scaled_time
        if scaled_time < self.last_scaled_time or self.last_scaled_time < MIN_START_TIME:
            self.init(self.first_change_index)
        for change in iter_timescale_changes(self.next_change_index):
            next_timescale = change.timescale
            next_time = beat_to_time(change.beat)
            match change.timescale_ease:
                case TimescaleEase.NONE:
                    next_scaled_time = self.last_scaled_time + (next_time - self.last_time) * self.last_timescale
                    lo_scaled_time = min(self.last_scaled_time, next_scaled_time)
                    hi_scaled_time = max(self.last_scaled_time, next_scaled_time)
                    if lo_scaled_time <= scaled_time <= hi_scaled_time:
                        if (next_scaled_time - self.last_scaled_time) < 1e-6:
                            return self.last_time
                        return remap(self.last_scaled_time, next_scaled_time, self.last_time, next_time, scaled_time)
                case TimescaleEase.LINEAR:
                    next_scaled_time = (
                        self.last_scaled_time
                        + (next_time - self.last_time) * (next_timescale + self.last_timescale) / 2
                    )
                    if abs(next_time - self.last_time) < 1e-6:
                        lo_scaled_time = min(self.last_scaled_time, next_scaled_time)
                        hi_scaled_time = max(self.last_scaled_time, next_scaled_time)
                        if lo_scaled_time <= scaled_time <= hi_scaled_time:
                            return self.last_time
                    else:
                        a = (next_timescale - self.last_timescale) / (next_time - self.last_time)
                        b = self.last_timescale
                        c = self.last_scaled_time - scaled_time

                        first_time = inf
                        found_time = False

                        if abs(a) < 1e-6:
                            if abs(b) > 1e-6:
                                dt = -c / b
                                if 0 <= dt <= (next_time - self.last_time):
                                    first_time = min(first_time, self.last_time + dt)
                                    found_time = True
                        else:
                            discriminant = b * b - 2 * a * c
                            if discriminant >= 0:
                                sqrt_discriminant = discriminant**0.5
                                for dt in ((-b + sqrt_discriminant) / a, (-b - sqrt_discriminant) / a):
                                    if 0 <= dt <= (next_time - self.last_time):
                                        first_time = min(first_time, self.last_time + dt)
                                        found_time = True

                        if found_time:
                            return first_time
                case _:
                    assert_never(change.timescale_ease)
            skip_scaled_time = beat_to_time(change.beat + change.timescale_skip) - beat_to_time(change.beat)
            if (next_scaled_time <= scaled_time <= next_scaled_time + change.timescale_skip) or (
                next_scaled_time + change.timescale_skip <= scaled_time <= next_scaled_time
            ):
                return next_time
            self.last_timescale = next_timescale
            self.last_time = next_time
            self.last_scaled_time = next_scaled_time + skip_scaled_time
            self.next_change_index = change.next_ref.index
        if self.last_timescale == 0:
            return inf
        additional_time = (scaled_time - self.last_scaled_time) / self.last_timescale
        if additional_time < 0:
            return inf
        return self.last_time + additional_time


def timescale_change_archetype() -> type[TimescaleChangeLike]:
    return cast(type[TimescaleChangeLike], get_archetype_by_name(TIMESCALE_CHANGE_NAME))


def timescale_group_archetype() -> type[TimescaleGroupLike]:
    return cast(type[TimescaleGroupLike], get_archetype_by_name(TIMESCALE_GROUP_NAME))


def iter_timescale_changes(index: int) -> Iterator[TimescaleChangeLike]:
    while True:
        if index <= 0:
            return
        change = timescale_change_archetype().at(index)
        yield change
        index = change.next_ref.index


def group_scaled_time(group: int | EntityRef):
    if isinstance(group, EntityRef):
        group = group.index
    if group == 0 or Options.disable_timescale:
        return runtime.time()
    return timescale_group_archetype().at(group).current_scaled_time


def group_time_to_scaled_time(
    group: int | EntityRef,
    time: float,
) -> float:
    if isinstance(group, EntityRef):
        group = group.index
    return timescale_group_archetype().at(group).time_to_scaled_time.get(time)


def group_scaled_time_to_first_time(
    group: int | EntityRef,
    scaled_time: float,
) -> float:
    if isinstance(group, EntityRef):
        group = group.index
    return timescale_group_archetype().at(group).scaled_time_to_first_time.get(scaled_time)
