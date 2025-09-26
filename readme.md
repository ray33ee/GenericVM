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

## Operand stack

Integer arithmetic, float arithmetic and subroutines all use the operand stack, so all but the most basic compilers will need this. 

## Memory blocks (mem[x], mem1[y], etc. via LOAD and STORE)

Allow addressing of arbitrary sections of memory initialised by the interpreter. Support read and writing words. This will allow pointer-like behaviour.

## Custom functions

Since each Vm is different, users will want to create custom functions specific to their tasks. In the python-like code they are called in the same way as subroutines, but they do not require the call stack (and if constants are used they do not require the operand stack either) and are implemented by the interpreter directly.

## If expression

Equivalent to Cs ternary ? operator

## Assertions

# Levels

Some features rely on others. For example, conditional jumps require either integer or floating math to be allowed. The builder will raise an exception if an invalid configuration is specified, but once a valid specification is created the user no longer need worry about exceptions.