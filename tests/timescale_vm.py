"""Run optimized Sonolus instructions with controlled numeric precision.

The installed interpreter supplies instruction semantics. This adapter limits
execution and rounds arithmetic and storage to the selected precision. ROM uses
binary32, as in packaged engines. Entity fields can use binary32 storage while
arithmetic and temporary values use binary64.

These tests model rounding behavior; they do not measure client precision or
performance.

Preallocate arrays when a probe relies on zero-initialized storage. The
interpreter fills new storage gaps with sentinels and limits indices to 65535.
This adapter does not model memory aliases or callback scheduling.
"""

import math
import struct
from collections import Counter
from dataclasses import dataclass

from sonolus.backend.blocks import PlayBlock
from sonolus.backend.interpret import Interpreter
from sonolus.backend.mode import Mode
from sonolus.backend.node import EngineNode, FunctionNode
from sonolus.backend.ops import Op
from sonolus.backend.optimize import STANDARD_PASSES, OptimizerConfig, optimize_and_finalize
from sonolus.build.compile import callback_to_cfg
from sonolus.script.internal.context import ModeContextState, ProjectContextState, RuntimeChecks


def binary32(value: float) -> float:
    """Round to binary32, including overflow to signed infinity."""
    try:
        return struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


_SUPPORTED = frozenset(
    Op(name)
    for name in (  # noqa: SIM905 - compact allowlist, checked against the installed Op enum
        "Execute Execute0 If Switch SwitchWithDefault SwitchInteger SwitchIntegerWithDefault "
        "While DoWhile And Or JumpLoop Block Break Abs Add Subtract Multiply Divide Power "
        "Negate Not Equal NotEqual Less LessOr Greater GreaterOr Min Max Floor Ceil Trunc "
        "Lerp LerpClamped Unlerp UnlerpClamped Remap RemapClamped Clamp "
        "BeatToBPM BeatToTime "
        "Mod Rem Sign Log Get GetShifted GetPointed Set SetShifted SetPointed Copy "
        "SetAdd SetSubtract SetMultiply SetDivide SetMod "
        "SetAddShifted SetSubtractShifted SetMultiplyShifted SetDivideShifted "
        "IncrementPre IncrementPost DecrementPre DecrementPost"
    ).split()
)

_ENTITY_BLOCKS = frozenset(
    {
        PlayBlock.EntityData,
        PlayBlock.EntityDataArray,
        PlayBlock.EntityMemory,
        PlayBlock.EntitySharedMemory,
        PlayBlock.EntitySharedMemoryArray,
    }
)


