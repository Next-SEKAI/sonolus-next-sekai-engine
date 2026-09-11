from math import inf
from random import uniform


def jitter_spawn_time(start_time: float, end_time: float = inf) -> float:
    if start_time >= end_time:
        return start_time
    return start_time - uniform(0, 1)
