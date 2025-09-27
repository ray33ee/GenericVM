import ast
from hr import ast_to_hr, dump, Walker
from symbols import Symbols

at = ast.parse("""

x: int = 44

x = x + 3

y: float = 2.3

def thing(l: int) -> NoneType:
    return l

def do_something(a: int, b: int) -> int:
    return a + b + x

c: int = 44


""")

print(ast.dump(at))

h = ast_to_hr(at)

print(dump(h))

s = Symbols(h)


w = Walker()

w.walk(h)

print(f"Top: {s.top_level}")

for f, s in s.functions.items():
    print(f"{f}: {s}")


