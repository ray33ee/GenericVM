"""Runnable GenericVM example using a declared target instruction set."""

import interpreter
from compiler import compile_source
from bytecode import bytecode

SOURCE = """

def copy_string(s, d):
    d[0] = len(s)

    for i in range(len(s)):
        d[i+1] = ord(s[i])

class PRNG:
    def __init__(self, s):
        self.seed = 0x6D2B79F5

        for i in range(100):
            self.seed += ord(s[i]) - i
            self.seed += self.seed << 7
            self.seed *= 0xC2B2AE35
            self.seed ^= self.seed >> 9
            self.seed += self.seed << 3

    def __next__(self):
        self.seed ^= self.seed << 13
        self.seed ^= self.seed >> 17
        self.seed *= 0x2C1B3C6D
        self.seed ^= self.seed << 5

        self.seed += 0x9E3779B9

        return self.seed

def contains(list, number, index):

    r = False

    for i in range(index):
        if number == list[i]:
            r = True

    return r

def from_hex(c):
    return (ord(c) & 0x0F) + (ord(c) >= ord('A')) * 9

main()

def main():
    PRIME = 65521

    #################### Get the username and password inputs
    print("Enter username: ")
    u = input(100)

    print("Enter password: ")
    k = input(100)

    #################### Move them to a 100 buffer
    username_buff = malloc(101)
    password_buff = malloc(101)

    copy_string(u, username_buff)
    copy_string(k, password_buff)

    username = cast_str(username_buff + 1)
    password = cast_str(password_buff + 1)

    rng = PRNG(username)

    x = malloc(10)
    y = malloc(10)

    poly = malloc(10)

    is_dashes = 1

    #################### password string validations
    for i in range(9):
        is_dashes &= password[i*5+4] == "-"

    is_hex = 1
    i = 0
    while i < 49:
        is_hex &= (password[i] >= "0" and password[i] <= "9") or (password[i] >= "A" and password[i] <= "F")

        i += 1

        if i % 5 == 4:
            i += 1

    #################### Get 10 (x, y) pairs ensuring x is unique and x, y are mod PRIME
    i = 0
    while i < 10:
        v = next(rng) % PRIME

        if contains(x, v, i):
            continue

        x[i] = v

        y[i] = next(rng) % PRIME

        i += 1

    #################### Get password coeffs
    for i in range(10):
        ind = i * 5
        c4 = from_hex(password[ind])
        c3 = from_hex(password[ind+1])
        c2 = from_hex(password[ind+2])
        c1 = from_hex(password[ind+3])

        coeff = c4 * 4096 + c3 * 256 + c2 * 16 + c1

        poly[i] = coeff

    fits = 1

    #################### For each (x, y) check it lies in poly
    for i in range(10):

        s = 0

        for j in range(10):

            s = (((s * x[i]) % 65521) + poly[j]) % 65521


        fits &= s == y[i]

    yes = "yes\\n"
    no = "no\\n"

    if is_dashes == 1 and is_hex == 1 and len(k) == 49 and fits == 1:
        print(yes)
    else:
        print(no)


"""


def main():
    # The supplied interpreter declares the exact IR operations it supports.
    target = interpreter.Interpreter.INSTRUCTION_SET

    # Compiling from source retains filenames, source lines, and columns for
    # readable errors if this program needs an instruction absent from target.
    result = compile_source(
        SOURCE,
        filename="example.gvm",
        instruction_set=target,
    )

    print("Instructions:")
    for index, instruction in enumerate(result):
        print(f"{index:03}: {instruction}")

    print()
    print("START PROGRAM")
    return_value = interpreter.Interpreter().run(result)
    print("END PROGRAM")
    print()
    print(f"Interpreter result: {return_value}")

    print(bytecode(result, instruction_set=target))

if __name__ == "__main__":
    main()
