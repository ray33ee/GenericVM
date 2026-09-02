import io
import unittest
from contextlib import redirect_stdout

import interpreter
from compiler import compile_source
from typecheck import TypeCheckError


def run_output(source):
    output = io.StringIO()
    with redirect_stdout(output):
        interpreter.Interpreter().run(compile_source(source))
    return output.getvalue()


class OptionalArgumentTests(unittest.TestCase):
    def test_omitted_function_argument_is_expanded_at_call_site(self):
        self.assertEqual(run_output('''
main()
def add(value: int, amount: int = 2) -> int:
    return value + amount
def main():
    print(add(3))
    print(add(3, 4))
    return
'''), "5\n7\n")

    def test_constructor_defaults_are_supported(self):
        self.assertEqual(run_output('''
class Number:
    value: int
    def __init__(self, value: int = 2):
        self.value = value
main()
def main():
    number = Number()
    print(number.value)
    return
'''), "2\n")

    def test_print_end_defaults_to_newline_and_can_be_overridden(self):
        self.assertEqual(run_output('''
main()
def main():
    print("left", "")
    print("right")
    print()
    return
'''), "leftright\n\n")

    def test_print_end_must_be_a_string(self):
        with self.assertRaisesRegex(TypeCheckError, "print end argument must be str"):
            compile_source("print(1, 2)")


if __name__ == "__main__":
    unittest.main()
