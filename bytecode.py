from collections import defaultdict
from dataclasses import dataclass

import hr
import ir
from instruction_set import CompilationResult, InstructionSet


@dataclass(frozen=True)
class BytecodeEncodingDiagnostic:
    span: hr.SourceSpan | None
    construct: str
    problem: str
    instructions: frozenset[str]


class BytecodeEncodingError(Exception):
    def __init__(self, diagnostics):
        self.diagnostics = tuple(diagnostics)
        super().__init__(self.render())

    def render(self):
        rich = any(item.span is not None for item in self.diagnostics)
        if not rich and len(self.diagnostics) == 1:
            item = self.diagnostics[0]
            names = ", ".join(sorted(item.instructions))
            if item.problem == "unsupported":
                return f"Target instruction set does not support {names}"
            if len(item.instructions) == 1:
                return f"Instruction {names} has no opcode mapping"
            return f"Instructions {names} have no opcode mappings"

        lines = ["Bytecode cannot be generated for the target VM."]
        all_missing = set()
        for diagnostic in self.diagnostics:
            names = sorted(diagnostic.instructions)
            all_missing.update(names)
            span = diagnostic.span
            location = (
                "<unknown location>"
                if span is None
                else f"{span.filename or '<source>'}:{span.line}:{span.column + 1}"
            )
            description = (
                "uses instructions unsupported by the target"
                if diagnostic.problem == "unsupported"
                else "requires instructions with no bytecode opcode mapping"
            )
            lines.extend(["", f"{location}: {diagnostic.construct} {description}"])
            if span is not None and span.source_line is not None:
                width = max(
                    1,
                    span.end_column - span.column if span.end_line == span.line else 1,
                )
                lines.append(f"    {span.source_line}")
                lines.append(f"    {' ' * span.column}{'^' * width}")
            lines.append(f"    {', '.join(names)}")

        lines.extend([
            "",
            "Target bytecode mappings are missing: " + ", ".join(sorted(all_missing)),
            "Add explicit .opcode(InstructionClass, value) mappings to the target instruction set.",
        ])
        return "\n".join(lines)


def _legacy_opcode(instruction, builtins):
    opcode = getattr(instruction, "OPCODE", None)
    if opcode is not None:
        return opcode
    if isinstance(instruction, (ir.BuiltInInstruction, ir.BuiltInFunction)):
        signature = builtins.get(instruction.name)
        return None if signature is None else signature.opcode
    return None


def bytecode(
    instructions: list[ir.Instruction],
    builtin_instructions=None,
    instruction_set: InstructionSet | None = None,
):
    """Encode IR only after aggregating all target and opcode problems."""
    builtin_instructions = builtin_instructions or {}
    operations = list(instructions)
    origins = (
        instructions.origins
        if isinstance(instructions, CompilationResult)
        else [None] * len(operations)
    )

    grouped = defaultdict(set)
    resolved_opcodes = []
    for instruction, origin in zip(operations, origins):
        unsupported = instruction_set is not None and not instruction_set.supports(instruction)
        opcode = (
            instruction_set.opcode_for(instruction)
            if instruction_set is not None and not unsupported
            else _legacy_opcode(instruction, builtin_instructions)
        )
        resolved_opcodes.append(opcode)

        if unsupported:
            problem = "unsupported"
        elif opcode is None:
            problem = "missing opcode"
        else:
            continue

        name = (
            f"{type(instruction).__name__}({instruction.name})"
            if isinstance(instruction, (ir.BuiltInInstruction, ir.BuiltInFunction))
            else type(instruction).__name__
        )
        span = None if origin is None else origin.span
        construct = "compiler-generated instruction" if origin is None else origin.construct
        grouped[(span, construct, problem)].add(name)

    if grouped:
        raise BytecodeEncodingError(
            BytecodeEncodingDiagnostic(span, construct, problem, frozenset(names))
            for (span, construct, problem), names in grouped.items()
        )

    binary = []
    for instruction, opcode in zip(operations, resolved_opcodes):
        if hasattr(instruction, "value"):
            immediate = instruction.value
        elif hasattr(instruction, "offset"):
            immediate = instruction.offset
        elif hasattr(instruction, "location"):
            immediate = instruction.location
        elif hasattr(instruction, "arg_count"):
            immediate = instruction.arg_count
        elif hasattr(instruction, "variable_count"):
            immediate = instruction.variable_count
        elif hasattr(instruction, "count"):
            immediate = instruction.count
        elif hasattr(instruction, "depth"):
            immediate = instruction.depth
        else:
            immediate = 0
        binary.append((opcode, immediate))

    return binary
