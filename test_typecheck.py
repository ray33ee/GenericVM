import ast
import unittest

import hr
import interpreter
import ir
from compiler import compile
from symbols import Symbols
from typecheck import TypeCheckError, check_types
from typesystem import (
    BOOL,
    CHAR,
    INT,
    NONE,
    STR,
    ListType,
    TupleType,
)


BUILTINS = {}


def analyse(source: str, builtins=None):
    module = hr.ast_to_hr(ast.parse(source))
    symbols = Symbols(module)
    check_types(module, symbols, builtins or {})
    return module, symbols


class TypeInferenceTests(unittest.TestCase):
    def test_string_slice_requires_integer_bounds_and_no_step(self):
        with self.assertRaisesRegex(TypeCheckError, "bound must be int"):
            analyse('text = "abc"\nresult = text["x":]\nresult\n')
        with self.assertRaisesRegex(TypeCheckError, "steps are not currently supported"):
            analyse('text = "abc"\nresult = text[::2]\nresult\n')

    def test_unannotated_variables_are_inferred(self):
        module, symbols = analyse("""
x = 1
message = "hello"
items = [1, 2, 3]
pair = (1, "two")
x
message
items
pair
""")

        self.assertIs(symbols.top_level["x"].type, INT)
        self.assertIs(symbols.top_level["message"].type, STR)
        self.assertEqual(symbols.top_level["items"].type, ListType(INT))
        self.assertEqual(symbols.top_level["pair"].type, TupleType((INT, STR)))
        self.assertTrue(
            all(
                statement.rhs.type is not None
                for statement in module.body
                if isinstance(statement, hr.Assign)
            )
        )

    def test_nested_list_and_tuple_types_are_complete(self):
        _, symbols = analyse("""
values = [[1, 2], [3]]
record = (1, [2, 3], (4, 5))
values
record
""")

        self.assertEqual(symbols.top_level["values"].type, ListType(ListType(INT)))
        self.assertEqual(
            symbols.top_level["record"].type,
            TupleType((INT, ListType(INT), TupleType((INT, INT)))),
        )

    def test_context_types_an_empty_list(self):
        _, symbols = analyse("""
def empty() -> list[int]:
    result: list[int] = []
    return result
""")
        self.assertEqual(symbols.functions["empty"][0]["result"].type, ListType(INT))

    def test_empty_list_without_context_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "empty list"):
            analyse("items = []")

    def test_mixed_list_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "List elements"):
            analyse('items = [1, "two"]')

    def test_variable_type_cannot_change(self):
        with self.assertRaisesRegex(TypeCheckError, "Cannot assign"):
            analyse("""
def invalid() -> int:
    value = 1
    value = "changed"
    return value
""")

    def test_subscript_result_types(self):
        module, _ = analyse("""
numbers: list[int] = [1]
number = numbers[0]
pair = (1, "two")
word = pair[1]
letter = "abc"[0]
number
word
letter
""")
        assignments = {
            statement.lhs.id: statement
            for statement in module.body
            if isinstance(statement, hr.Assign)
        }
        self.assertIs(assignments["number"].rhs.type, INT)
        self.assertIs(assignments["word"].rhs.type, STR)
        self.assertIs(assignments["letter"].rhs.type, CHAR)

    def test_dynamic_heterogeneous_tuple_index_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "integer literal"):
            analyse("""
pair = (1, "two")
index = 0
value = pair[index]
""")

    def test_tuple_assignment_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "immutable"):
            analyse("""
pair = (1, 2)
pair[0] = 3
""")

    def test_operators_and_conditions_are_typed(self):
        module, _ = analyse("""
def choose(left: int, right: int) -> int:
    total = left + right
    return total if left < right else right
""")
        function = module.body[0]
        self.assertIs(function.body[0].rhs.type, INT)
        self.assertIs(function.body[1].value.condition.type, BOOL)
        self.assertIs(function.body[1].value.type, INT)

    def test_non_bool_condition_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "Condition must be bool"):
            analyse("""
def invalid(value: int) -> int:
    if value:
        return 1
    else:
        return 2
""")

    def test_function_calls_use_parameter_and_return_types(self):
        module, symbols = analyse("""
result = first([])
result

def first(values: list[int]) -> int:
    return values[0]
""")
        self.assertIs(symbols.top_level["result"].type, INT)
        self.assertEqual(module.body[0].rhs.args[0].type, ListType(INT))

    def test_bad_function_argument_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "Invalid argument"):
            analyse("""
result = identity("wrong")

def identity(value: int) -> int:
    return value
""")

    def test_non_none_function_must_return_on_every_path(self):
        with self.assertRaisesRegex(TypeCheckError, "every path"):
            analyse("""
def invalid(flag: bool) -> int:
    if flag:
        return 1
""")

    def test_builtin_signatures_are_checked(self):
        module, _ = analyse("printi(1)", BUILTINS)
        self.assertIs(module.body[0].expr.type, NONE)

        with self.assertRaisesRegex(TypeCheckError, "printi expects int"):
            analyse('printi("wrong")', BUILTINS)


