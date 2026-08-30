import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

import hr
import ir
import interpreter
from bytecode import BytecodeEncodingError, bytecode
from compiler import compile_source
from instruction_set import (
    BuiltinDefinition,
    BuiltinKind,
    CompilationResult,
    InstructionGroup,
    InstructionOrigin,
    InstructionSetBuilder,
    InvalidInstructionSetError,
    UnsupportedInstructionError,
)
from typesystem import BuiltinSignature, INT


class InstructionSetBuilderTests(unittest.TestCase):
    def test_groups_are_convenient_and_individual_exclusions_win(self):
        target = (
            InstructionSetBuilder()
            .include_group(InstructionGroup.BITWISE)
            .exclude(ir.Xor)
            .build()
        )
        self.assertIn(ir.And, target.instructions)
        self.assertNotIn(ir.Xor, target.instructions)

    def test_input_intrinsic_allocates_then_uses_native_instruction(self):
        target = interpreter.Interpreter.INSTRUCTION_SET
        self.assertNotIn("input", target.builtin_instructions)
        self.assertNotIn("input", target.builtin_functions)

        result = compile_source(
            "value: str = input(3)\nprint(value)\n",
            instruction_set=target,
        )
        self.assertTrue(any(isinstance(item, ir.Malloc) for item in result))
        self.assertTrue(any(isinstance(item, ir.Input) for item in result))
        self.assertEqual(sum(isinstance(item, ir.Roll) for item in result), 1)
        self.assertFalse(any(isinstance(item, ir.BuiltInFunction) for item in result))
        self.assertIn((1005, 0), bytecode(result, instruction_set=target))
        output = StringIO()
        with patch("builtins.input", return_value="hello"), redirect_stdout(output):
            interpreter.Interpreter().run(result)
        self.assertEqual(output.getvalue(), "hel")

    def test_complete_set_can_be_built(self):
        target = InstructionSetBuilder().include_all().build()
        self.assertIn(ir.Malloc, target.instructions)
        self.assertIn(ir.Call, target.instructions)

    def test_builtin_definition_unifies_signature_kind_and_opcode(self):
        signature = BuiltinSignature((INT,), INT, 1010)
        target = InstructionSetBuilder().include_builtin(
            BuiltinDefinition("random", BuiltinKind.FUNCTION, signature)
        ).build()
        self.assertEqual(target.builtin_functions["random"], signature)
        self.assertEqual(target.builtins["random"].opcode, 1010)

    def test_opcode_collisions_are_rejected(self):
        with self.assertRaisesRegex(InvalidInstructionSetError, "assigned to both"):
            (
                InstructionSetBuilder()
                .include(ir.IAdd, ir.ISub)
                .opcode(ir.IAdd, 700)
                .opcode(ir.ISub, 700)
                .build()
            )

    def test_non_instruction_is_rejected(self):
        with self.assertRaises(TypeError):
            InstructionSetBuilder().include(str)

    def test_packing_opcode_range_is_enforced(self):
        with self.assertRaisesRegex(InvalidInstructionSetError, "outside the configured range"):
            (
                InstructionSetBuilder()
                .include(ir.PrintInt)
                .opcode_range(0, 127)
                .build()
            )


