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


class StringRuntimeTests(unittest.TestCase):
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
'''), "hello")

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
'''), "sameZTrueFalse012345-907")

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
'''), "0.00.01.512.0123.4567910.0-0.251.2345e-51.2345e-71.0e+16inf-infnan")

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
'''), "abcdxyxyxyzzTrueTrueTrueTrueTrueTrue")

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
'''), "y\nAlonglongZxy")

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
'''), "263TrueTrueananabanabaXXXTrueTruebananana")

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
'''), "hELLoxxhelloHELLOaBc!HelloHello WorldTrueTrueTrueTrueTrueTrueTrueTrueTrueabc")

    def test_join_expandtabs_and_zfill(self):
        self.assertEqual(run_output('''
main()
def main():
    print(",".join(["a", "b", "c"]))
    print("a\tb".expandtabs())
    print("42".zfill(5))
    print("-42".zfill(5))
    return
'''), "a,b,ca       b00042-0042")


if __name__ == "__main__":
    unittest.main()