class TypedCompilerTests(unittest.TestCase):
    def test_integer_modulo_is_typed_compiled_and_interpreted(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    return 17 % 5
"""))
        instructions = compile(module, Symbols(module), {}, {})

        self.assertEqual(interpreter.Interpreter().run(instructions), 2)
        self.assertEqual(sum(isinstance(item, ir.IMod) for item in instructions), 1)

    def test_modulo_rejects_float_operands(self):
        with self.assertRaisesRegex(TypeCheckError, "Mod requires int operands"):
            analyse("result = 5.0 % 2")

    def test_mixed_numeric_arithmetic_promotes_int_and_uses_float_instruction(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> float:
    integer: int = 7
    floating: float = 0.5
    return integer + floating
"""))
        instructions = compile(module, Symbols(module), {}, {})

        self.assertEqual(interpreter.Interpreter().run(instructions), 7.5)
        self.assertEqual(sum(isinstance(item, ir.IntToFloat) for item in instructions), 1)
        self.assertEqual(sum(isinstance(item, ir.FAdd) for item in instructions), 1)

    def test_arithmetic_instruction_family_is_selected_from_operand_type(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> float:
    integer: int = 3
    floating: float = 2.0
    return -(integer * floating) - +1.0
"""))
        instructions = compile(module, Symbols(module), {}, {})

        self.assertEqual(interpreter.Interpreter().run(instructions), -7.0)
        self.assertTrue(any(isinstance(item, ir.FMultiply) for item in instructions))
        self.assertTrue(any(isinstance(item, ir.FUnaryNegative) for item in instructions))
        self.assertTrue(any(isinstance(item, ir.FUnaryPositive) for item in instructions))
        self.assertTrue(any(isinstance(item, ir.FSub) for item in instructions))

    def test_string_len_uses_value_word_and_list_len_loads_heap_header(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    text = "hello"
    values = [10, 20, 30]
    return len(text) + len(values)
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 8)
        self.assertEqual(sum(isinstance(item, ir.ISub) for item in instructions), 0)
        self.assertGreaterEqual(sum(isinstance(item, ir.Load) for item in instructions), 1)

    def test_dynamic_list_mutations_preserve_aliases(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    values = [1, 2]
    alias = values
    values.append(4)
    values.insert(1, 3)
    removed = alias.pop(0)
    return removed + len(values) * 10 + alias[0] + alias[2]
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 38)

    def test_list_slice_is_an_independent_dynamic_list(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    values = [10, 20, 30, 40]
    sliced = values[-3:3]
    sliced.append(50)
    sliced[0] = 7
    return len(values) * 100 + len(sliced) * 10 + sliced[0] + sliced[2]
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 487)

    def test_dynamic_list_supports_two_word_strings_and_clear(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    values: list[str] = ["a"]
    values.append("bc")
    values.insert(1, "xyz")
    removed: str = values.pop()
    score: int = len(removed) + len(values[1])
    values.clear()
    return score + len(values)
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 5)

    def test_sparse_list_shrinks_without_losing_elements(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    values: list[int] = []
    i: int = 0
    while i < 8:
        values.append(i)
        i = i + 1
    while len(values) > 2:
        values.pop()
    return len(values) * 100 + values[0] * 10 + values[1]
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 201)

    def test_unknown_empty_list_propagates_through_alias(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    values = []
    alias = values
    alias.append(7)
    return values[0]
"""))
        symbols = Symbols(module)
        instructions = compile(module, symbols, {}, {})
        self.assertEqual(symbols.functions["main"][0]["values"].type, ListType(INT))
        self.assertEqual(symbols.functions["main"][0]["alias"].type, ListType(INT))
        self.assertEqual(interpreter.Interpreter().run(instructions), 7)

    def test_empty_list_append_anchors_nested_constructor_call(self):
        module = hr.ast_to_hr(ast.parse("""
class Thing:
    def __init__(self, x, y):
        self.x = x
        self.y = y

main()

def main():
    values = []
    for i in range(10):
        values.append(Thing(i, i * 2))
    return
"""))
        symbols = Symbols(module)
        compile(module, symbols, {}, {})
        constructor = symbols.classes["Thing"].methods["__init__"]
        self.assertEqual([argument.annotation for argument in constructor.args[1:]], [INT, INT])
        self.assertEqual(
            symbols.functions["main"][0]["values"].type,
            ListType(symbols.classes["Thing"].type),
        )

    def test_conflicting_evidence_for_unknown_list_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "Invalid list.append value"):
            analyse("""
values = []
values.append(1)
values.append("two")
values
""")

    def test_string_field_uses_two_contiguous_heap_words(self):
        module = hr.ast_to_hr(ast.parse("""
main()

class Box:
    text: str
    def __init__(self, text: str):
        self.text = text
    def score(self) -> int:
        return len(self.text) + ord(self.text[1])

def main() -> int:
    return Box("abc").score()
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 101)

    def test_list_of_strings_supports_indexed_load_and_store(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    values: list[str] = ["a", "bc"]
    values[0] = "xyz"
    return len(values[0]) + ord(values[1][1])
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 102)

    def test_compiler_runs_type_analysis_and_executes_inferred_locals(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    value = 10
    return value + 2
"""))
        symbols = Symbols(module)
        instructions = compile(module, symbols, {}, {})

        self.assertIs(symbols.functions["main"][0]["value"].type, INT)
        self.assertEqual(interpreter.Interpreter().run(instructions), 12)

    def test_typed_logical_and_unary_operations_execute(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    return 1 if True and not False else 0
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 1)

    def test_inferred_list_subscript_executes(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    values = [10, 20]
    return values[1]
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 20)

    def test_typed_user_call_executes(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def identity(value: int) -> int:
    return value

def main() -> int:
    return identity(7)
"""))
        instructions = compile(module, Symbols(module), {}, {})
        self.assertEqual(interpreter.Interpreter().run(instructions), 7)

    def test_range_target_is_inferred_as_int(self):
        module = hr.ast_to_hr(ast.parse("""
main()

def main() -> int:
    total = 0
    for index in range(3):
        total = total + index
    return total
"""))
        symbols = Symbols(module)
        instructions = compile(module, symbols, {}, {})
        self.assertIs(symbols.functions["main"][0]["index"].type, INT)
        self.assertEqual(interpreter.Interpreter().run(instructions), 3)

    def test_compiler_rejects_untyped_builtin_declarations(self):
        module = hr.ast_to_hr(ast.parse("printi(1)"))
        symbols = Symbols(module)
        with self.assertRaisesRegex(TypeError, "BuiltinSignature"):
            compile(module, symbols, {"printi": (1, 1001)}, {})

    def test_tuple_runtime_uses_inline_global_words(self):
        module = hr.ast_to_hr(ast.parse("pair = (1, 2)\npair"))
        symbols = Symbols(module)
        instructions = compile(module, symbols, {}, {})
        self.assertEqual(symbols.top_level["pair"].word_width, 2)
        self.assertFalse(any(type(item).__name__ == "Malloc" for item in instructions))


class GlobalDeadVariableTests(unittest.TestCase):
    def test_unused_global_is_rejected(self):
        module = hr.ast_to_hr(ast.parse("value = 1"))
        symbols = Symbols(module)
        with self.assertRaisesRegex(Exception, "Global variable value is declared but never read"):
            check_types(module, symbols, {})

    def test_top_level_read_marks_global_as_used(self):
        analyse("""
value = 1
value
""")

    def test_read_inside_function_marks_global_as_used(self):
        analyse("""
value = 1

def read() -> int:
    return value
""")

    def test_rhs_read_and_final_read_cover_global_chain(self):
        analyse("""
first = 1
second = first
second
""")


if __name__ == "__main__":
    unittest.main()
