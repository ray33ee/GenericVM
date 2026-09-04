import io
import unittest
from contextlib import redirect_stdout

from compiler import compile_source
from interpreter import Interpreter
from signature_inference import SignatureInferenceError
from typecheck import TypeCheckError


class MembershipTests(unittest.TestCase):
    def test_slice_membership_constrains_empty_list(self):
        self.assertEqual(self.run_source('''
main()
def main():
    values = []
    missing = "hello" not in values[:]
    values.append("hello")
    return missing + ("hello" in values[:])
'''), 2)

    def run_source(self, source):
        instructions = compile_source(source)
        with redirect_stdout(io.StringIO()):
            return Interpreter().run(instructions)

    def test_strings_and_lists(self):
        expressions = {
            '2 in [1, 2, 3]': 1,
            '4 in [1, 2, 3]': 0,
            '4 not in [1, 2, 3]': 1,
            '2 in []': 0,
            '[1, 2].__contains__(2)': 1,
            '1.5 in [2.5, 1.5]': 1,
            'True in [False, True]': 1,
            '"hello" in ["world", "hello"]': 1,
            '"other" in ["world", "hello"]': 0,
            '"a" in "cat"': 1,
            '"at" in "cat"': 1,
            '"" in "cat"': 1,
            '"z" not in "cat"': 1,
            '"cat".__contains__("at")': 1,
            '"cat".__contains__(chr(97))': 1,
        }
        for expression, expected in expressions.items():
            with self.subTest(expression=expression):
                self.assertEqual(self.run_source('main()\ndef main():\n    return ' + expression), expected)

    def test_class_protocol_infers_argument(self):
        self.assertEqual(self.run_source('''
class Box:
    def __init__(self, value):
        self.value = value
    def __contains__(self, value):
        return value == self.value
main()
def main():
    box = Box(3)
    return (3 in box) + (4 not in box) + box.__contains__(3)
'''), 3)

    def test_class_list_uses_element_equality(self):
        self.assertEqual(self.run_source('''
class Item:
    def __init__(self, value):
        self.value = value
    def __eq__(self, other: Item) -> bool:
        return self.value < other.value
main()
def main():
    return Item(3) in [Item(2)]
'''), 1)

    def test_invalid_membership(self):
        for expression in ('"text" in [1, 2]', '1 in "text"', '1 in 2', '[1].__contains__()', '[1].__contains__(1, 2)'):
            with self.subTest(expression=expression):
                with self.assertRaises((TypeCheckError, SignatureInferenceError)):
                    compile_source('main()\ndef main() -> bool:\n    return ' + expression)

    def test_operands_evaluated_once(self):
        self.assertEqual(self.run_source('''
class Factory:
    def __init__(self):
        self.calls = 0
    def needle(self) -> int:
        self.calls += 1
        return 3
    def values(self) -> list[int]:
        self.calls += 10
        return [1, 2, 3, 4]
main()
def main():
    factory = Factory()
    found = factory.needle() in factory.values()
    return factory.calls + found
'''), 12)

    def test_protocol_requires_boolean_result(self):
        with self.assertRaisesRegex(TypeCheckError, '__contains__ must return bool'):
            compile_source('''
class Box:
    def __init__(self):
        pass
    def __contains__(self, value: int) -> int:
        return value
main()
def main():
    return 1 in Box()
''')


if __name__ == '__main__':
    unittest.main()
