
class Instruction:
    def __repr__(self):
        s = [type(self).__name__, "("]
        for attr, value in vars(self).items():
            s.append(attr)
            s.append("=")
            s.append(str(value))
        s.append(")")
        return "".join(s)

###### Stack instructions

# Push the value of a local variable onto the op stack
class OpStackPushLocal(Instruction):
    def __init__(self, offset: int):
        self.offset = offset

# Pop the top of the op stack into a local variable
class OpStackPopLocal(Instruction):
    def __init__(self, offset: int):
        self.offset = offset

# Push the value of an argument variable onto the op stack
class OpStackPushArg(Instruction):
    def __init__(self, offset: int):
        self.offset = offset

# Pop the top of the op stack into an argument variable
class OpStackPopArg(Instruction):
    def __init__(self, offset: int):
        self.offset = offset

# Push a literal onto the op stack
class OpStackPushLiteral(Instruction):
    def __init__(self, value):
        self.value = value

# Pop a value off the op stack and push it into the call stack
class OpStackPopToCallStack(Instruction):
    pass

# Push the value of a global variable onto the op stack
class OpStackPushGlobal(Instruction):
    def __init__(self, offset: int):
        self.offset = offset

# Pop the top of the op stack into the global variable
class OpStackPopGlobal(Instruction):
    def __init__(self, offset: int):
        self.offset = offset


###### Jumps

# Unconditional jump
class Jump(Instruction):
    pass

# Jump if top of op stack is non-zero (pops op stack)
class JumpIfTrue(Instruction):
    pass

# Jump if top of op stack is zero (pops op stack)
class JumpIfFalse(Instruction):
    pass


###### Conversion

# Pop the int on the top of the op stack, convert to float, push it back on
class ConvertIntToFloat(Instruction):
    pass

# Pop the float on the top of the op stack, convert to int, push it back on
class ConvertFloatToInt(Instruction):
    pass


###### Subroutines

# Make a function call. Stores return address on call stack
class Call(Instruction):
    def __init__(self, location):
        self.location = location

# Return to the link address stored in the call stack
class Return(Instruction):
    pass

# Allocate machine words for local variables
class LocalAlloc(Instruction):
    def __init__(self, variable_count: int):
        self.variable_count = variable_count

# Allocate machine words for global variables
class GlobalAlloc(Instruction):
    def __init__(self, variable_count: int):
        self.variable_count = variable_count


###### Comparison - Pop two values off the op stack, compare them, then push the result. 0 for false and 1 for true


class Equal(Instruction):
    pass

class NotEqual(Instruction):
    pass

class LessThan(Instruction):
    pass

class GreaterThan(Instruction):
    pass

class LessThanEqualTo(Instruction):
    pass

class GreaterThanEqualTo(Instruction):
    pass


###### Built ins

# Allows built-in instructions that can be called in code but executed by VM.
# Built-in instructions pass arguments as immediates and DO NOT use the op stack OR the call stack (as a result they must pass constants)
class BuiltInInstruction(Instruction):
    pass


# Allows built-in functions that can be called in code but executed by VM.
# Built-in functions pass arguments on the op stack and DO NOT use the call stack
# It is down to the VM implementor to ensure they remove the correct number of items from the stack
class BuiltInFunction(Instruction):
    pass



###### Binary ops - Each instruction pops two values, operates on them, then pushes the result

class Add(Instruction):
    pass


###### Unary ops - Each instruction pops a value, operates on it, then pushes the result

class UnaryNegative(Instruction):
    pass

class UnaryPositive(Instruction):
    pass

class OnesComplement(Instruction):
    pass

class LogicalNot(Instruction):
    pass

###### Ternary

# IfExp, C ternary instruction.
class Ternary(Instruction):
    pass