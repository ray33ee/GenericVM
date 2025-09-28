import ast
from hr import ast_to_hr, dump, Walker
from symbols import Symbols
from compiler import compile
import interpreter

at = ast.parse("""

x: int = 10
y: int = 100

if x > y:
    print(1)
else:
    print(2)

""")

print(ast.dump(at))

h = ast_to_hr(at)

print(dump(h))

s = Symbols(h)

c = compile(h, s, {"finish": 0, "print": 1}, {})


print(c)

i = interpreter.Interpreter()

i.run(c)



