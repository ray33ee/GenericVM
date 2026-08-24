import ast
import unittest

import hr
import interpreter
import ir
from bytecode import bytecode
from compiler import compile
from symbols import Symbols
from typecheck import TypeCheckError, check_types
from typesystem import INT, ListType, TupleType, tuple_member_layout, word_count


def compile_source(source: str):
    module = hr.ast_to_hr(ast.parse(source))
    symbols = Symbols(module)
    instructions = compile(module, symbols, {}, {})
    return module, symbols, instructions


def run_source(source: str):
    _, _, instructions = compile_source(source)
    return interpreter.Interpreter().run(instructions)


class TupleLayoutTests(unittest.TestCase):
    def test_nested_layout_is_flattened(self):
        value_type = TupleType((INT, TupleType((INT, INT)), ListType(INT)))
        self.assertEqual(word_count(value_type), 4)
        self.assertEqual(tuple_member_layout(value_type, 0), (0, 1))
        self.assertEqual(tuple_member_layout(value_type, 1), (1, 2))
        self.assertEqual(tuple_member_layout(value_type, 2), (3, 1))

    def test_drop_and_roll_project_stack_words(self):
        instructions = [
            ir.OpStackPushLiteral(1),
            ir.OpStackPushLiteral(2),
            ir.OpStackPushLiteral(3),
            ir.Drop(1),
            ir.Roll(1),
            ir.Drop(1),
        ]
        self.assertEqual(interpreter.Interpreter().run(instructions), 2)

    def test_drop_and_roll_use_single_bytecode_immediates(self):
        self.assertEqual(
            bytecode([ir.Drop(3), ir.Roll(2)], {}),
            [(ir.Drop.OPCODE, 3), (ir.Roll.OPCODE, 2)],
        )

    def test_local_offsets_are_word_offsets(self):
        _, symbols, instructions = compile_source("""
main()

def main() -> int:
    first = 1
    pair = (2, 3)
    last = 4
    return first + pair[1] + last
""")
        function_symbols = symbols.functions["main"][0]
        self.assertEqual(function_symbols["first"].stack_offset, 0)
        self.assertEqual(function_symbols["pair"].stack_offset, 1)
        self.assertEqual(function_symbols["pair"].word_width, 2)
        self.assertEqual(function_symbols["last"].stack_offset, 3)
        allocation = next(item for item in instructions if isinstance(item, ir.LocalAlloc))
        self.assertEqual(allocation.variable_count, 4)

    def test_container_type_selects_addressing_strategy(self):
        _, _, instructions = compile_source("""
main()

def main() -> int:
    values = [1]
    pair = (2, 3)
    return values[0] + pair[1]
""")
        self.assertTrue(any(isinstance(item, ir.Load) for item in instructions))
        self.assertTrue(any(isinstance(item, ir.Roll) for item in instructions))
        self.assertTrue(any(isinstance(item, ir.Drop) for item in instructions))


class TupleRuntimeTests(unittest.TestCase):
    def test_immediate_tuple_projection(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    return (1, 4, 0)[0]
"""), 1)

    def test_nested_immediate_projection(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    return (1, (2, 3), 4)[1][0]
"""), 2)

    def test_whole_tuple_assignment(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    original = (10, 20)
    copied = original
    return copied[1]
"""), 20)

    def test_nested_tuple_variable(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    value = (1, (2, (3, 4)))
    return value[1][1][0]
"""), 3)

    def test_global_tuple_uses_inline_global_slots(self):
        _, symbols, instructions = compile_source("""
pair = (3, 9)
main()

def main() -> int:
    return pair[1]
""")
        allocation = next(item for item in instructions if isinstance(item, ir.GlobalAlloc))
        self.assertEqual(allocation.variable_count, 2)
        self.assertEqual(symbols.top_level["pair"].word_width, 2)
        self.assertEqual(interpreter.Interpreter().run(instructions), 9)

    def test_tuple_argument_and_return(self):
        _, symbols, instructions = compile_source("""
main()

def make_pair(value: int) -> tuple[int, int]:
    return (value, value + 1)

def second(pair: tuple[int, int]) -> int:
    return pair[1]

def main() -> int:
    pair = make_pair(6)
    return second(pair)
""")
        self.assertEqual(symbols.functions["second"][0]["pair"].word_width, 2)
        second_return = next(
            instruction
            for instruction in instructions
            if isinstance(instruction, ir.Return) and instruction.arg_count == 2
        )
        self.assertEqual(second_return.arg_count, 2)
        self.assertEqual(interpreter.Interpreter().run(instructions), 7)

    def test_tuple_argument_between_scalar_arguments(self):
        self.assertEqual(run_source("""
main()

def combine(left: int, pair: tuple[int, int], right: int) -> int:
    return left + pair[0] + pair[1] + right

def main() -> int:
    return combine(1, (2, 3), 4)
"""), 10)

    def test_immediate_projection_of_returned_nested_tuple(self):
        self.assertEqual(run_source("""
main()

def make() -> tuple[int, tuple[int, int]]:
    return (1, (7, 8))

def main() -> int:
    return make()[1][0]
"""), 7)

    def test_conditional_tuple_expression(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    pair = (1, 2) if False else (3, 4)
    return pair[0]
"""), 3)

    def test_tuple_can_contain_a_list_pointer(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    value = ([8, 9], 3)
    return value[0][1]
"""), 9)

    def test_negative_literal_index(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    return (5, 6, 7)[-1]
"""), 7)

    def test_unused_tuple_expression_is_removed(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    (1, (2, 3))
    return 4
"""), 4)

    def test_tuple_creation_does_not_allocate_heap_memory(self):
        _, _, instructions = compile_source("""
main()

def main() -> int:
    pair = (1, (2, 3))
    return pair[1][0]
""")
        self.assertFalse(any(isinstance(item, ir.Malloc) for item in instructions))


