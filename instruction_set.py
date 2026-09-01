"""Target VM instruction-set descriptions and compilation diagnostics.

Instruction groups in this module are convenience sets only.  They do not
describe language features and deliberately carry no dependency rules.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

import hr
import ir
from typesystem import BuiltinSignature


@dataclass(frozen=True)
class InstructionOrigin:
    span: hr.SourceSpan | None
    construct: str


@dataclass
class CompilationResult(Sequence[ir.Instruction]):
    instructions: list[ir.Instruction]
    origins: list[InstructionOrigin | None]

    def __post_init__(self):
        if len(self.instructions) != len(self.origins):
            raise ValueError("Instruction and origin counts must match")

    def __getitem__(self, index):
        return self.instructions[index]

    def __len__(self):
        return len(self.instructions)

    def __iter__(self) -> Iterator[ir.Instruction]:
        return iter(self.instructions)


class BuiltinKind(Enum):
    INSTRUCTION = "instruction"
    FUNCTION = "function"


@dataclass(frozen=True)
class BuiltinDefinition:
    name: str
    kind: BuiltinKind
    signature: BuiltinSignature


class InstructionGroup:
    STACK_LITERALS = frozenset({ir.OpStackPushLiteral})
    LOCAL_STORAGE = frozenset({ir.OpStackPushLocal, ir.OpStackPopLocal, ir.LocalAlloc})
    GLOBAL_STORAGE = frozenset({ir.OpStackPushGlobal, ir.OpStackPopGlobal, ir.GlobalAlloc})
    FUNCTIONS = frozenset({
        ir.Call, ir.Return, ir.LocalAlloc, ir.OpStackPushArg,
        ir.OpStackPopArg, ir.OpStackPopToCallStack,
    })
    BRANCHING = frozenset({ir.Jump, ir.JumpIfTrue, ir.JumpIfFalse})
    COMPARISONS = frozenset({
        ir.Equal, ir.NotEqual, ir.LessThan, ir.GreaterThan,
        ir.LessThanEqualTo, ir.GreaterThanEqualTo,
    })
    ARITHMETIC = frozenset({
        ir.IAdd, ir.ISub, ir.IMultiply, ir.IMod, ir.IUnaryNegative, ir.IUnaryPositive,
        ir.FAdd, ir.FSub, ir.FMultiply, ir.FUnaryNegative, ir.FUnaryPositive,
    })
    BITWISE = frozenset({
        ir.And, ir.Or, ir.Xor, ir.ShiftLeft, ir.ShiftRight, ir.OnesComplement,
    })
    LOGICAL = frozenset({ir.LogicalAnd, ir.LogicalOr, ir.LogicalNot})
    CONVERSIONS = frozenset({ir.IntToFloat, ir.ConvertFloatToInt})
    HEAP = frozenset({ir.Malloc, ir.Free, ir.Load, ir.Store})
    IO = frozenset({ir.Input})
    STACK_MANIPULATION = frozenset({ir.Dupe, ir.Drop, ir.Roll})
    PRINTING = frozenset({
        ir.PrintInt, ir.PrintFloat, ir.PrintString, ir.PrintBool, ir.PrintChar,
    })
    ASSERTIONS = frozenset({ir.Assert})
    CONDITIONAL_VALUE = frozenset({ir.Ternary})

    CORE = STACK_LITERALS


def all_instruction_types() -> frozenset[type[ir.Instruction]]:
    return frozenset(
        value for value in vars(ir).values()
        if isinstance(value, type)
        and issubclass(value, ir.Instruction)
        and value not in {ir.Instruction, ir.BuiltInInstruction, ir.BuiltInFunction}
    )


@dataclass(frozen=True)
class InstructionSet:
    instructions: frozenset[type[ir.Instruction]]
    builtin_instructions: Mapping[str, BuiltinSignature] = field(default_factory=dict)
    builtin_functions: Mapping[str, BuiltinSignature] = field(default_factory=dict)
    opcodes: Mapping[type[ir.Instruction], int] = field(default_factory=dict)
    minimum_opcode: int = 0
    maximum_opcode: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "builtin_instructions", MappingProxyType(dict(self.builtin_instructions)))
        object.__setattr__(self, "builtin_functions", MappingProxyType(dict(self.builtin_functions)))
        object.__setattr__(self, "opcodes", MappingProxyType(dict(self.opcodes)))

    @classmethod
    def unrestricted(cls) -> "InstructionSet":
        """Compatibility target accepting every current IR operation."""
        return cls(all_instruction_types())

    def supports(self, instruction: ir.Instruction) -> bool:
        if isinstance(instruction, ir.BuiltInInstruction):
            return instruction.name in self.builtin_instructions
        if isinstance(instruction, ir.BuiltInFunction):
            return instruction.name in self.builtin_functions
        return type(instruction) in self.instructions

    def opcode_for(self, instruction: ir.Instruction) -> int | None:
        if isinstance(instruction, ir.BuiltInInstruction):
            definition = self.builtin_instructions.get(instruction.name)
            return None if definition is None else definition.opcode
        if isinstance(instruction, ir.BuiltInFunction):
            definition = self.builtin_functions.get(instruction.name)
            return None if definition is None else definition.opcode
        return self.opcodes.get(type(instruction), getattr(type(instruction), "OPCODE", None))

    @property
    def builtins(self) -> dict[str, BuiltinSignature]:
        return {**self.builtin_instructions, **self.builtin_functions}


class InvalidInstructionSetError(ValueError):
    pass


class InstructionSetBuilder:
    def __init__(self):
        self._instructions: set[type[ir.Instruction]] = set()
        self._builtin_instructions: dict[str, BuiltinSignature] = {}
        self._builtin_functions: dict[str, BuiltinSignature] = {}
        self._opcodes: dict[type[ir.Instruction], int] = {}
        self._minimum_opcode = 0
        self._maximum_opcode = None

    @staticmethod
    def _check_types(instructions):
        for instruction in instructions:
            if not isinstance(instruction, type) or not issubclass(instruction, ir.Instruction):
                raise TypeError(f"Expected an IR instruction class, found {instruction!r}")

    def include(self, *instructions):
        self._check_types(instructions)
        self._instructions.update(instructions)
        return self

    def exclude(self, *instructions):
        self._check_types(instructions)
        self._instructions.difference_update(instructions)
        return self

    def include_group(self, group):
        return self.include(*group)

    def exclude_group(self, group):
        return self.exclude(*group)

    def include_core(self):
        return self.include_group(InstructionGroup.CORE)

    def include_all(self):
        return self.include(*all_instruction_types())

    def _include_builtin(self, name, signature, kind):
        if not isinstance(signature, BuiltinSignature):
            raise TypeError("A built-in must have a BuiltinSignature")
        other = self._builtin_functions if kind is BuiltinKind.INSTRUCTION else self._builtin_instructions
        if name in other:
            raise InvalidInstructionSetError(f"Built-in '{name}' has two different calling conventions")
        target = self._builtin_instructions if kind is BuiltinKind.INSTRUCTION else self._builtin_functions
        target[name] = signature
        return self

    def include_builtin_instruction(self, name, signature):
        return self._include_builtin(name, signature, BuiltinKind.INSTRUCTION)

    def include_builtin_function(self, name, signature):
        return self._include_builtin(name, signature, BuiltinKind.FUNCTION)

    def include_builtin(self, definition: BuiltinDefinition):
        return self._include_builtin(definition.name, definition.signature, definition.kind)

    def opcode(self, instruction, value):
        self._check_types((instruction,))
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise InvalidInstructionSetError("Opcodes must be non-negative integers")
        self._opcodes[instruction] = value
        return self

    def opcode_range(self, minimum: int, maximum: int):
        if (
            not isinstance(minimum, int) or isinstance(minimum, bool)
            or not isinstance(maximum, int) or isinstance(maximum, bool)
            or minimum < 0 or maximum < minimum
        ):
            raise InvalidInstructionSetError("Invalid opcode range")
        self._minimum_opcode = minimum
        self._maximum_opcode = maximum
        return self

    def build(self):
        used: dict[int, str] = {}
        entries = []
        for instruction in self._instructions:
            opcode = self._opcodes.get(instruction, getattr(instruction, "OPCODE", None))
            if opcode is not None:
                entries.append((opcode, instruction.__name__))
        entries.extend((sig.opcode, f"built-in '{name}'") for name, sig in self._builtin_instructions.items())
        entries.extend((sig.opcode, f"built-in '{name}'") for name, sig in self._builtin_functions.items())
        for opcode, name in entries:
            if not isinstance(opcode, int) or isinstance(opcode, bool) or opcode < 0:
                raise InvalidInstructionSetError(f"Invalid opcode {opcode!r} for {name}")
            if opcode in used:
                raise InvalidInstructionSetError(
                    f"Opcode {opcode} is assigned to both {used[opcode]} and {name}"
                )
            if not self._minimum_opcode <= opcode or (
                self._maximum_opcode is not None and opcode > self._maximum_opcode
            ):
                raise InvalidInstructionSetError(
                    f"Opcode {opcode} for {name} is outside the configured range "
                    f"{self._minimum_opcode}..{self._maximum_opcode}"
                )
            used[opcode] = name
        return InstructionSet(
            frozenset(self._instructions), self._builtin_instructions,
            self._builtin_functions, self._opcodes,
            self._minimum_opcode, self._maximum_opcode,
        )


@dataclass(frozen=True)
class UnsupportedInstructionDiagnostic:
    span: hr.SourceSpan | None
    construct: str
    missing_instructions: frozenset[type[ir.Instruction] | str]


class UnsupportedInstructionError(Exception):
    def __init__(self, diagnostics):
        self.diagnostics = tuple(diagnostics)
        super().__init__(self.render())

    def render(self):
        lines = ["Compilation requires instructions unavailable on the target VM."]
        all_missing = set()
        for diagnostic in self.diagnostics:
            missing = sorted(
                item if isinstance(item, str) else item.__name__
                for item in diagnostic.missing_instructions
            )
            all_missing.update(missing)
            span = diagnostic.span
            if span is None:
                location = "<unknown location>"
            else:
                location = f"{span.filename or '<source>'}:{span.line}:{span.column + 1}"
            lines.extend(["", f"{location}: {diagnostic.construct} requires unsupported instructions"])
            if span is not None and span.source_line is not None:
                width = max(1, (span.end_column - span.column) if span.end_line == span.line else 1)
                lines.append(f"    {span.source_line}")
                lines.append(f"    {' ' * span.column}{'^' * width}")
            lines.append(f"    {', '.join(missing)}")
        lines.extend(["", "Target VM is missing: " + ", ".join(sorted(all_missing))])
        return "\n".join(lines)


def validate_instruction_set(result: CompilationResult, target: InstructionSet):
    grouped = defaultdict(set)
    origins = {}
    for instruction, origin in zip(result.instructions, result.origins):
        if target.supports(instruction):
            continue
        if isinstance(instruction, (ir.BuiltInInstruction, ir.BuiltInFunction)):
            missing = f"{type(instruction).__name__}({instruction.name})"
        else:
            missing = type(instruction)
        key = (None, "compiler-generated instruction") if origin is None else (origin.span, origin.construct)
        grouped[key].add(missing)
        origins[key] = origin
    if grouped:
        raise UnsupportedInstructionError(
            UnsupportedInstructionDiagnostic(span, construct, frozenset(missing))
            for (span, construct), missing in grouped.items()
        )
