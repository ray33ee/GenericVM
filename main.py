import ast
from hr import ast_to_hr, dump, Walker
from symbols import Symbols
from compiler import compile

at = ast.parse("""


thing(4, stuff(67))

def thing(l: int, k: int) -> int:
    return l + k

def stuff(l: int) -> int:
    return l


""")

print(ast.dump(at))

h = ast_to_hr(at)

print(dump(h))

s = Symbols(h)

c = compile(h, s, set(), set())

print(c)


