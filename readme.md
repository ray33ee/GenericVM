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

Strings are two-word values in `[pointer, length]` order. The pointer addresses
the first character directly; the heap contains character data only and has no
hidden length header. `PrintString` consumes both words.

String slicing supports `text[start:end]`, including omitted and negative
bounds. Bounds are clamped using Python-style rules. Slice steps are not yet
supported; `text[start:end:step]` is rejected during type checking.

Lists are one-word references to stable heap descriptors containing
`[data_pointer, length, capacity]`. The backing array is separate, so aliases
remain valid when `append` or `insert` grows it. Capacity doubles when full
(with a minimum allocation of four elements) and `pop` halves sparse backing
arrays when their length falls to one quarter of capacity. `clear` releases the
backing array. List slicing supports the same start/end forms as string slicing
and returns an independent dynamic list. These operations lower to existing
heap, stack, arithmetic, and branch instructions.

An unannotated empty literal begins type analysis as `list[?]`. Element-adding
operations such as `append` and `insert` constrain `?`; the constraint is shared
through ordinary list aliases. Inference reports an error at completion if the
unknown remains unresolved, and reports conflicting additions at their source.

List printing is compositional: the compiler emits list punctuation and applies
the normal typed printer to every element. Consequently any printable type also
has printable lists, recursively, including classes with explicit `__str__` or
`__repr__` methods and classes using the automatic field representation.

The language intrinsic `input(length)` allocates `length` character words and
then invokes the native `Input` instruction (opcode `1005`) with
`[location, maximum_length]` on the operand stack. `Input` leaves the location in
place, writes the entered characters, and replaces the maximum length with the
actual entered length, producing the normal `[pointer, length]` string directly.

The low-level memory intrinsics `malloc(size)` and `free(location)` lower
directly to the native `Malloc` and `Free` instructions. `malloc` returns a
`ptr`; `free` consumes a `ptr` and returns `None`. Pointer indexing is raw
word access, so `p[index]` loads an integer and `p[index] = value` stores one.
Pointer arithmetic is word-based: `ptr + int`, `int + ptr`, and `ptr - int`
produce pointers, while subtracting two pointers produces their integer word
distance.

`cast_str(location, length)` constructs a string value from a pointer and an
integer length. It emits no conversion instruction and performs no validation
or allocation.

`cast_int(text)` exposes the pointer word of a string as an `int` without
emitting a VM instruction.

`cast_ptr(text)` extracts a string's underlying `ptr`, also without emitting a
VM instruction. Together, `cast_str(ptr, len)` and `cast_ptr(str)` are
the direct pointer/string casts.

For low-level runtime code, `cast_int(ptr)` and `cast_ptr(int)` also reinterpret
raw pointer words without emitting conversion instructions.

`bool` is implicitly usable wherever an `int` is expected. Mixed integer and
boolean arithmetic and bitwise operations produce `int`; no conversion
instruction is emitted. This conversion is one-way, so an arbitrary `int`
cannot be used where `bool` is required.

The explicit `int()` and `bool()` conversions support the `int`, `bool`, and
`str` primitives. `int(str)` follows base-10 `strtol`-style parsing: it skips
leading ASCII whitespace, accepts an optional sign, consumes digits up to the
first non-digit, and returns zero if it consumes no digits. `bool(int)` tests
against zero, and `bool(str)` tests whether the string length is nonzero. These
conversions are composed from existing instructions and source-level runtime
functions; no conversion-specific core VM instruction is required.

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
# Iteration

`for` loops support `range`, strings, typed lists, and user-defined iterable
classes. Range, string, and list loops keep their iteration state directly on
the VM operand stack; they do not allocate iterator wrapper objects. This is
compiler lowering composed from the existing VM instruction set.

User-defined iterables use the following protocol:

```python
class Counter:
    def __iter__(self) -> Counter:
        return self

    def __bool__(self) -> bool:
        return self.current < self.stop

    def __next__(self) -> int:
        value: int = self.current
        self.current = self.current + 1
        return value
```

In GenericVM, iterator truthiness means that `__next__` may safely be called.
This deliberately differs from Python's exception-based `StopIteration`
protocol. A generated loop checks `__bool__` before every call to `__next__`.

String iteration yields `char`; `list[T]` iteration yields `T`; and range
iteration yields `int`. Loop `break`, `continue`, `return`, and `else` paths
clean up their retained operand-stack state, including in nested loops.

Built-in list and string iteration is currently available through `for`.
First-class `iter(list_value)` and `iter(string_value)` objects are not yet
provided.
