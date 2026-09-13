import io
import unittest
from contextlib import redirect_stdout

import ir
from bytecode import bytecode
from compiler import compile_source
from interpreter import Interpreter
from typecheck import TypeCheckError


class UnifiedStackCallingConventionTests(unittest.TestCase):
    def run_source(self, source):
        with redirect_stdout(io.StringIO()):
            return Interpreter().run(compile_source(source))

    def test_legacy_transfer_opcode_is_retired(self):
        assigned = {
            instruction.OPCODE
            for instruction in vars(ir).values()
            if isinstance(instruction, type)
            and issubclass(instruction, ir.Instruction)
            and hasattr(instruction, "OPCODE")
        }
        self.assertNotIn(5, assigned)

    def test_alloc_replaces_local_and_global_alloc(self):
        self.assertEqual(ir.Alloc.OPCODE, 42)
        self.assertFalse(hasattr(ir, "LocalAlloc"))
        self.assertFalse(hasattr(ir, "GlobalAlloc"))
        assigned = {
            instruction.OPCODE
            for instruction in vars(ir).values()
            if isinstance(instruction, type)
            and issubclass(instruction, ir.Instruction)
            and hasattr(instruction, "OPCODE")
        }
        self.assertNotIn(43, assigned)

    def test_locals_and_arguments_use_signed_variable_offsets(self):
        operations = list(compile_source("""
identity(42)
def identity(argument: int) -> int:
    local: int = argument
    return local
"""))
        offsets = [
            operation.offset
            for operation in operations
            if isinstance(operation, (ir.StackPushVariable, ir.StackPopVariable))
        ]
        self.assertIn(-2, offsets)
        self.assertIn(1, offsets)
        self.assertEqual(ir.StackPushVariable.OPCODE, 0)
        self.assertEqual(ir.StackPopVariable.OPCODE, 1)
        self.assertEqual(ir.StackPushGlobal.OPCODE, 2)
        self.assertEqual(ir.StackPopGlobal.OPCODE, 3)

    def test_call_reserves_result_slot_below_arguments(self):
        operations = list(compile_source("""
add(20, 22)
def add(a: int, b: int) -> int:
    return a + b
"""))
        self.assertTrue(any(
            isinstance(operations[index], ir.StackPushLiteral)
            and operations[index].value == 0
            and isinstance(operations[index + 1], ir.Roll)
            and operations[index + 1].depth == 2
            and isinstance(operations[index + 2], ir.Roll)
            and operations[index + 2].depth == 2
            and isinstance(operations[index + 3], ir.Call)
            for index in range(len(operations) - 3)
        ))

    def test_return_stores_result_beyond_arguments(self):
        operations = list(compile_source("""
add(20, 22)
def add(a: int, b: int) -> int:
    return a + b
"""))
        self.assertTrue(any(
            isinstance(operations[index], ir.StackPopVariable)
            and operations[index].offset == -4
            and isinstance(operations[index + 1], ir.Return)
            and operations[index + 1].arg_count == 2
            for index in range(len(operations) - 1)
        ))

    def test_globals_are_bottom_based_unified_stack_variables(self):
        source = """
value: int = 40
main()
def main() -> int:
    value = value + 2
    return value
"""
        operations = list(compile_source(source))
        self.assertTrue(any(
            isinstance(operation, ir.Alloc) and operation.variable_count == 1
            for operation in operations
        ))
        self.assertTrue(any(
            isinstance(operation, (ir.StackPushGlobal, ir.StackPopGlobal))
            and operation.index == 0
            for operation in operations
        ))
        self.assertEqual(self.run_source(source), 42)

    def test_global_and_load_address_the_same_memory_word(self):
        vm = Interpreter(memory_size=16)
        with redirect_stdout(io.StringIO()):
            result = vm.run([
                ir.Alloc(1),
                ir.StackPushLiteral(15),
                ir.StackPushLiteral(42),
                ir.Store(),
                ir.StackPushGlobal(0),
            ])
        self.assertEqual(result, 42)
        self.assertEqual(vm.memory[15], 42)

    def test_stack_grows_down_from_top_of_vm_memory(self):
        vm = Interpreter(memory_size=16)
        with redirect_stdout(io.StringIO()):
            vm.run([ir.StackPushLiteral(10), ir.StackPushLiteral(20)])
        self.assertEqual(vm.sp, 14)
        self.assertEqual(vm.memory[15], 10)
        self.assertEqual(vm.memory[14], 20)

    def test_vm_detects_allocated_memory_stack_collision(self):
        vm = Interpreter(memory_size=3)
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(MemoryError, "collided"):
                vm.run([
                    ir.StackPushLiteral(2),
                    ir.Malloc(),
                    ir.StackPushLiteral(99),
                ])

    def test_global_stack_indexes_encode_as_the_single_immediate(self):
        self.assertEqual(
            bytecode([ir.StackPushGlobal(3), ir.StackPopGlobal(4)]),
            [(ir.StackPushGlobal.OPCODE, 3), (ir.StackPopGlobal.OPCODE, 4)],
        )

    def test_main_without_return_implicitly_returns_zero_above_globals(self):
        source = """
GLOBAL = 99
main()
def main():
    print(GLOBAL + 1)
"""
        operations = list(compile_source(source))
        self.assertTrue(any(
            isinstance(operations[index], ir.StackPushLiteral)
            and operations[index].value == 0
            and isinstance(operations[index + 1], ir.StackPopVariable)
            and isinstance(operations[index + 2], ir.Return)
            for index in range(len(operations) - 2)
        ))
        self.assertEqual(self.run_source(source), 0)

    def test_module_without_main_returns_zero(self):
        source = """
GLOBAL = 99
print(GLOBAL + 1)
"""
        operations = list(compile_source(source))
        self.assertIsInstance(operations[-1], ir.StackPushLiteral)
        self.assertEqual(operations[-1].value, 0)
        self.assertEqual(self.run_source(source), 0)

    def test_call_to_undefined_main_is_an_unknown_function_error(self):
        with self.assertRaisesRegex(TypeCheckError, "Unknown function 'main'"):
            compile_source("main()")

    def test_main_must_return_int(self):
        for source in (
            'main()\ndef main() -> float:\n    return 1.5',
            'main()\ndef main() -> None:\n    return',
            'main()\ndef main():\n    return "wrong"',
            'main()\ndef main():\n    return True',
            'main()\ndef main():\n    return',
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(TypeCheckError, "main.*return int"):
                    compile_source(source)

    def test_nested_calls_leave_results_ready_for_arithmetic(self):
        self.assertEqual(self.run_source("""
main()
def left() -> int:
    return 20
def right() -> int:
    return 22
def main() -> int:
    return left() + right()
"""), 42)

    def test_multiword_return_slots_preserve_flattened_order(self):
        self.assertEqual(self.run_source("""
main()
def pair() -> tuple[int, int]:
    return (20, 22)
def main() -> int:
    a, b = pair()
    return a + b
"""), 42)

    def test_multiword_argument_uses_the_same_unified_stack(self):
        self.assertEqual(self.run_source("""
main()
def string_length(value: str) -> int:
    return len(value)
def main() -> int:
    return string_length("abc")
"""), 3)


if __name__ == "__main__":
    unittest.main()
