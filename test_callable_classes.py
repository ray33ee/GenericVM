import io
import unittest
from contextlib import redirect_stdout

import interpreter
from test_classes import compile_source
from signature_inference import SignatureInferenceError
from typecheck import TypeCheckError


class CallableClassTests(unittest.TestCase):
    def test_constructor_infers_list_populated_in_nested_block(self):
        for block, expected in (
            ('for i in range(3):\n        values.append(i)', 0),
            ('while len(values) < 3:\n        values.append(len(values))', 0),
            ('if True:\n        values.append(2)', 2),
        ):
            with self.subTest(block=block):
                source = '''
class Poly:
    def __init__(self, coeffs):
        self.coeffs = coeffs
    def __call__(self):
        return self.coeffs[0]
main()
def main():
    values = []
    BLOCK
    poly = Poly(values[:])
    return poly()
'''.replace('BLOCK', block)
                self.assertEqual(self.run_source(source), expected)

    def test_argument_inferred_from_pointer_index(self):
        self.assertEqual(self.run_source('''
class Double:
    def __init__(self):
        pass
    def __call__(self, x):
        return x * 2
main()
def main():
    values = malloc(1)
    values[0] = 21
    double = Double()
    result = double(values[0])
    free(values)
    return result
'''), 42)

    def run_source(self, source):
        instructions = compile_source(source)
        with redirect_stdout(io.StringIO()):
            return interpreter.Interpreter().run(instructions)

    def test_inferred_arguments_return_and_mutation(self):
        self.assertEqual(self.run_source('''
class Counter:
    def __init__(self, value):
        self.value = value
    def __call__(self, amount):
        self.value = self.value + amount
        return self.value
def invoke(counter: Counter):
    return counter(3)
main()
def main():
    counter = Counter(4)
    first = invoke(counter)
    return first + counter(2)
'''), 16)

    def test_defaults_expansion_and_tuple_result(self):
        self.assertEqual(self.run_source('''
class Pair:
    def __init__(self):
        pass
    def __call__(self, left: int, right: int = 5) -> tuple[int, int]:
        return (left, right)
main()
def main():
    pair = Pair()
    a, b = pair(2)
    c, d = pair(*(3, 4))
    return a + b + c + d
'''), 14)

    def test_expression_and_field_receivers(self):
        self.assertEqual(self.run_source('''
class Callable:
    def __init__(self):
        pass
    def __call__(self, value: int) -> int:
        return value + 1
class Holder:
    def __init__(self):
        self.callback = Callable()
def make() -> Callable:
    return Callable()
main()
def main():
    holder = Holder()
    callbacks = [Callable()]
    return Callable()(1) + make()(2) + holder.callback(3) + callbacks[0](4)
'''), 14)

    def test_recursive_call(self):
        self.assertEqual(self.run_source('''
class Sum:
    def __init__(self):
        pass
    def __call__(self, n):
        if n == 0:
            return 0
        return n + self(n - 1)
main()
def main():
    total = Sum()
    return total(4)
'''), 10)

    def test_invalid_calls_are_rejected(self):
        for expression in ('callback()', 'callback(1, 2)', 'callback(True)'):
            with self.subTest(expression=expression):
                with self.assertRaises((TypeCheckError, SignatureInferenceError)):
                    compile_source('''
class Callable:
    def __init__(self):
        pass
    def __call__(self, value: int) -> int:
        return value
main()
def main():
    callback = Callable()
    return ''' + expression)

    def test_non_callable_instance_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "__call__"):
            compile_source('''
class Empty:
    def __init__(self):
        pass
main()
def main() -> int:
    value = Empty()
    return value()
''')

    def test_result_type_is_checked(self):
        with self.assertRaises((TypeCheckError, SignatureInferenceError)):
            compile_source('''
class Callable:
    def __init__(self):
        pass
    def __call__(self) -> str:
        return "text"
main()
def main() -> int:
    callback = Callable()
    return callback()
''')


if __name__ == '__main__':
    unittest.main()
