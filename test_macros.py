import unittest

import ir
from compiler import compile_source
from interpreter import Interpreter


class MacroTests(unittest.TestCase):
    def run_source(self, source):
        return Interpreter().run(compile_source(source))

    def test_macro_main_without_return_implicitly_returns_zero(self):
        source = """
main()

@macro
def main():
    x = "yes"
    print(x)
"""
        self.assertEqual(self.run_source(source), 0)

    def test_macro_is_expanded_without_call_or_function_body(self):
        operations = list(compile_source("""
main()

@macro
def add_one(value: int) -> int:
    return value + 1

def main() -> int:
    return add_one(41)
"""))
        self.assertEqual(Interpreter().run(operations), 42)
        self.assertEqual(sum(isinstance(operation, ir.Call) for operation in operations), 1)

    def test_terminal_macro_return_does_not_emit_jump(self):
        operations = list(compile_source("""
identity(42)

@macro
def identity(value: int) -> int:
    return value
"""))
        self.assertFalse(any(isinstance(operation, ir.Jump) for operation in operations))

    def test_macro_parameters_and_locals_do_not_clash_with_caller(self):
        source = """
main()

@macro
def adjust(value: int) -> int:
    temporary: int = value + 10
    value = temporary + 1
    return value

def main() -> int:
    value: int = 3
    temporary: int = 100
    first: int = adjust(value)
    second: int = adjust(5)
    return value + temporary + first + second
"""
        self.assertEqual(self.run_source(source), 133)

    def test_nested_macros_have_separate_hygienic_storage(self):
        source = """
main()

@macro
def inner(value: int) -> int:
    local: int = value * 2
    return local

@macro
def outer(value: int) -> int:
    local: int = value + 1
    return inner(local) + value

def main() -> int:
    local: int = 50
    value: int = 4
    return outer(value) + local + value
"""
        self.assertEqual(self.run_source(source), 68)

    def test_macro_return_exits_only_the_expansion(self):
        source = """
main()

@macro
def absolute(value: int) -> int:
    if value < 0:
        return -value
    return value

def main() -> int:
    result: int = absolute(-7)
    return result + 1
"""
        self.assertEqual(self.run_source(source), 8)

    def test_macro_argument_is_evaluated_exactly_once(self):
        source = """
counter: int = 0
main()

def next_value() -> int:
    counter = counter + 1
    return counter

@macro
def doubled(value: int) -> int:
    return value + value

def main() -> int:
    result: int = doubled(next_value())
    return result + counter * 10
"""
        self.assertEqual(self.run_source(source), 12)

    def test_macro_supports_multiword_parameters_and_results(self):
        source = """
main()

@macro
def swap(pair: tuple[int, int]) -> tuple[int, int]:
    left: int = pair[0]
    right: int = pair[1]
    return right, left

def main() -> int:
    result: tuple[int, int] = swap((20, 22))
    return result[0] - result[1]
"""
        self.assertEqual(self.run_source(source), 2)

    def test_macro_supports_starred_arguments(self):
        source = """
main()

@macro
def subtract(left: int, right: int) -> int:
    return left - right

def main() -> int:
    values: tuple[int, int] = (50, 8)
    return subtract(*values)
"""
        self.assertEqual(self.run_source(source), 42)

    def test_method_macro_is_hygienic_in_caller_and_self_storage(self):
        source = """
main()

class Calculator:
    def __init__(self, offset: int):
        self.offset = offset

    @macro
    def adjusted(self, value: int) -> int:
        temporary: int = value + self.offset
        value = temporary + 1
        return value

def main() -> int:
    calculator: Calculator = Calculator(10)
    value: int = 3
    temporary: int = 100
    first: int = calculator.adjusted(value)
    second: int = calculator.adjusted(5)
    return value + temporary + first + second
"""
        self.assertEqual(self.run_source(source), 133)

    def test_method_macro_can_call_another_method_macro(self):
        source = """
main()

class Number:
    def __init__(self, value: int):
        self.value = value

    @macro
    def doubled(self, value: int) -> int:
        local: int = value * 2
        return local

    @macro
    def combined(self, value: int) -> int:
        local: int = value + self.value
        return self.doubled(local) + value

def main() -> int:
    number: Number = Number(3)
    local: int = 100
    return number.combined(4) + local
"""
        self.assertEqual(self.run_source(source), 118)

    def test_special_method_macro_is_rejected(self):
        source = """
class Number:
    @macro
    def __init__(self, value: int):
        self.value = value
Number(1)
"""
        with self.assertRaisesRegex(Exception, "Special method 'Number.__init__' cannot be a macro"):
            compile_source(source)

    def test_main_can_be_a_macro(self):
        source = """
main()

@macro
def main() -> int:
    local: int = 40
    return local + 2
"""
        operations = list(compile_source(source))
        self.assertFalse(any(isinstance(operation, ir.Call) for operation in operations))
        self.assertFalse(any(isinstance(operation, ir.Return) for operation in operations))
        self.assertFalse(any(isinstance(operation, ir.Jump) for operation in operations))
        self.assertEqual(Interpreter().run(operations), 42)

    def test_recursive_macro_is_rejected(self):
        source = """
loop(1)

@macro
def loop(value: int) -> int:
    return loop(value)
"""
        with self.assertRaisesRegex(Exception, "Recursive macro expansion"):
            compile_source(source)

    def test_unknown_decorator_is_rejected(self):
        with self.assertRaisesRegex(Exception, "Unsupported function decorator"):
            compile_source("""
@inline
def identity(value: int) -> int:
    return value
identity(1)
""")


if __name__ == "__main__":
    unittest.main()
