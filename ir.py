
class Instruction:
    def __repr__(self):
        s = [type(self).__name__, "("]
        if hasattr(self, "OPCODE"):
            s.append("OPCODE=")
            s.append(str(self.OPCODE))
            s.append(", ")
        for i, (attr, value) in enumerate(vars(self).items()):
            s.append(attr)
            s.append("=")
            s.append(str(value))
            if i != len(vars(self)) - 1:
                s.append(", ")
        s.append(")")
        return "".join(s)

###### Unified-memory stack instructions

# Push the word at physical address BP - offset.
class StackPushVariable(Instruction):

    OPCODE = 0

    def __init__(self, offset: int):
        self.offset = offset

# Pop into the word at physical address BP - offset.
class StackPopVariable(Instruction):

    OPCODE = 1

    def __init__(self, offset: int):
        self.offset = offset

# Push a global word at memory_size - 1 - index.
class StackPushGlobal(Instruction):

    OPCODE = 2

    def __init__(self, index: int):
        self.index = index


# Pop into the global word at memory_size - 1 - index.
class StackPopGlobal(Instruction):

    OPCODE = 3

    def __init__(self, index: int):
        self.index = index

# Push a literal onto the unified stack
class StackPushLiteral(Instruction):

    OPCODE = 4

    def __init__(self, value):
        self.value = value

# Opcode 5 is intentionally retired with the former operand-to-call-stack
# transfer instruction.

# Opcodes 6 and 7 are intentionally retired with the separate global-access
# instructions.


###### Jumps

# Unconditional jump
class Jump(Instruction):

    OPCODE = 20

    def __init__(self, location):
        self.location = location

# Jump if the top stack word is non-zero (and pop it)
class JumpIfTrue(Instruction):

    OPCODE = 21

    def __init__(self, location):
        self.location = location

# Jump if the top stack word is zero (and pop it)
class JumpIfFalse(Instruction):

    OPCODE = 22

    def __init__(self, location):
        self.location = location


###### Conversion

# Convert the top stack word from int to float
class IntToFloat(Instruction):
    OPCODE = 30
    pass

# Convert the top stack word from float to int
class ConvertFloatToInt(Instruction):
    pass


###### Subroutines

# Push the return address and previous BP, set BP to SP, and jump.
class Call(Instruction):

    OPCODE = 40

    def __init__(self, location):
        self.location = location

# Pop the frame and arguments, then return to its link address. Results have
# already been written into caller-owned slots below the arguments.
class Return(Instruction):

    OPCODE = 41

    def __init__(self, arg_count):
        self.arg_count = arg_count

# Allocate zero-initialized machine words on the stack
class Alloc(Instruction):

    OPCODE = 42

    def __init__(self, variable_count: int):
        self.variable_count = variable_count


###### Comparison - Pop two stack words and push 0 for false or 1 for true


class Equal(Instruction):

    OPCODE = 60

    pass

class NotEqual(Instruction):

    OPCODE = 61

    pass

class LessThan(Instruction):

    OPCODE = 62

    pass

class GreaterThan(Instruction):

    OPCODE = 63

    pass

class LessThanEqualTo(Instruction):

    OPCODE = 64

    pass

class GreaterThanEqualTo(Instruction):

    OPCODE = 65

    pass


###### Built ins

# Allows built-in instructions that can be called in code but executed by VM.
# Built-in instructions pass arguments as immediates and do not use the stack.
class BuiltInInstruction(Instruction):
    def __init__(self, name, args):
        self.name = name
        self.args = args


# Allows built-in functions that can be called in code but executed by VM.
# Built-in functions consume arguments and produce results directly on the
# unified stack; they do not create call frames.
# It is down to the VM implementor to ensure they remove the correct number of items from the stack
class BuiltInFunction(Instruction):
    def __init__(self, name, args):
        self.name = name
        self.args = args



###### Binary ops - Each instruction pops two values, operates on them, then pushes the result

class IAdd(Instruction):

    OPCODE = 100

    pass

class ISub(Instruction):

    OPCODE = 101

    pass

class IMultiply(Instruction):

    OPCODE = 102

    pass

class IMod(Instruction):

    OPCODE = 113

    pass

class And(Instruction):

    OPCODE = 103

    pass

class Or(Instruction):

    OPCODE = 104

    pass

class Xor(Instruction):

    OPCODE = 105

    pass

class ShiftLeft(Instruction):

    OPCODE = 106

    pass

class ShiftRight(Instruction):

    OPCODE = 107

    pass

class LogicalAnd(Instruction):

    OPCODE = 108

    pass

class LogicalOr(Instruction):

    OPCODE = 109

    pass


###### Unary ops - Each instruction pops a value, operates on it, then pushes the result

class IUnaryNegative(Instruction):

    OPCODE = 150

    pass

class IUnaryPositive(Instruction):

    OPCODE = 151

    pass

class OnesComplement(Instruction):

    OPCODE = 152

    pass

class LogicalNot(Instruction):

    OPCODE = 153

    pass


class FAdd(Instruction):
    OPCODE = 110
    pass


class FSub(Instruction):
    OPCODE = 111
    pass


class FMultiply(Instruction):
    OPCODE = 112
    pass


class FUnaryNegative(Instruction):
    OPCODE = 154
    pass


class FUnaryPositive(Instruction):
    OPCODE = 155
    pass


class PrintInt(Instruction):
    """Print one integer-like VM word."""

    OPCODE = 162


class PrintString(Instruction):
    """Consume a string as ``[pointer, length]`` and print its characters."""

    OPCODE = 163


class PrintBool(Instruction):
    """Print one boolean VM word as True or False."""

    OPCODE = 164


class PrintChar(Instruction):
    """Print one Unicode character code."""

    OPCODE = 165


class PrintFloat(Instruction):
    """Print one floating-point value."""

    OPCODE = 166

###### Ternary

# IfExp, C ternary instruction.
class Ternary(Instruction):
    pass

###### Unified memory

class Store(Instruction):
    """Store a word through an address in the VM's shared memory space."""
    OPCODE = 1004


class Load(Instruction):
    """Load a word through an address in the VM's shared memory space."""
    OPCODE = 1003

class Malloc(Instruction):
    """Target-specific allocation returning a shared-memory address."""
    OPCODE = 1006


class Free(Instruction):
    """Target-specific release of a shared-memory address."""
    OPCODE = 1007


class Input(Instruction):
    """Replace [location, maximum_length] with [location, actual_length]."""

    OPCODE = 1005


###### Stack manip

class Dupe(Instruction):
    OPCODE = 200


class Drop(Instruction):
    """Discard a compile-time number of words from the unified stack."""

    OPCODE = 201

    def __init__(self, count: int):
        self.count = count


class Roll(Instruction):
    """Move the word at a compile-time depth to the top of the unified stack."""

    OPCODE = 202

    def __init__(self, depth: int):
        self.depth = depth

