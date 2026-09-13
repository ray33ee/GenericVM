"""Broad, self-checking GenericVM smoke program.

Running this module compiles and executes the program.
"""

import interpreter
from bytecode import bytecode
from compiler import compile_source
from instruction_set import InstructionSetBuilder
from typesystem import BuiltinSignature, INT


SOURCE = r'''
GLOBAL_BONUS = 3

class Counter:
    def __init__(self, start: int, stop: int):
        self.current = start
        self.stop = stop
    def __iter__(self) -> Counter:
        return self
    def __bool__(self) -> bool:
        return self.current < self.stop
    def __next__(self) -> int:
        value: int = self.current
        self.current += 1
        return value

class Number:
    def __init__(self, value: int = 2):
        self.value = value
    def __call__(self, amount: int = 1) -> int:
        return self.value + amount
    def __add__(self, other: int) -> Number:
        return Number(self.value + other)
    def __radd__(self, other: int) -> Number:
        return Number(other + self.value)
    def __neg__(self) -> Number:
        return Number(-self.value)
    def __eq__(self, other: Number) -> bool:
        return self.value == other.value
    def __contains__(self, value: int) -> bool:
        return value == self.value
    def __str__(self) -> str:
        return "number"

def factorial(value: int) -> int:
    if value <= 1:
        return 1
    return value * factorial(value - 1)

def combine(left: int, right: int = 4) -> tuple[int, int]:
    return left + right, left * right

def add_pair(left: int, right: int) -> int:
    return left + right

def main() -> int:
    # Arithmetic, comparisons, logic, bitwise operations and conditionals.
    if not factorial(5) == 120: return 1
    if not 17 % 5 == 2: return 2
    if not -7 + +10 == 3: return 3
    if not ((6 & 3) == 2 and (6 | 3) == 7 and (6 ^ 3) == 5): return 4
    if not ((1 << 4) == 16 and (16 >> 2) == 4 and ~0 == -1): return 5
    if not (1 < 2 and 2 <= 2 and 3 != 4 and not False): return 6
    if not (10 if True else 20) == 10: return 8

    # Tuples, unpacking, starred calls, defaults and global access.
    pair = combine(GLOBAL_BONUS)
    first, second = pair
    if not (first == 7 and second == 12): return 9
    if not add_pair(*pair) == 19: return 10
    nested = (1, (2, 3), "four")
    if not (nested[1][1] == 3 and nested[-1] == "four"): return 11

    # Dynamic lists, aliases, indexing, slicing, mutation and membership.
    values = []
    for value in range(6):
        values.append(value * value)
    alias = values
    alias.insert(2, 99)
    if not (len(values) == 7 and values[2] == 99): return 12
    if not values[6] == 25: return 13
    middle = values[1:4]
    if not (len(middle) == 3 and middle[0] == 1 and middle[2] == 4): return 14
    if not (16 in values and 100 not in values): return 15
    copied = values[:]
    copied.clear()
    if not (len(copied) == 0 and len(values) == 7): return 16

    # Strings, characters, slicing, methods, conversions and iteration.
    text = "  HeLLo-world  "
    clean = text.strip().lower()
    if not clean == "hello-world": return 17
    if not (clean.startswith("hello") and clean.endswith("world")): return 18
    if not (clean.find("lo") == 3 and clean.count("l") == 3): return 19
    if not clean.replace("world", "vm") == "hello-vm": return 20
    if not (clean[1:5] == "ello" and clean[-5:] == "world"): return 21
    if not ("lo" in clean and "z" not in clean): return 22
    if not (ord(chr(65)) == 65 and str(123) == "123"): return 23
    if not int("  -42 trailing") == -42: return 24
    if not bool("xy"): return 25
    if bool(0): return 26
    character_total: int = 0
    for character in "ABC":
        character_total += ord(character)
    if not character_total == 198: return 27

    # Classes, fields, methods, operators, callables and protocols.
    number = Number(7)
    number.value += 1
    if not (number() == 9 and number(4) == 12): return 28
    if not ((number + 2).value == 10 and (3 + number).value == 11): return 29
    if not (-number).value == -8: return 30
    if not Number(5) == Number(5): return 31
    if not 4 in Number(4): return 32
    if not str(number) == "number": return 33

    iterator_total: int = 0
    for item in Counter(2, 7):
        if item == 3:
            continue
        if item == 6:
            break
        iterator_total += item
    if not iterator_total == 11: return 34

    # While/else and raw pointer allocation, access, arithmetic and casts.
    countdown: int = 3
    while countdown > 0:
        countdown -= 1
    else:
        countdown = 42
    if not countdown == 42: return 35

    location: ptr = malloc(3)
    location[0] = 10
    (location + 1)[0] = 20
    location[2] = 12
    if not location[0] + location[1] + location[2] == 42: return 36
    if not (location + 2) - location == 2: return 37
    pointer_text: str = cast_str(location, 0)
    if not cast_int(cast_ptr(pointer_text)) == cast_int(location): return 38
    free(location)
    print(GLOBAL_BONUS)
    print(chr(0x35))
    print("PASS")
    return 0

main()
'''

