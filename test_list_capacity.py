import io
import sys
import unittest
from contextlib import redirect_stdout

from compiler import compile_source
from interpreter import Interpreter


class ListCapacityTests(unittest.TestCase):
    def run_list(self, body):
        program = compile_source('main()\ndef main():\n' + body)
        state = {}

        def capture(frame, event, arg):
            if frame.f_code is Interpreter.run.__code__ and event == 'return':
                state.update(heap=dict(frame.f_locals['heap']),
                             allocated=frame.f_locals['malloc_index'])
            return capture

        previous = sys.gettrace()
        with redirect_stdout(io.StringIO()):
            sys.settrace(capture)
            try:
                pointer = Interpreter().run(program)
            finally:
                sys.settrace(previous)
        heap = state['heap']
        return heap, pointer, state['allocated']

    def test_first_append_uses_initial_allocation(self):
        heap, descriptor, allocated = self.run_list(
            '    values = []\n    values.append(42)\n    return values\n')
        self.assertEqual((heap[descriptor + 1], heap[descriptor + 2]), (1, 10))
        self.assertEqual(allocated, 13)
        self.assertEqual(heap[heap[descriptor]], 42)

    def test_growth_doubles_and_preserves_contents(self):
        heap, descriptor, allocated = self.run_list(
            '    values = []\n    for i in range(21):\n        values.append(i)\n    return values\n')
        self.assertEqual((heap[descriptor + 1], heap[descriptor + 2]), (21, 40))
        self.assertEqual(allocated, 3 + 10 + 20 + 40)
        self.assertEqual([heap[heap[descriptor] + i] for i in range(21)], list(range(21)))

    def test_clear_and_pop_reuse_capacity(self):
        heap, descriptor, allocated = self.run_list(
            '    values = [1, 2]\n    values.pop()\n    values.clear()\n'
            '    values.append(42)\n    return values\n')
        self.assertEqual((heap[descriptor + 1], heap[descriptor + 2]), (1, 10))
        self.assertEqual(allocated, 13)
        self.assertEqual(heap[heap[descriptor]], 42)

    def test_empty_slice_has_initial_capacity(self):
        heap, descriptor, allocated = self.run_list(
            '    values = [1]\n    result = values[:0]\n    result.append(42)\n    return result\n')
        self.assertEqual((heap[descriptor + 1], heap[descriptor + 2]), (1, 10))
        self.assertEqual(allocated, 26)
        self.assertEqual(heap[heap[descriptor]], 42)

    def test_two_word_elements_reserve_twice_capacity(self):
        heap, descriptor, allocated = self.run_list(
            '    values = ["hi"]\n    return values\n')
        self.assertEqual((heap[descriptor + 1], heap[descriptor + 2]), (1, 10))
        self.assertEqual(allocated, 25)  # descriptor + 20 backing words + "hi"


if __name__ == '__main__':
    unittest.main()
