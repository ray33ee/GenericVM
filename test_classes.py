import ast
import io
import unittest
from contextlib import redirect_stdout

import hr
import interpreter
import ir
from bytecode import bytecode
from compiler import compile
from signature_inference import SignatureInferenceError
from symbols import Symbols
from typecheck import TypeCheckError
from typesystem import CHAR


def compile_source(source, builtins=None):
    module = hr.ast_to_hr(ast.parse(source))
    symbols = Symbols(module)
    return compile(module, symbols, builtins or {}, {})


class ClassTests(unittest.TestCase):
    def test_next_protocol_method_with_no_return_compiles(self):
        instructions = compile_source("""
class PRNG:
    def __init__(self, seed: str):
        self.seed = 2166136261
        for i in range(len(seed)):
            self.seed = self.seed ^ ord(seed[i])
            self.seed = (self.seed * 16777619) & 0xFFFFFFFF

    def __next__(self):
        self.seed = self.seed + 0x9E3779B9

main()
def main():
    generator = PRNG("hello!")
    print(f"{generator.seed}\\n")
    next(generator)
    return
""")
        self.assertTrue(any(isinstance(item, ir.Call) for item in instructions))

    def test_print_instructions_are_core_ir_instructions(self):
        instructions = compile_source("""
main()
def main():
    printi(1)
    printb(True)
    prints("core")
    return
""")
        core = [item for item in instructions if isinstance(item, (ir.PrintInt, ir.PrintBool, ir.PrintString))]
        self.assertEqual([type(item) for item in core], [ir.PrintInt, ir.PrintBool, ir.PrintString])
        encoded = bytecode(core, {})
        self.assertEqual(encoded, [(ir.PrintInt.OPCODE, 0), (ir.PrintBool.OPCODE, 0), (ir.PrintString.OPCODE, 0)])

    def test_print_selects_integer_boolean_string_and_newline_instructions(self):
        instructions = compile_source("""
main()
def main():
    print(1)
    print(True)
    print("text")
    print()
    return
""")
        selected = [
            type(instruction) for instruction in instructions
            if isinstance(instruction, (ir.PrintInt, ir.PrintBool, ir.PrintString))
        ]
        self.assertEqual(selected, [ir.PrintInt, ir.PrintBool, ir.PrintString, ir.PrintString])

    def test_print_streams_automatic_class_representation(self):
        instructions = compile_source("""
class Thing:
    def __init__(self):
        pass
main()
def main():
    print(Thing())
    return
""")
        output = io.StringIO()
        with redirect_stdout(output):
            interpreter.Interpreter().run(instructions)
        self.assertEqual(output.getvalue(), "Thing()")

    def test_print_fstring_streams_typed_fragments(self):
        instructions = compile_source("""
main()
def main():
    number = 7
    flag = True
    text = "ok"
    print(f"number={number}, flag={flag}, text={text}")
    return
""")
        selected = [
            "printi" if isinstance(instruction, ir.PrintInt)
            else "printb" if isinstance(instruction, ir.PrintBool)
            else "prints"
            for instruction in instructions
            if isinstance(instruction, (ir.PrintInt, ir.PrintBool, ir.PrintString))
        ]
        self.assertEqual(
            selected,
            ["prints", "printi", "prints", "printb", "prints", "prints"],
        )

    def test_print_bool_renders_boolean_words(self):
        instructions = compile_source("""
main()
def main():
    printb(True)
    printb(False)
    return
""")
        output = io.StringIO()
        with redirect_stdout(output):
            interpreter.Interpreter().run(instructions)
        self.assertEqual(output.getvalue(), "TrueFalse")

    def test_direct_fstring_print_streams_without_concat_or_integer_conversion(self):
        instructions = compile_source("""
main()
def main():
    text = "Thing(7)"
    print(f"{text[0]}")
    return
""")
        self.assertTrue(any(isinstance(item, ir.PrintChar) for item in instructions))
        output = io.StringIO()
        with redirect_stdout(output):
            interpreter.Interpreter().run(instructions)
        self.assertEqual(output.getvalue(), "T")

    def test_char_literals_ord_chr_indexing_and_printc(self):
        module = hr.ast_to_hr(ast.parse("""
main()
def main() -> int:
    character = 'A'
    indexed = "BC"[0]
    printc(character)
    print(indexed)
    return ord(character) + ord(chr(1))
"""))
        symbols = Symbols(module)
        instructions = compile(module, symbols, {}, {})
        function_symbols = symbols.functions["main"][0]
        self.assertIs(function_symbols["character"].type, CHAR)
        self.assertIs(function_symbols["indexed"].type, CHAR)
        self.assertEqual(sum(isinstance(item, ir.PrintChar) for item in instructions), 2)
        output = io.StringIO()
        with redirect_stdout(output):
            result = interpreter.Interpreter().run(instructions)
        self.assertEqual(output.getvalue(), "AB")
        self.assertEqual(result, 66)

    def test_print_char_is_encoded_as_core_ir(self):
        self.assertEqual(bytecode([ir.PrintChar()], {}), [(ir.PrintChar.OPCODE, 0)])

    def test_explicit_char_to_string_uses_malloc_and_store(self):
        instructions = compile_source("""
main()
def main():
    print(str('A'))
    return
""")
        self.assertEqual(sum(isinstance(item, ir.Malloc) for item in instructions), 1)
        self.assertEqual(sum(isinstance(item, ir.Store) for item in instructions), 2)
        output = io.StringIO()
        with redirect_stdout(output):
            interpreter.Interpreter().run(instructions)
        self.assertEqual(output.getvalue(), "A")

    def test_fstring_cannot_be_stored(self):
        with self.assertRaisesRegex(TypeCheckError, "streaming-only"):
            compile_source("""
main()
def main() -> str:
    value = 7
    text = f"value={value}"
    return text
""")

    def test_str_prefers_str_then_repr_then_automatic_fields(self):
        instructions = compile_source("""
class Preferred:
    def __init__(self):
        pass
    def __str__(self) -> str:
        return "str-value"
    def __repr__(self) -> str:
        return "repr-value"

class ReprOnly:
    def __init__(self):
        pass
    def __repr__(self) -> str:
        return "repr-only"

class Automatic:
    def __init__(self, number: int, flag: bool):
        self.number = number
        self.flag = flag

main()
def main():
    print(str(Preferred()))
    print(str(ReprOnly()))
    print(str(Automatic(7, True)))
    return
""")
        output = io.StringIO()
        with redirect_stdout(output):
            interpreter.Interpreter().run(instructions)
        self.assertEqual(
            output.getvalue(),
            "str-value"
            "repr-only"
            "Automatic(7, True)",
        )

    def test_protocol_builtins_dispatch_to_dunder_methods(self):
        instructions = compile_source("""
class Value:
    def __init__(self, value: int):
        self.value = value

    def __len__(self):
        return self.value

    def __int__(self):
        return self.value + 1

    def __next__(self):
        return self.value + 2

main()
def main() -> int:
    value = Value(5)
    return len(value) + int(value) + next(value)
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 18)

    def test_protocol_builtin_requires_matching_dunder(self):
        with self.assertRaisesRegex(TypeCheckError, "does not implement __len__"):
            compile_source("""
class Empty:
    def __init__(self):
        pass

main()
def main() -> int:
    return len(Empty())
""")

    def test_protocol_dunder_return_type_is_validated(self):
        with self.assertRaisesRegex(TypeCheckError, "Invalid return type for 'Bad.__len__'"):
            compile_source("""
class Bad:
    def __init__(self):
        pass
    def __len__(self):
        return 1.0

main()
def main() -> int:
    return len(Bad())
""")

    def test_constructor_and_method_parameters_are_inferred_from_calls(self):
        instructions = compile_source("""
class Value:
    def __init__(self, value):
        self.value = value

    def plus(self, amount):
        return self.value + amount

main()
def main() -> int:
    return Value(7).plus(5)
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 12)

    def test_conflicting_method_call_types_are_rejected(self):
        with self.assertRaisesRegex(SignatureInferenceError, "Conflicting calls for parameter 'value'"):
            compile_source("""
class Identity:
    def __init__(self):
        pass
    def accept(self, value):
        return value

main()
def main():
    identity = Identity()
    identity.accept(1)
    identity.accept(1.0)
    return
""")

    def test_recursive_method_is_anchored_by_external_call(self):
        instructions = compile_source("""
class Maths:
    def __init__(self):
        pass

    def sum_to(self, value):
        if value == 0:
            return 0
        return value + self.sum_to(value - 1)

main()
def main() -> int:
    return Maths().sum_to(4)
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 10)

    def test_mutually_recursive_method_parameters_propagate_external_anchor(self):
        instructions = compile_source("""
class Alternating:
    def __init__(self):
        pass

    def first(self, value):
        if value == 0:
            return 0
        return self.second(value - 1)

    def second(self, value):
        if value == 0:
            return 0
        return self.first(value - 1)

main()
def main() -> int:
    return Alternating().first(4)
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 0)

    def test_unanchored_recursive_method_parameter_is_rejected(self):
        with self.assertRaisesRegex(SignatureInferenceError, "Cannot infer parameter 'value' of method"):
            compile_source("""
class Recursive:
    def __init__(self):
        pass
    def repeat(self, value):
        return self.repeat(value)
""")

    def test_tuple_expansion_in_constructor_and_method_call(self):
        instructions = compile_source("""
class Pair:
    def __init__(self, left: int, right: int):
        self.left = left
        self.right = right

    def total(self, extra: int, more: int) -> int:
        return self.left + self.right + extra + more

main()
def main() -> int:
    pair = Pair(*(2, 3))
    return pair.total(*(4, 5))
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 14)

    def test_reverse_and_unary_operators_execute(self):
        instructions = compile_source("""
class Value:
    def __init__(self, value: int):
        self.value = value

    def __radd__(self, left: int):
        return Value(left + self.value)

    def __neg__(self):
        return Value(-self.value)

main()
def main() -> int:
    return (-(5 + Value(2))).value
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), -7)

    def test_nested_object_fields_execute(self):
        instructions = compile_source("""
class Inner:
    def __init__(self, value: int):
        self.value = value

class Outer:
    def __init__(self, inner: Inner):
        self.inner = inner

main()
def main() -> int:
    return Outer(Inner(9)).inner.value
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 9)

    def test_all_declared_fields_must_be_definitely_initialized(self):
        with self.assertRaisesRegex(TypeCheckError, "does not initialize fields: value"):
            compile_source("""
class Broken:
    value: int
    def __init__(self, condition: bool):
        if condition:
            self.value = 1
""")

    def test_field_initialized_in_both_branches_is_valid(self):
        instructions = compile_source("""
class Complete:
    value: int
    def __init__(self, condition: bool):
        if condition:
            self.value = 1
        else:
            self.value = 2

main()
def main() -> int:
    return Complete(False).value
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 2)

    def test_field_cannot_be_read_before_initialization(self):
        with self.assertRaisesRegex(TypeCheckError, "read before initialization"):
            compile_source("""
class Broken:
    first: int
    second: int
    def __init__(self):
        self.second = self.first
        self.first = 1
""")

    def test_class_and_function_names_cannot_collide(self):
        with self.assertRaisesRegex(Exception, "Name 'Duplicate' is already defined"):
            compile_source("""
class Duplicate:
    def __init__(self):
        pass

def Duplicate():
    return
""")

    def test_zero_word_field_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "exactly one heap word"):
            compile_source("""
class Invalid:
    value: None
    def __init__(self):
        self.value = None
""")

    def test_method_return_and_add_operator_are_inferred(self):
        instructions = compile_source("""
class Thing:
    def __init__(self, x: int):
        self.x = x

    def __add__(self, x: int):
        return Thing(self.x + x)

main()

def main() -> int:
    thing = Thing(7)
    result = thing + 5
    return result.x
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 12)

    def test_method_return_is_inferred_for_normal_method_call(self):
        instructions = compile_source("""
class Counter:
    def __init__(self, value: int):
        self.value = value

    def increment(self, amount: int):
        return Counter(self.value + amount)

main()

def main() -> int:
    return Counter(2).increment(3).value
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 5)

    def test_constructor_fields_and_method_execute(self):
        instructions = compile_source("""
class Thing:
    def __init__(self, x: int):
        self.x = x

    def get(self) -> int:
        return self.x

main()

def main() -> int:
    thing = Thing(41)
    thing.x = thing.x + 1
    return thing.get()
""")
        self.assertEqual(interpreter.Interpreter().run(instructions), 42)

    def test_constructor_arity_is_reported_as_type_error(self):
        with self.assertRaisesRegex(TypeCheckError, "Thing.*expects 1 arguments"):
            compile_source("""
class Thing:
    x: int
    def __init__(self, x: int):
        self.x = x

main()
def main():
    thing = Thing()
    thing
    return
""")

    def test_tuple_field_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "stack-only tuple"):
            compile_source("""
class Bad:
    value: tuple[int, int]
    def __init__(self):
        self
""")


if __name__ == "__main__":
    unittest.main()