# Todo: Implement the advance rng & rng seed code

SOURCE = '''

@macro
def advance_rng(state):
    state += 0x9E3779B9
    state ^= state >> 16
    state *= 0x21F0AAAD
    state ^= state >> 15
    state *= 0x735A2D97
    state ^= state >> 15
    
    if state == 0:
        state = 0x6E4B91D7
    
    return state

USERNAME_MAX_LEN = 20
PASSWORD_MAX_LEN = 1000

B = time()

B = advance_rng(B) # RNG thingy

print("Please enter username: ", "")
u = input(USERNAME_MAX_LEN)

print("Please enter password: ", "")
p = input(PASSWORD_MAX_LEN)

print("verifying...")

C = 0

username = cast_str(cast_ptr(u), USERNAME_MAX_LEN)

A = 0xFFFFFFFF

password = cast_str(cast_ptr(p), PASSWORD_MAX_LEN)

SBOX = [
    0x00, 0x6B, 0xE6, 0x4E, 0xB5, 0x9C, 0xEC, 0xC3, 0x57, 0xFE, 0x09, 0x24, 0x98, 0x45, 0xBD, 0x85,
    0xEF, 0x19, 0x7B, 0x7A, 0xC2, 0x05, 0xF8, 0x11, 0x43, 0x64, 0x9F, 0x83, 0xB1, 0x3E, 0xEA, 0x93,
    0xA4, 0x92, 0xA3, 0x29, 0x96, 0x63, 0x4B, 0xE3, 0x06, 0x8E, 0xD9, 0xC6, 0xD4, 0x48, 0x9A, 0x02,
    0x72, 0x21, 0x60, 0x07, 0x36, 0x04, 0x40, 0xC9, 0x87, 0x9B, 0x7F, 0xCC, 0xD7, 0x3F, 0xF2, 0x25,
    0x42, 0xE5, 0x34, 0x10, 0x95, 0x7D, 0x5E, 0x99, 0x1B, 0x84, 0xD3, 0x8B, 0x35, 0x30, 0x53, 0xD6,
    0xFD, 0x61, 0x1D, 0x65, 0x5D, 0x0D, 0xE9, 0xA1, 0x7E, 0xCD, 0x82, 0xDE, 0x16, 0x8C, 0x1F, 0x2C,
    0x39, 0xDB, 0x0B, 0x3D, 0x17, 0x03, 0x68, 0xED, 0x8A, 0x6C, 0x2F, 0x97, 0xB4, 0x9E, 0xF6, 0xB2,
    0x1A, 0x6F, 0x75, 0x08, 0x88, 0x4D, 0xF0, 0x28, 0x49, 0xAB, 0x38, 0xF3, 0x74, 0x55, 0x37, 0x20,
    0x23, 0x44, 0xC8, 0x2D, 0xDC, 0xDA, 0xC4, 0x13, 0x8D, 0x8F, 0xF4, 0xAA, 0xE4, 0x7C, 0x80, 0xAF,
    0xB9, 0xE2, 0xD0, 0x46, 0x01, 0xA2, 0x62, 0x94, 0xD8, 0x41, 0xCA, 0x32, 0xEB, 0x69, 0x1E, 0xB6,
    0xE1, 0x73, 0x81, 0x3B, 0x3A, 0xCF, 0x0F, 0x0A, 0x51, 0xD2, 0x26, 0xC0, 0x67, 0x4F, 0x5C, 0xB3,
    0xAD, 0x1C, 0xFB, 0x89, 0x9D, 0x4C, 0x70, 0xCE, 0xA5, 0x6E, 0xA0, 0xDF, 0xBA, 0x2B, 0x5A, 0x56,
    0xE0, 0xBF, 0x27, 0xF7, 0xA9, 0x5F, 0x0E, 0x59, 0xBE, 0x58, 0xE7, 0x0C, 0x22, 0xD1, 0x5B, 0xF9,
    0x31, 0xC7, 0x86, 0xEE, 0xC5, 0xFA, 0xB0, 0x2A, 0xCB, 0x3C, 0xA6, 0xA8, 0x78, 0x12, 0xB7, 0xD5,
    0x79, 0xBC, 0x76, 0x14, 0x54, 0x47, 0x6A, 0x2E, 0x4A, 0xC1, 0x6D, 0x15, 0x77, 0xF1, 0xE8, 0x18,
    0x91, 0xAC, 0x52, 0xDD, 0x66, 0x50, 0x90, 0x33, 0xAE, 0xB8, 0xBB, 0x71, 0xF5, 0xFC, 0xA7, 0xFF,
]

@macro
def sbox_bytes(value):
    result = 0

    for shift in range(0, 32, 8):
        byte = (value >> shift) & 0xFF
        result |= SBOX[byte] << shift

    return result

@macro
def permute_bits(value):
    value &= 0xFFFFFFFF
    result = 0

    for bit in range(32):
        new_position = (bit * 5 + 3) % 32
        result |= ((value >> bit) & 1) << new_position

    return result


# Use as value = branchless_choose(condition, value, new)
# Sets value to new if condition is true, keeps value as is if condition is false
@macro
def branchless_choose(condition, value, new):
    return value ^ ((value ^ new) * condition)

scratch = malloc(USERNAME_MAX_LEN)
verification = malloc(USERNAME_MAX_LEN)

for i in range(USERNAME_MAX_LEN):
    scratch[i] = ord(username[i])
    verification[i] = 0xFFFFFFFF



for ch in password:
    
    o = ord(ch)
    
    C += o * 0x06653f41 == 2894040579 # o == ord('C')
    
    B = branchless_choose(-o ^ 0xE660F183 == 429854270, B, advance_rng(B)) # o == ord('C')
    
    A = branchless_choose(((o << 13) | (o >> 19)) == 729088, A, sbox_bytes(A)) # o == ord('Y')
    
    A = branchless_choose(o * 0x34311bf5 + 0x3503a2b7 == 2387048153, A, permute_bits(A)) # o == ord('Z')
    
    A = branchless_choose((((o ^ (o << 9)) ^ ((o ^ (o << 9)) << 11)) ^ 0x6DFEF294) == 1752990412, A, A ^ (A << 16)) # o == ord('X')
    
    A = branchless_choose(~(o + 0xb7fe38d2) == 1208076015, A, scratch[C]) # o == ord('>')
    
    scratch[C] = branchless_choose((o * 0x4d96a101) ^ 0xb3f0fc8b == 2629648567, scratch[C], A) # o == ord('<')
    
    verification[C] = branchless_choose(
        bool((0xd60912a2 - o == 3590918732) * (verification[C] == 0xFFFFFFFF)),  # o == ord('V')
        verification[C],
        int(scratch[C] == B)
    )

verify = 0

for j in range(USERNAME_MAX_LEN):
    verify += verification[j] != 1

results = ["incorrect", "correct"]

print(results[verify == 0])

'''

def main():
    target = (
        InstructionSetBuilder()
        .include(*interpreter.Interpreter.INSTRUCTION_SET.instructions)
        .include_builtin_function("time", BuiltinSignature((), INT, opcode=1010))
        .build()
    )
    program = compile_source(SOURCE, filename="smoke_test.gvm", instruction_set=target)
    raw = bytecode(program, instruction_set=target)
    print(raw)
    call_count = sum(first == 40 for first, _ in raw)
    jump_count = sum(first == 20 or first == 21 or first == 22 for first, _ in raw)
    #result = interpreter.Interpreter().run(program)
    #if result != 0:
    #    raise RuntimeError(f"Smoke program returned {result}, expected 0")

    print(f"Program has {call_count} counts and {jump_count} jumps")

if __name__ == "__main__":
    main()
