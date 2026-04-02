from typing import Any, Self

from sonolus.script.archetype import EntityRef, entity_data, StandardImport


class BaseEvent:
    beat: StandardImport.BEAT
    left: EntityRef[Any] = entity_data()
    right: EntityRef[Any] = entity_data()
    next_ref: EntityRef[Any]

    def build_tree(self) -> EntityRef[Self]:
        pass
