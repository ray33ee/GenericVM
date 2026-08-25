
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

###### Stack instructions

# Push the value of a local variable onto the op stack
class OpStackPushLocal(Instruction):

    OPCODE = 0

    def __init__(self, offset: int):
        self.offset = offset

# Pop the top of the op stack into a local variable
class OpStackPopLocal(Instruction):

    OPCODE = 1

    def __init__(self, offset: int):
        self.offset = offset

# Push the value of an argument variable onto the op stack
class OpStackPushArg(Instruction):

    OPCODE = 2

    def __init__(self, offset: int):
        self.offset = offset

# Pop the top of the op stack into an argument variable
class OpStackPopArg(Instruction):

    OPCODE = 3

    def __init__(self, offset: int):
        self.offset = offset

# Push a literal onto the op stack
class OpStackPushLiteral(Instruction):

    OPCODE = 4

    def __init__(self, value):
        self.value = value

# Pop a value off the op stack and push it into the call stack
class OpStackPopToCallStack(Instruction):

    OPCODE = 5

    pass

# Push the value of a global variable onto the op stack
class OpStackPushGlobal(Instruction):

    OPCODE = 6

    def __init__(self, offset: int):
        self.offset = offset

# Pop the top of the op stack into the global variable
class OpStackPopGlobal(Instruction):

    OPCODE = 7

    def __init__(self, offset: int):
        self.offset = offset


###### Jumps

# Unconditional jump
class Jump(Instruction):

    OPCODE = 20

    def __init__(self, location):
        self.location = location

# Jump if top of op stack is non-zero (pops op stack)
class JumpIfTrue(Instruction):

    OPCODE = 21

    def __init__(self, location):
        self.location = location

# Jump if top of op stack is zero (pops op stack)
class JumpIfFalse(Instruction):

    OPCODE = 22

    def __init__(self, location):
        self.location = location


###### Conversion

# Pop the int on the top of the op stack, convert to float, push it back on
class IntToFloat(Instruction):
    OPCODE = 30
    pass

# Pop the float on the top of the op stack, convert to int, push it back on
class ConvertFloatToInt(Instruction):
    pass


###### Subroutines

# Make a function call. Stores return address on call stack
class Call(Instruction):

    OPCODE = 40

    def __init__(self, location):
        self.location = location

# Return to the link address stored in the call stack
class Return(Instruction):

    OPCODE = 41

    def __init__(self, arg_count):
        self.arg_count = arg_count

# Allocate machine words for local variables
class LocalAlloc(Instruction):

    OPCODE = 42

    def __init__(self, variable_count: int):
        self.variable_count = variable_count

# Allocate machine words for global variables
class GlobalAlloc(Instruction):

    OPCODE = 43

    def __init__(self, variable_count: int):
        self.variable_count = variable_count


###### Comparison - Pop two values off the op stack, compare them, then push the result. 0 for false and 1 for true


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
# Built-in instructions pass arguments as immediates and DO NOT use the op stack OR the call stack (as a result they must pass constants)
class BuiltInInstruction(Instruction):
    def __init__(self, name, args):
        self.name = name
        self.args = args


# Allows built-in functions that can be called in code but executed by VM.
# Built-in functions pass arguments on the op stack and DO NOT use the call stack
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
    """Print one heap string."""

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

###### Heap

class Store(Instruction):
    pass


class Load(Instruction):
    pass

###### Memory

class Malloc(Instruction):
    pass


class Free(Instruction):
    pass


###### Stack manip

class Dupe(Instruction):
    pass


class Drop(Instruction):
    """Discard a compile-time number of words from the operand stack."""

    OPCODE = 201

    def __init__(self, count: int):
        self.count = count


class Roll(Instruction):
    """Move the word at a compile-time depth to the top of the operand stack."""

    OPCODE = 202

    def __init__(self, depth: int):
        self.depth = depth




###### Misc

# If the top of the op stack is non-zero stop program
class Assert(Instruction):
    pass