class TupleRestrictionTests(unittest.TestCase):
    def test_list_of_tuples_is_rejected(self):
        module = hr.ast_to_hr(ast.parse("values = [(1, 2)]"))
        symbols = Symbols(module)
        with self.assertRaisesRegex(TypeCheckError, "heap type"):
            check_types(module, symbols, {})

    def test_nested_heap_container_with_tuple_is_rejected(self):
        module = hr.ast_to_hr(ast.parse("values = [[(1, 2)]]"))
        symbols = Symbols(module)
        with self.assertRaisesRegex(TypeCheckError, "heap type"):
            check_types(module, symbols, {})


class TupleExpansionTests(unittest.TestCase):
    def test_tuple_literal_expands_into_function_arguments(self):
        self.assertEqual(run_source("""
main()

def add(left: int, right: int) -> int:
    return left + right

def main() -> int:
    return add(*(2, 3))
"""), 5)

    def test_expansion_can_appear_between_regular_arguments(self):
        self.assertEqual(run_source("""
main()

def combine(a: int, b: int, c: int, d: int) -> int:
    return a + b + c + d

def main() -> int:
    pair = (2, 3)
    return combine(1, *pair, 4)
"""), 10)

    def test_returned_tuple_can_be_expanded_immediately(self):
        self.assertEqual(run_source("""
main()

def values() -> tuple[int, int]:
    return (6, 7)

def subtract(left: int, right: int) -> int:
    return left - right

def main() -> int:
    return subtract(*values())
"""), -1)

    def test_nested_tuple_member_remains_one_logical_argument(self):
        self.assertEqual(run_source("""
main()

def select(number: int, pair: tuple[int, int]) -> int:
    return number + pair[1]

def main() -> int:
    return select(*(1, (2, 3)))
"""), 4)

    def test_non_tuple_expansion_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "Only tuples"):
            compile_source("""
result = consume(*1)

def consume(value: int) -> int:
    return value
""")

    def test_expanded_argument_count_is_checked(self):
        with self.assertRaisesRegex(TypeCheckError, "too many arguments"):
            compile_source("""
result = consume(*(1, 2))

def consume(value: int) -> int:
    return value
""")

    def test_expanded_argument_types_are_checked(self):
        with self.assertRaisesRegex(TypeCheckError, "Invalid expanded argument"):
            compile_source("""
result = consume(*(1, "wrong"))

def consume(left: int, right: int) -> int:
    return left + right
""")

    def test_signature_context_types_empty_list_in_expansion(self):
        module = hr.ast_to_hr(ast.parse("""
result = consume(*([],))
result

def consume(values: list[int]) -> int:
    return values[0]
"""))
        symbols = Symbols(module)
        check_types(module, symbols, {})
        expanded_list = module.body[0].rhs.args[0].value.elements[0]
        self.assertEqual(expanded_list.type, ListType(INT))


class TupleAssignmentTests(unittest.TestCase):
    def test_tuple_literal_unpacks_into_variables(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    x, y = (3, 4)
    return x * 10 + y
"""), 34)

    def test_tuple_variable_unpacks_into_variables(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    pair = (5, 6)
    x, y = pair
    return x + y
"""), 11)

    def test_nested_tuple_assignment(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    x, (y, z) = (1, (2, 3))
    return x + y + z
"""), 6)

    def test_target_variable_can_receive_a_nested_tuple_member(self):
        self.assertEqual(run_source("""
main()

def main() -> int:
    pair, value = ((7, 8), 9)
    return pair[1] + value
"""), 17)

    def test_returned_tuple_can_be_unpacked(self):
        self.assertEqual(run_source("""
main()

def values() -> tuple[int, int]:
    return (4, 5)

def main() -> int:
    x, y = values()
    return x + y
"""), 9)

    def test_global_tuple_assignment_targets_use_word_offsets(self):
        self.assertEqual(run_source("""
x, y = (8, 2)
main()

def main() -> int:
    return x - y
"""), 6)

    def test_non_tuple_unpacking_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "non-tuple"):
            compile_source("x, y = 1")

    def test_unpacking_arity_is_checked(self):
        with self.assertRaisesRegex(TypeCheckError, "Cannot unpack tuple with 3 members"):
            compile_source("x, y = (1, 2, 3)")

    def test_nested_target_requires_nested_tuple(self):
        with self.assertRaisesRegex(TypeCheckError, "non-tuple member"):
            compile_source("x, (y, z) = (1, 2)")

    def test_duplicate_targets_are_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "Duplicate tuple assignment"):
            compile_source("x, x = (1, 2)")

    def test_starred_assignment_target_has_clear_error(self):
        with self.assertRaisesRegex(Exception, "Starred assignment targets"):
            hr.ast_to_hr(ast.parse("x, *rest = (1, 2, 3)"))

    def test_existing_targets_supply_context_during_unpacking(self):
        module = hr.ast_to_hr(ast.parse("""
def replace() -> int:
    values: list[int] = [1]
    marker: int = 0
    values, marker = ([], 2)
    return marker + values[0]
"""))
        symbols = Symbols(module)
        check_types(module, symbols, {})
        unpacked_list = module.body[0].body[2].rhs.elements[0]
        self.assertEqual(unpacked_list.type, ListType(INT))

if __name__ == "__main__":
    unittest.main()
