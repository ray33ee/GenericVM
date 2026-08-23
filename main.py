import ast
from hr import ast_to_hr, dump, Walker
from symbols import Symbols
from compiler import compile
import interpreter
from bytecode import bytecode
import struct

at = ast.parse("""



main()

def main() -> int:
    
    x: int = 10

    return 66 if x == 1 else -9
""")

print(ast.dump(at))

h = ast_to_hr(at)

print(dump(h))

s = Symbols(h)

builtin_instructions = {"printi": (1, 1001), "prints": (1, 1002), "input": (2, 1005)}

c = compile(h, s, builtin_instructions, {})

print("Instructions: " + str(c))

i = interpreter.Interpreter()

print("Interpreter result: " + str(i.run(c)))

b = bytecode(c, builtin_instructions)

print(b)

#with open("program.bin", "wb") as f:
#    for opcode, immediate in b:
#        f.write(struct.pack("<II", opcode, immediate))
