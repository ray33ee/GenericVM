import io
import unittest
from contextlib import redirect_stdout

import interpreter
import ir
from compiler import compile_source


def run_output(source):
    output = io.StringIO()
    with redirect_stdout(output):
        interpreter.Interpreter().run(compile_source(source))
    return output.getvalue()


def run_result(source):
    with redirect_stdout(io.StringIO()):
        return interpreter.Interpreter().run(compile_source(source))


class StringRuntimeTests(unittest.TestCase):
    def test_empty_list_infers_from_append_and_prints(self):
        self.assertEqual(run_output('''
main()
def main():
    values = []
    for i in range(10):
        values.append(i)
    print(values)
    return
'''), "[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]\n")

    def test_list_printing_composes_custom_and_automatic_class_strings(self):
        self.assertEqual(run_output('''
class Automatic:
    def __init__(self, value: int):
        self.value = value

class Custom:
    def __init__(self, value: int):
        self.value = value
    def __str__(self) -> str:
        return "custom"

main()
def main():
    automatic = [Automatic(1), Automatic(2)]
    custom = [Custom(3)]
    print(automatic)
    print(custom)
    return
'''), "[Automatic(1), Automatic(2)]\n[custom]\n")

    def test_list_printing_is_recursive(self):
        self.assertEqual(run_output('''
main()
def main():
    values = [[1, 2], [3]]
    print(values)
    return
'''), "[[1, 2], [3]]\n")

    def test_slice_syntax_supports_omitted_and_negative_bounds(self):
        self.assertEqual(run_output('''
main()
def main():
    text: str = "abcdef"
    print(text[1:4])
    print(text[:3])
    print(text[-3:])
    print(text[:])
    print(text[-20:99])
    return
'''), "bcd\nabc\ndef\nabcdef\nabcdef\n")

    def test_concat_links_only_its_runtime_dependency(self):
        instructions = compile_source('result = "left" + "right"\nresult\n')

        self.assertLess(len(instructions), 200)
        self.assertEqual(sum(isinstance(item, ir.LocalAlloc) for item in instructions), 1)
        self.assertEqual(sum(isinstance(item, ir.Call) for item in instructions), 1)

    def test_string_method_return_type_can_be_inferred(self):
        self.assertEqual(run_output('''
main()
def clean(text: str):
    return text.strip().lower()
def main():
    print(clean("  HeLLo  "))
    return
'''), "hello\n")

    def test_primitive_string_conversion(self):
        self.assertEqual(run_output('''
main()
def main():
    print(str("same"))
    print(str('Z'))
    print(str(True))
    print(str(False))
    print(str(0))
    print(str(12345))
    print(str(-907))
    return
'''), "same\nZ\nTrue\nFalse\n0\n12345\n-907\n")

    def test_primitive_int_and_bool_conversion(self):
        cases = (
            ("int(12)", 12),
            ("int(True)", 1),
            ("int(False)", 0),
            ('int("12345")', 12345),
            ('int("  -907\\t")', -907),
            ('int("+42")', 42),
            ("bool(0)", False),
            ("bool(-3)", True),
            ("bool(False)", False),
            ("bool(True)", True),
            ('bool("")', False),
            ('bool("text")', True),
        )
        for expression, expected in cases:
            with self.subTest(expression=expression):
                self.assertEqual(run_result(f'''
main()
def main():
    return {expression}
'''), expected)

    def test_primitive_int_string_conversion_uses_strtol_semantics(self):
        instructions = compile_source('''
main()
def main():
    return int("12x")
''')
        self.assertFalse(any(isinstance(op, ir.Assert) for op in instructions))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(interpreter.Interpreter().run(instructions), 12)

        self.assertEqual(run_result('''
main()
def main():
    return int("  -42 remainder")
'''), -42)
        self.assertEqual(run_result('''
main()
def main():
    return int("not a number")
'''), 0)

    def test_float_string_conversion(self):
        self.assertEqual(run_output('''
main()
def main():
    print(str(0.0))
    print(str(-0.0))
    print(str(1.5))
    print(str(12.0))
    print(str(123.456789))
    print(str(9.99999996))
    print(str(-0.25))
    print(str(0.000012345))
    print(str(0.00000012345))
    print(str(10000000000000000.0))
    print(str(1e309))
    print(str(-1e309))
    print(str(1e309 - 1e309))
    return
'''), "0.0\n0.0\n1.5\n12.0\n123.45679\n10.0\n-0.25\n1.2345e-5\n1.2345e-7\n1.0e+16\ninf\n-inf\nnan\n")

    def test_concat_repeat_and_comparisons(self):
        self.assertEqual(run_output('''
main()
def main():
    print("ab" + "cd")
    print("xy" * 3)
    print(2 * "z")
    print("abc" == "abc")
    print("abc" != "abd")
    print("abc" < "abd")
    print("abc" <= "abc")
    print("abd" > "abc")
    print("abc" >= "abc")
    return
'''), "abcd\nxyxyxy\nzz\nTrue\nTrue\nTrue\nTrue\nTrue\nTrue\n")

    def test_concat_accepts_char_operands(self):
        self.assertEqual(run_output('''
main()
def main():
    value: str = 'yes' + 'no'
    print(value[0] + "\\n")
    print('A' + "long")
    print("long" + 'Z')
    print('x' + 'y')
    return
'''), "y\n\nAlong\nlongZ\nxy\n")

    def test_search_and_prefix_methods(self):
        self.assertEqual(run_output('''
main()
def main():
    text: str = "bananana"
    print(text.find("na"))
    print(text.rfind("na"))
    print(text.count("na"))
    print(text.startswith("ban"))
    print(text.endswith("nana"))
    print(text.removeprefix("ban"))
    print(text.removesuffix("nana"))
    print(text.replace("na", "X"))
    print("nan" in text)
    print("z" not in text)
    print(text.substr(-20, 3))
    print(text.substr(3, 99))
    return
'''), "2\n6\n3\nTrue\nTrue\nanana\nbana\nbaXXX\nTrue\nTrue\nban\nanana\n")

    def test_ascii_case_trimming_and_classification(self):
        self.assertEqual(run_output('''
main()
def main():
    print("  hELLo  ".strip())
    print("  x".lstrip())
    print("x  ".rstrip())
    print("hELLo".lower())
    print("hELLo".upper())
    print("AbC!".swapcase())
    print("hELLO".capitalize())
    print("hello WORLD".title())
    print("abc".isalpha())
    print("a1".isalnum())
    print("123".isdigit())
    print("abc".islower())
    print("ABC".isupper())
    print(" \t".isspace())
    print("abc".isascii())
    print("abc!".isprintable())
    print("valid_1".isidentifier())
    print("ABC".casefold())
    return
'''), "hELLo\nx\nx\nhello\nHELLO\naBc!\nHello\nHello World\nTrue\nTrue\nTrue\nTrue\nTrue\nTrue\nTrue\nTrue\nTrue\nabc\n")

    def test_join_expandtabs_and_zfill(self):
        self.assertEqual(run_output('''
main()
def main():
    print(",".join(["a", "b", "c"]))
    print("a\tb".expandtabs())
    print("42".zfill(5))
    print("-42".zfill(5))
    return
'''), "a,b,c\na       b\n00042\n-0042\n")


if __name__ == "__main__":
    unittest.main()
