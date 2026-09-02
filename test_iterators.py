import unittest

import interpreter
from compiler import compile_source
from typecheck import TypeCheckError


def run(source):
    return interpreter.Interpreter().run(compile_source(source))


class IteratorTests(unittest.TestCase):
    def test_string_iteration(self):
        self.assertEqual(run('''
def main() -> int:
    total: int = 0
    for character in "ABC":
        total = total + ord(character)
    return total

main()
'''), 198)

    def test_list_iteration_and_continue(self):
        self.assertEqual(run('''
def main() -> int:
    values: list[int] = [1, 2, 3, 4]
    total: int = 0
    for value in values:
        if value == 2:
            continue
        total = total + value
    return total

main()
'''), 8)

    def test_range_negative_step(self):
        self.assertEqual(run('''
def main() -> int:
    total: int = 0
    for value in range(5, 0, -2):
        total = total * 10 + value
    return total

main()
'''), 531)

    def test_range_dynamic_step_and_single_evaluation(self):
        self.assertEqual(run('''
def step() -> int:
    return -2

def main() -> int:
    total: int = 0
    for value in range(6, 0, step()):
        total = total * 10 + value
    return total

main()
'''), 642)

    def test_list_of_strings_iteration(self):
        self.assertEqual(run('''
def main() -> int:
    values: list[str] = ["a", "bc"]
    total: int = 0
    for value in values:
        total = total * 10 + len(value)
    return total

main()
'''), 12)

    def test_list_iteration_observes_live_length(self):
        self.assertEqual(run('''
def main() -> int:
    values: list[int] = [1]
    total: int = 0
    for value in values:
        total = total + value
        if value == 1:
            values.append(2)
    return total

main()
'''), 3)

    def test_custom_iterator_protocol(self):
        self.assertEqual(run('''
class Counter:
    current: int
    stop: int

    def __init__(self, stop: int):
        self.current = 0
        self.stop = stop

    def __iter__(self) -> Counter:
        return self

    def __bool__(self) -> bool:
        return self.current < self.stop

    def __next__(self) -> int:
        value: int = self.current
        self.current = self.current + 1
        return value

def main() -> int:
    total: int = 0
    for value in Counter(4):
        total = total * 10 + value
    return total

main()
'''), 123)

    def test_break_skips_else_and_natural_exhaustion_runs_else(self):
        self.assertEqual(run('''
def main() -> int:
    result: int = 0
    for value in [1, 2]:
        result = result + value
    else:
        result = result + 10
    for character in "xy":
        result = result + ord(character) * 0
        break
    else:
        result = result + 100
    return result

main()
'''), 13)

    def test_return_cleans_nested_iterator_state(self):
        self.assertEqual(run('''
def main() -> int:
    for left in [1, 2]:
        for right in "ab":
            return left + ord(right)
    return 0

main()
'''), 98)

    def test_return_from_for_else_does_not_double_drop_state(self):
        self.assertEqual(run('''
def main() -> int:
    values: list[int] = []
    for value in values:
        return value
    else:
        return 7
    return 0

main()
'''), 7)

    def test_invalid_iterator_bool_type_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "Invalid return type"):
            compile_source('''
class BadIterator:
    def __init__(self):
        pass

    def __iter__(self) -> BadIterator:
        return self

    def __bool__(self) -> int:
        return 1

    def __next__(self) -> int:
        return 1

def main():
    for value in BadIterator():
        print(value)
    return

main()
''')

    def test_non_iterable_is_rejected(self):
        with self.assertRaisesRegex(TypeCheckError, "not iterable"):
            compile_source('''
def main():
    for value in 3:
        print(value)
    return

main()
''')


if __name__ == "__main__":
    unittest.main()
