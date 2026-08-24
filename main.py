"""Runnable GenericVM example using a declared target instruction set."""

import interpreter
from compiler import compile_source


SOURCE = """
class PRNG:
    def __init__(self, s: str):
        self.seed = 0x811C9DC5

        for i in range(len(s)):
            self.seed ^= ord(s[i])
            self.seed = (self.seed * 0x01000193) & 0xFFFFFFFF

    def __next__(self):
        self.seed = (self.seed + 0x9E3779B9) & 0xFFFFFFFF

        x = self.seed
        x = ((x ^ (x >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
        x = ((x ^ (x >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
        return x ^ (x >> 16)


main()

def main():
    p = PRNG("hello!")
    print(f"{p.seed}\\n")
    print(f"{next(p)}\\n")
    print(f"{next(p)}\\n")
    print(f"{next(p)}\\n")
    print(f"{next(p)}\\n")
    return
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

if __name__ == "__main__":
    main()