class ProvenanceAndValidationTests(unittest.TestCase):
    def test_compile_result_is_a_sequence_and_origins_align(self):
        result = compile_source("value = 1\nvalue\n")
        self.assertEqual(len(result), len(result.origins))
        self.assertTrue(all(isinstance(item, ir.Instruction) for item in result))
        self.assertTrue(any(origin is not None for origin in result.origins))

    def test_missing_heap_instructions_show_original_string_literal(self):
        source = 'message = "Hello"\nmessage\n'
        target = (
            InstructionSetBuilder()
            .include_all()
            .exclude(ir.Malloc, ir.Store)
            .build()
        )
        with self.assertRaises(UnsupportedInstructionError) as raised:
            compile_source(source, filename="example.gvm", instruction_set=target)
        message = str(raised.exception)
        self.assertIn("example.gvm:1:11", message)
        self.assertIn('message = "Hello"', message)
        self.assertIn("string literal", message)
        self.assertIn("Malloc", message)
        self.assertIn("Store", message)
        self.assertIn("^^^^^^^", message)

    def test_repeated_store_operations_are_deduplicated(self):
        target = InstructionSetBuilder().include_all().exclude(ir.Store).build()
        with self.assertRaises(UnsupportedInstructionError) as raised:
            compile_source('message = "abc"\nmessage\n', instruction_set=target)
        diagnostic = next(
            item for item in raised.exception.diagnostics
            if item.construct == "string literal"
        )
        self.assertEqual(diagnostic.missing_instructions, frozenset({ir.Store}))

    def test_caret_uses_character_columns_after_unicode_text(self):
        source = 'prefix = "é"; message = "Hello"\nprefix\nmessage\n'
        target = InstructionSetBuilder().include_all().exclude(ir.Malloc).build()
        with self.assertRaises(UnsupportedInstructionError) as raised:
            compile_source(source, instruction_set=target)
        hello = next(
            item for item in raised.exception.diagnostics
            if item.span is not None and item.span.column > 10
        )
        self.assertEqual(hello.span.column, source.splitlines()[0].index('"Hello"'))

    def test_missing_call_points_to_source_call(self):
        source = """\
def identity(value: int) -> int:
    return value

result = identity(4)
result
"""
        target = InstructionSetBuilder().include_all().exclude(ir.Call).build()
        with self.assertRaises(UnsupportedInstructionError) as raised:
            compile_source(source, filename="calls.gvm", instruction_set=target)
        self.assertIn("calls.gvm:4:10", str(raised.exception))
        self.assertIn("function call", str(raised.exception))

    def test_named_builtin_must_be_in_target(self):
        signature = BuiltinSignature((INT,), INT, 1010)
        permissive = InstructionSetBuilder().include_all().build()
        with self.assertRaises(UnsupportedInstructionError) as raised:
            compile_source(
                "result = random(4)\nresult\n",
                instruction_set=permissive,
                extra_functions={"random": signature},
            )
        self.assertIn("BuiltInFunction(random)", str(raised.exception))

    def test_target_registered_builtin_is_used_for_typechecking_and_validation(self):
        signature = BuiltinSignature((INT,), INT, 1010)
        target = (
            InstructionSetBuilder()
            .include_all()
            .include_builtin_function("random", signature)
            .build()
        )
        result = compile_source(
            "result = random(4)\nresult\n",
            instruction_set=target,
        )
        self.assertTrue(any(isinstance(item, ir.BuiltInFunction) for item in result))

    def test_duplicate_builtin_configuration_cannot_disagree_with_target(self):
        target = (
            InstructionSetBuilder()
            .include_all()
            .include_builtin_function("random", BuiltinSignature((INT,), INT, 1010))
            .build()
        )
        with self.assertRaisesRegex(ValueError, "disagrees"):
            compile_source(
                "result = random(4)\nresult\n",
                instruction_set=target,
                extra_functions={"random": BuiltinSignature((INT,), INT, 1011)},
            )

    def test_interpreter_rejects_unsupported_program_before_execution(self):
        unsupported = CompilationResult(
            [ir.OpStackPushLiteral(1), ir.Ternary()],
            [None, None],
        )
        with self.assertRaises(UnsupportedInstructionError):
            interpreter.Interpreter().run(unsupported)


class BytecodeValidationTests(unittest.TestCase):
    def test_heap_and_dupe_instructions_use_stable_opcodes(self):
        self.assertEqual(
            bytecode([ir.Load(), ir.Store(), ir.Input(), ir.Malloc(), ir.Free(), ir.Dupe()]),
            [(1003, 0), (1004, 0), (1005, 0), (1006, 0), (1007, 0), (200, 0)],
        )

    def test_explicit_target_opcode_overrides_standard_instruction_opcode(self):
        target = (
            InstructionSetBuilder()
            .include(ir.Malloc)
            .opcode(ir.Malloc, 170)
            .build()
        )
        self.assertEqual(bytecode([ir.Malloc()], instruction_set=target), [(170, 0)])

    def test_bytecode_rejects_instruction_not_supported_by_target(self):
        target = InstructionSetBuilder().include(ir.IAdd).build()
        with self.assertRaisesRegex(BytecodeEncodingError, "does not support ISub"):
            bytecode([ir.ISub()], instruction_set=target)

    def test_missing_opcode_error_retains_source_line_and_construct(self):
        source = "condition if true_value else false_value"
        span = hr.SourceSpan("encoding.gvm", 1, 0, 1, len(source), source)
        target = InstructionSetBuilder().include_all().build()
        result = CompilationResult(
            [ir.Ternary()],
            [InstructionOrigin(span, "ternary expression")],
        )
        with self.assertRaises(BytecodeEncodingError) as raised:
            bytecode(result, instruction_set=target)
        message = str(raised.exception)
        self.assertIn("encoding.gvm:1:1", message)
        self.assertIn(source, message)
        self.assertIn("ternary expression", message)
        self.assertIn("Ternary", message)
        self.assertIn("explicit .opcode", message)


if __name__ == "__main__":
    unittest.main()
