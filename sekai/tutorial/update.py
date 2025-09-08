from sonolus.script.globals import level_memory

from sekai.tutorial.framework import current_phase_time, reset_phase, update_end, update_start
from sekai.tutorial.phases import PHASES


@level_memory
class TutorialState:
    current_phase: int


def inc_phase():
    TutorialState.current_phase += 1
    TutorialState.current_phase %= len(PHASES)
    reset_phase()


def dec_phase():
    TutorialState.current_phase -= 1
    TutorialState.current_phase %= len(PHASES)
    reset_phase()


def run_current_phase():
    for i, phase in enumerate(PHASES):
        if i == TutorialState.current_phase:
            is_done = phase(current_phase_time())
            if is_done:
                inc_phase()
            return


def update():
    update_start()
    run_current_phase()
    update_end()
