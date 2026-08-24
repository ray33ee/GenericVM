import ast
import unittest

import hr
import interpreter
from compiler import compile
from signature_inference import DeadCodeError, SignatureInferenceError
from symbols import Symbols
from typecheck import TypeCheckError, check_types
from typesystem import BOOL, FLOAT, INT, TupleType


def analyse(source: str):
    module = hr.ast_to_hr(ast.parse(source))
    symbols = Symbols(module)
    check_types(module, symbols, {})
    return module, symbols


def run(source: str):
    module = hr.ast_to_hr(ast.parse(source))
    instructions = compile(module, Symbols(module), {}, {})
    return interpreter.Interpreter().run(instructions)


def function_named(module, name):
    return next(
        node for node in module.body
        if isinstance(node, hr.FunctionDef) and node.name == name
    )


class BasicSignatureInferenceTests(unittest.TestCase):
    def test_unused_function_is_reported_before_signature_inference(self):
        with self.assertRaisesRegex(DeadCodeError, "Function 'unused' is never called"):
            analyse("""
main()

def unused(x, y):
    return x + y

def main():
    return
""")

    def test_unreachable_statement_after_return_is_rejected(self):
        with self.assertRaisesRegex(DeadCodeError, "Unreachable Expr statement"):
            analyse("""
main()

def main():
    return
    1
""")

    def test_class_field_at_external_call_infers_parameter(self):
        module, _ = analyse("""
class Thing:
    def __init__(self, x: int):
        self.x = x

def add(x, y):
    return x + y

main()

def main():
    thing = Thing(7)
    return add(thing.x, 5)
""")
        function = function_named(module, "add")
        self.assertIs(function.args[0].annotation, INT)
        self.assertIs(function.args[1].annotation, INT)
        self.assertIs(function.return_type, INT)

    def test_arguments_and_return_are_inferred_from_call_and_body(self):
        module, symbols = analyse("""
result = add(2, 3)
result

def add(left, right):
    return left + right
""")
        function = function_named(module, "add")
        self.assertIs(function.args[0].annotation, INT)
        self.assertIs(function.args[1].annotation, INT)
        self.assertIs(function.return_type, INT)
        self.assertIs(symbols.top_level["result"].type, INT)

    def test_fully_inferred_function_executes(self):
        self.assertEqual(run("""
main()

def add(left, right):
    return left + right

def main():
    return add(4, 5)
"""), 9)

    def test_explicit_parameter_can_have_inferred_return(self):
        module, _ = analyse("""
result = increment(2)
result

def increment(value: int):
    return value + 1
""")
        self.assertIs(function_named(module, "increment").return_type, INT)

    def test_tuple_parameter_and_return_are_inferred(self):
        module, _ = analyse("""
result = swap((2, 3))
result

def swap(pair):
    return (pair[1], pair[0])
""")
        function = function_named(module, "swap")
        self.assertEqual(function.args[0].annotation, TupleType((INT, INT)))
        self.assertEqual(function.return_type, TupleType((INT, INT)))

    def test_starred_external_call_infers_each_parameter(self):
        module, _ = analyse("""
result = add(*(2, 3))
result

def add(left, right):
    return left + right
""")
        function = function_named(module, "add")
        self.assertIs(function.args[0].annotation, INT)
        self.assertIs(function.args[1].annotation, INT)

    def test_external_anchor_propagates_through_nonrecursive_calls(self):
        module, _ = analyse("""
result = outer(2)
result

def outer(value):
    return inner(value)

def inner(value):
    return value + 1
""")
        outer = function_named(module, "outer")
        inner = function_named(module, "inner")
        self.assertIs(outer.args[0].annotation, INT)
        self.assertIs(inner.args[0].annotation, INT)
        self.assertIs(outer.return_type, INT)
        self.assertIs(inner.return_type, INT)

    def test_function_without_return_infers_none(self):
        module, _ = analyse("""
consume(1)

def consume(value):
    value
""")
        self.assertEqual(str(function_named(module, "consume").return_type), "NoneType")

    def test_contextual_integer_literal_is_emitted_as_float(self):
        self.assertEqual(run("""
main()

def identity(value: float):
    return value

def main():
    return identity(1)
"""), 1.0)

    def test_conflicting_external_calls_are_rejected(self):
        with self.assertRaisesRegex(SignatureInferenceError, "Conflicting external calls"):
            analyse("""
first = identity(1)
second = identity(1.0)

def identity(value):
    return value
""")

    def test_conflicting_external_calls_are_order_independent(self):
        with self.assertRaisesRegex(SignatureInferenceError, "Conflicting external calls"):
            analyse("""
first = identity(1.0)
second = identity(1)

def identity(value):
    return value
""")

    def test_uncalled_parameter_is_not_inferred_from_body(self):
        with self.assertRaisesRegex(SignatureInferenceError, "external call"):
            analyse("""
def increment(value):
    return value + 1
""")

    def test_incompatible_inferred_returns_are_rejected(self):
        with self.assertRaisesRegex(SignatureInferenceError, "incompatible inferred return"):
            analyse("""
result = choose(True)

def choose(flag):
    if flag:
        return 1
    return "wrong"
""")


class RecursiveSignatureInferenceTests(unittest.TestCase):
    def test_integer_factorial_signature_is_inferred(self):
        module, _ = analyse("""
result = factorial(5)
result

def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n - 1)
""")
        factorial = function_named(module, "factorial")
        self.assertIs(factorial.args[0].annotation, INT)
        self.assertIs(factorial.return_type, INT)

    def test_integer_factorial_executes(self):
        self.assertEqual(run("""
main()

def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n - 1)

def main():
    return factorial(5)
"""), 120)

    def test_float_call_anchors_recursive_parameter_as_float(self):
        module, _ = analyse("""
result = factorial(3.0)
result

def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n - 1)
""")
        factorial = function_named(module, "factorial")
        self.assertIs(factorial.args[0].annotation, FLOAT)
        self.assertIs(factorial.return_type, FLOAT)

    def test_float_recursive_function_executes(self):
        self.assertEqual(run("""
main()

def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n - 1)

def main():
    return factorial(3.0)
"""), 6.0)

    def test_internal_recursive_call_is_checked_not_used_as_literal_evidence(self):
        with self.assertRaisesRegex(TypeCheckError, "Invalid argument"):
            analyse("""
result = recurse(2)

def recurse(value):
    if value == 0:
        return 0
    return recurse("wrong")
""")

    def test_unanchored_recursive_signature_requires_annotation(self):
        with self.assertRaisesRegex(SignatureInferenceError, "external call"):
            analyse("""
def recurse(value):
    return recurse(value)
""")

    def test_mutually_recursive_parameters_propagate_external_anchor(self):
        module, _ = analyse("""
result = even(8)
result

def even(n):
    if n == 0:
        return True
    return odd(n - 1)

def odd(n):
    if n == 0:
        return False
    return even(n - 1)
""")
        even = function_named(module, "even")
        odd = function_named(module, "odd")
        self.assertIs(even.args[0].annotation, INT)
        self.assertIs(odd.args[0].annotation, INT)
        self.assertIs(even.return_type, BOOL)
        self.assertIs(odd.return_type, BOOL)

    def test_mutual_recursion_executes(self):
        self.assertEqual(run("""
main()

def even(n):
    if n == 0:
        return True
    return odd(n - 1)

def odd(n):
    if n == 0:
        return False
    return even(n - 1)

def main():
    return 1 if even(10) else 0
"""), 1)


if __name__ == "__main__":
    unittest.main()