class NumericVM(Interpreter):
    """Execute the numeric subset through the installed instruction interpreter."""

    def __init__(
        self,
        *,
        precision: str = "binary64",
        entity_storage_precision: str | None = None,
        instruction_limit: int = 1_000_000,
    ):
        super().__init__()
        if precision not in {"binary32", "binary64"}:
            raise ValueError(f"Unknown precision: {precision}")
        if entity_storage_precision not in {None, "binary32", "binary64"}:
            raise ValueError(f"Unknown entity storage precision: {entity_storage_precision}")
        self.round_value = binary32 if precision == "binary32" else float
        storage = entity_storage_precision or precision
        self.round_entity_store = binary32 if storage == "binary32" else float
        self.instruction_limit = instruction_limit
        self.counts = Counter()
        self.steps = 0
        self.evaluations = 0
        self.read_blocks = set()
        self.read_locations = Counter()
        self.write_blocks = set()

    def run(self, node: EngineNode) -> float:
        self.evaluations += 1
        # Count literals too, so even While(1, 0) is bounded.
        if self.evaluations > self.instruction_limit:
            raise RuntimeError("Numeric probe instruction budget exceeded")
        if isinstance(node, FunctionNode):
            if node.func not in _SUPPORTED:
                raise NotImplementedError(f"Numeric probe does not model {node.func}")
            self.steps += 1
            if self.steps > self.instruction_limit:
                raise RuntimeError("Numeric probe instruction budget exceeded")
            self.counts[node.func] += 1
        return self.round_value(super().run(node))

    def _run(self, node: EngineNode) -> float:
        # Round each interpolation step in the interpreter's evaluation order.
        # This models separate operations without fused multiply-add.
        if isinstance(node, FunctionNode):
            rounding = self.round_value
            if node.func in {Op.Lerp, Op.LerpClamped}:
                left, right, fraction = (self.run(arg) for arg in node.args)
                if node.func == Op.LerpClamped:
                    fraction = max(0.0, min(1.0, fraction))
                return rounding(left + rounding(rounding(right - left) * fraction))
            if node.func in {Op.Unlerp, Op.UnlerpClamped}:
                left, right, value = (self.run(arg) for arg in node.args)
                fraction = rounding(rounding(value - left) / rounding(right - left))
                return max(0.0, min(1.0, fraction)) if node.func == Op.UnlerpClamped else fraction
            if node.func in {Op.Remap, Op.RemapClamped}:
                left, right, out_left, out_right, value = (self.run(arg) for arg in node.args)
                offset = rounding(value - left)
                width = rounding(right - left)
                out_width = rounding(out_right - out_left)
                if node.func == Op.RemapClamped:
                    fraction = max(0.0, min(1.0, rounding(offset / width)))
                    mapped = rounding(out_width * fraction)
                else:
                    mapped = rounding(rounding(out_width * offset) / width)
                return rounding(out_left + mapped)
        return super()._run(node)

    def reduce_args(self, args, operator):
        # Optimization can combine several Add or Multiply operands. Preserve
        # their emitted order and round each intermediate result.
        values = iter(args)
        first = next(values, None)
        if first is None:
            return 0.0
        result = self.run(first)
        for arg in values:
            result = self.round_value(operator(result, self.run(arg)))
        return result

    def get(self, block: float, index: float) -> float:
        block, index = self.ensure_int(block), self.ensure_int(index)
        self.read_blocks.add(block)
        if block in _ENTITY_BLOCKS:
            self.read_locations[block, index] += 1
        if index < 0:
            raise IndexError("Negative numeric probe memory address")
        values = self.blocks.get(block, [])
        return values[index] if index < len(values) else 0.0

    def set(self, block: float, index: float, value: float):
        self.write_blocks.add(self.ensure_int(block))
        return super().set(block, index, self.round_storage(block, value))

    def round_storage(self, block, value):
        return self.round_entity_store(value) if block in _ENTITY_BLOCKS else self.round_value(value)


@dataclass
class CompiledProbe:
    archetype: type
    node: EngineNode
    rom: tuple[float, ...]

    def run(
        self,
        *,
        precision: str = "binary64",
        entity_storage_precision: str | None = None,
        instruction_limit: int = 1_000_000,
        memory=None,
        **inputs,
    ):
        vm = NumericVM(
            precision=precision, entity_storage_precision=entity_storage_precision, instruction_limit=instruction_limit
        )
        if memory:
            vm.blocks.update(
                {int(block): [vm.round_storage(block, value) for value in values] for block, values in memory.items()}
            )
        vm.blocks[int(PlayBlock.EngineRom)] = [binary32(value) for value in self.rom]
        vm.blocks[int(PlayBlock.EntityData)] = [0.0] * 32
        for name, value in inputs.items():
            field = self.archetype._imported_fields_[name]
            vm.set(PlayBlock.EntityData, field.offset, value)
        vm.write_blocks.clear()
        vm.run(self.node)
        outputs = {
            name: tuple(vm.get(PlayBlock.EntityData, field.offset + i) for i in range(field.type._size_()))
            for name, field in self.archetype._data_fields_.items()
        }
        return outputs, vm


def compile_probe(
    archetype: type, *, archetypes=None, runtime_checks: RuntimeChecks = RuntimeChecks.NONE
) -> CompiledProbe:
    """Compile a real preprocess callback with the production optimizer."""
    project = ProjectContextState(runtime_checks=runtime_checks)
    mode = ModeContextState(Mode.PLAY, archetypes if archetypes is not None else [archetype])
    cfg = callback_to_cfg(project, mode, archetype.preprocess, "preprocess", archetype=archetype)
    node = optimize_and_finalize(cfg, STANDARD_PASSES, OptimizerConfig(mode=Mode.PLAY, callback="preprocess"))
    return CompiledProbe(archetype, node, tuple(project.rom.values))
