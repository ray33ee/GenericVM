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
    # 'well done!'
    store(0, 3750207280)
    store(1, 3750207308)
    store(2, 3750207326)
    store(3, 3750207319)
    store(4, 3750207319)
    store(5, 3750207259)
    store(6, 3750207327)
    store(7, 3750207316)
    store(8, 3750207317)
    store(9, 3750207326)
    store(10, 3750207258)
    store(11, 3750207281)
    i: int = 0
    for i in range(12):
        store(i, load(i) ^ 3750207291)
    
    # 'incorrect'
    store(20, 3678240514)
    store(21, 3678240609)
    store(22, 3678240614)
    store(23, 3678240619)
    store(24, 3678240615)
    store(25, 3678240634)
    store(26, 3678240634)
    store(27, 3678240621)
    store(28, 3678240619)
    store(29, 3678240636)
    store(30, 3678240514)
    
    for i in range(11):
        store(i + 20, load(i + 20) ^ 3678240520)
    
    # Keys
    store(40, 74311208)
    store(41, 4088329160)
    store(42, 116435963)
    store(43, 1061628287)
    store(44, 1774249048)
    store(45, 4099353480)
    store(46, 2187536505)
    store(47, 758196411)
    store(48, 2534953666)
    store(49, 1670640078)
    store(50, 274567504)
    store(51, 2638127618)
    store(52, 668767862)
    store(53, 3994167464)
    store(54, 3863059995)
    store(55, 3687951999)
    store(56, 1240495154)
    
    # encrypted
    store(60, 4220656037)
    store(61, 206638083)
    store(62, 4178531453)
    store(63, 3233339103)
    store(64, 2520718231)
    store(65, 195613717)
    store(66, 2107430835)
    store(67, 3536770823)
    store(68, 1760013640)
    store(69, 2624327235)
    store(70, 4020399814)
    store(71, 1656839629)
    store(72, 3626199510)
    store(73, 300799774)
    store(74, 431907283)
    store(75, 607015346)
    store(76, 3054472180)
    
    # 'Please enter password: '
    store(120, 1415888280)
    store(121, 1415888351)
    store(122, 1415888355)
    store(123, 1415888362)
    store(124, 1415888366)
    store(125, 1415888380)
    store(126, 1415888362)
    store(127, 1415888303)
    store(128, 1415888362)
    store(129, 1415888353)
    store(130, 1415888379)
    store(131, 1415888362)
    store(132, 1415888381)
    store(133, 1415888303)
    store(134, 1415888383)
    store(135, 1415888366)
    store(136, 1415888380)
    store(137, 1415888380)
    store(138, 1415888376)
    store(139, 1415888352)
    store(140, 1415888381)
    store(141, 1415888363)
    store(142, 1415888309)
    store(143, 1415888303)
    
    for i in range(24):
        store(i + 120, load(i + 120) ^ 1415888271)
    
    prints(120)
    
    input(100, 100)
    
    length: int = load(100)
    
    if length != 17:
        prints(20)
        return 1
    
    for i in range(17):
        if ((0xFFFFFFFF - load(i+40)) ^ load(i+60)) != load(i+101):
            prints(20)
            return 1
    
    prints(0)
    return 0

""")

print(ast.dump(at))

h = ast_to_hr(at)

print(dump(h))

s = Symbols(h)

builtin_instructions = {"printi": (1, 1001), "prints": (1, 1002), "load": (1, 1003), "store": (2, 1004), "input": (2, 1005)}

c = compile(h, s, builtin_instructions, {})

print(c)

i = interpreter.Interpreter()

print(i.run(c))

b = bytecode(c, builtin_instructions)

print(b)

#with open("program.bin", "wb") as f:
#    for opcode, immediate in b:
#        f.write(struct.pack("<II", opcode, immediate))
