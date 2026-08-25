"""Runnable GenericVM example using a declared target instruction set."""

import interpreter
from compiler import compile_source


SOURCE = """


main()

def main():
    
    y = str(1.2)
    
    print(y + "\\n")
    
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
