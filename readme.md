# About

GenericVM is a framework that can convert high level python like code into a low level assembly like code suitable for VMs. The language is highly customisable, allowing a range of complexities from simple script based languages, to evolved VMs with call stacks, floating arithmetic, conditional branches and much more!

# Customise

Functionality is customisable, allowing users to select and omit parts meaning they can taylor the language to their needs. Turn all but the bare mininimum functionality off for a simple script based language or enable all feautres for all the bells and whistles!

# Do

Users build the compiler by choosing their level of functionality, then they can use these compilers to convert the python-like code into an IR. Users can pass this IR directly into our provided interpreter, or they can specify a packing strategy to convert it into bytecode.

# Features

## Main function

If a main function is emabled, then all python-like code must contain a main function. the first instruction is to call main (or allocate space for globals) and after the call the EXIT function is used. If main feature is not selected, the code is translated in whatever order it appears, which could cause defined functions to execute out of order. Main can only be used if subroutines are selected. Rule of thumb is if subroutines are selected, so should a main function.

## Unconditional jump (JMP)

Simple branch to a particular label.

## Conditional jump (JT, JF)

Conditional branch, takes the value at the top of the op stack and uses it to branch or not. Either integer or floating arithmetic must be supported to use conditional jumps

## Integer arithmetic & comparison (ADD, SUB, etc.)

Essentially implemmentations of any python operator (+, -, /, etc.) for integer types. Users can specify exactly which operations are selected. If floating values are selected too, type annotations MUST be provided.

## Floating Arithmetic & comparison (FADD, FSUB, etc.)

Essentially implemmentations of any python operator (+, -, /, etc.) for floating types. Users can specify exactly which operations are selected. If integer values are selected too, type annotations MUST be provided.

## Conversions (FLOAT, INT, IBOOL, FBOOL)

If floating and integer types are both selected, conversions between the two are used.

If conditional jumps are used, BOOL is used to convert the operand to a boolean type.

## Subroutines (CALL, RET, ALLOC)

Allows subroutines. Compiler will handle calling convention, arguments and local variables.

If subroutines are disabled, functions can be used in the python=like code, but they will always be inlined

## Global variables

Implemented at the top of the call stack via ALLOC 

## Custom functions

Since each VM is different, users will want to create custom functions specific to their tasks. In the python-like code they are called in the same way as subroutines, but they do not require the call stack (and if constants are used they do not require the operand stack either) and are implemented by the interpreter directly.

## If expression

Equivalent to Cs ternary ? operator

# Levels

Targets are described by the IR instructions they implement, not by language
feature levels. The compiler determines the required combination from the
program it actually lowers and reports any unavailable instructions.

# Describing a target VM

GenericVM checks the instructions actually emitted for a program rather than
maintaining a separate list of language features.  This means two source
features which lower to the same IR naturally have the same VM requirements.

Use `InstructionSetBuilder` to describe a target.  Groups are convenience
macros only: they can overlap, do not imply dependencies, and can be refined
with individual inclusions and exclusions.

```python
import ir
from instruction_set import InstructionGroup, InstructionSetBuilder

target = (
    InstructionSetBuilder()
    .include_core()
    .include_group(InstructionGroup.LOCAL_STORAGE)
    .include_group(InstructionGroup.ARITHMETIC)
    .include_group(InstructionGroup.BRANCHING)
    .exclude(ir.Multiply)
    .include(ir.PrintInt)
    .build()
)
```

Compile source text directly when readable diagnostics are wanted:

```python
from compiler import compile_source

result = compile_source(
    source,
    filename="example.gvm",
    instruction_set=target,
)
```

The compiler first performs its normal lowering and then checks every emitted
IR instruction against `target`.  It does not change program lowering based on
the target.  If support is missing, one error reports all affected source
constructs with filenames, line text, carets, and the exact missing IR classes.

The lower-level API also accepts source information:

```python
import ast
import hr

module = hr.ast_to_hr(
    ast.parse(source, "example.gvm"),
    source=source,
    filename="example.gvm",
)
```

Without source text, diagnostics still contain AST line and column numbers but
cannot display the original line.

## Built-ins

Register a built-in once with its calling convention, type signature, and
opcode:

```python
from instruction_set import BuiltinDefinition, BuiltinKind
from typesystem import BuiltinSignature, INT

target = (
    InstructionSetBuilder()
    .include_core()
    .include_builtin(
        BuiltinDefinition(
            "random",
            BuiltinKind.FUNCTION,
            BuiltinSignature((INT,), INT, opcode=1010),
        )
    )
    .build()
)
```

`BuiltinKind.INSTRUCTION` is for immediate, constant-argument VM operations;
`BuiltinKind.FUNCTION` is for operand-stack-based operations.

The language intrinsic `input(length)` returns a newly allocated string. The
compiler emits `Malloc` for `length + 1` words and then the native `Input`
instruction (opcode `1005`) with the new character location and maximum length
on the operand stack in `[location, maximum_length]` order. `Input` records the actual entered length immediately
before the characters. The compiler preserves a separate copy of the allocated
string pointer because the native instruction consumes both operands and does
not push a result.

The low-level memory intrinsics `malloc(size)` and `free(location)` lower
directly to the native `Malloc` and `Free` instructions. `malloc` returns a
`ptr`; `free` consumes a `ptr` and returns `None`. Pointer indexing is raw
word access, so `p[index]` loads an integer and `p[index] = value` stores one.
Pointer arithmetic is word-based: `ptr + int`, `int + ptr`, and `ptr - int`
produce pointers, while subtracting two pointers produces their integer word
distance.

`cast_str(location)` is a compiler-only pointer cast from `ptr` to `str`. It
emits no conversion instruction and performs no validation or allocation; the
integer must already point to the first character of a valid GenericVM string,
with its length stored at `location - 1`.

`cast_int(text)` exposes a string pointer as an `int` without emitting a VM
instruction.

`cast_ptr(text)` casts a `str` back to its underlying `ptr`, also without
emitting a VM instruction. Together, `cast_str(ptr)` and `cast_ptr(str)` are
the direct pointer/string casts.

`bool` is implicitly usable wherever an `int` is expected. Mixed integer and
boolean arithmetic and bitwise operations produce `int`; no conversion
instruction is emitted. This conversion is one-way, so an arbitrary `int`
cannot be used where `bool` is required.

## Interpreter support and bytecode support

`Interpreter.INSTRUCTION_SET` describes exactly which core IR operations the
provided interpreter executes.  The interpreter validates a complete program
before starting, so it cannot fail halfway through due to a missing operation.

An interpreter may implement an IR operation which has no standard numeric
opcode.  Such a target can still compile and interpret programs.  To pack that
operation as bytecode, the VM designer must explicitly assign its opcode:

```python
target = (
    InstructionSetBuilder()
    .include(ir.Ternary)
    .opcode(ir.Ternary, 170)
    .build()
)
```

GenericVM does not choose new opcode numbers.  Duplicate, negative, and
non-integer opcode declarations are rejected, and bytecode generation raises
an error instead of silently dropping an instruction with no encoding.
