import ir
from instruction_set import CompilationResult, InstructionSet, validate_instruction_set


BLUE = "\033[34m"
RESET_COLOUR = "\033[0m"


def print_vm_output(value):
    print(f"{BLUE}{value}{RESET_COLOUR}", end='')


INTERPRETER_INSTRUCTION_SET = InstructionSet(frozenset({
    ir.IAdd, ir.And, ir.Call, ir.Drop, ir.Dupe, ir.Equal, ir.Free,
    ir.FAdd, ir.FMultiply, ir.FSub, ir.FUnaryNegative, ir.FUnaryPositive,
    ir.Alloc, ir.GreaterThan, ir.GreaterThanEqualTo, ir.Jump,
    ir.JumpIfFalse, ir.JumpIfTrue, ir.LessThan, ir.LessThanEqualTo, ir.Load,
    ir.Input, ir.LogicalAnd, ir.LogicalNot, ir.LogicalOr, ir.Malloc,
    ir.IMod, ir.IMultiply, ir.IntToFloat, ir.NotEqual, ir.OnesComplement,
    ir.StackPopGlobal, ir.StackPopVariable, ir.StackPushLiteral,
    ir.StackPushGlobal, ir.StackPushVariable, ir.Or, ir.PrintBool, ir.PrintChar, ir.PrintFloat, ir.PrintInt,
    ir.PrintString, ir.Return, ir.Roll, ir.ShiftLeft, ir.ShiftRight, ir.Store,
    ir.ISub, ir.IUnaryNegative, ir.IUnaryPositive, ir.Xor,
}))

class StackControlItem:
    def __repr__(self):
        return f"{type(self).__name__}({self.inner})"

class LinkAddress(StackControlItem):
    def __init__(self, inner):
        self.inner = inner

class BasePointer(StackControlItem):
    def __init__(self, inner):
        self.inner = inner


class Interpreter:

    INSTRUCTION_SET = INTERPRETER_INSTRUCTION_SET

    def __init__(self, memory_size=65536):
        if memory_size <= 0:
            raise ValueError("Memory size must be positive")
        self.memory_size = memory_size

    def run(self, instructions: list[ir.Instruction]):

        if isinstance(instructions, CompilationResult):
            validate_instruction_set(instructions, self.INSTRUCTION_SET)
        else:
            validate_instruction_set(
                CompilationResult(list(instructions), [None] * len(instructions)),
                self.INSTRUCTION_SET,
            )

        memory = [0] * self.memory_size
        sp = self.memory_size

        def stack_size():
            return self.memory_size - sp

        def push(value):
            nonlocal sp
            if sp == malloc_index:
                raise MemoryError("Stack collided with allocated memory")
            sp -= 1
            memory[sp] = value

        def pop(depth=0):
            nonlocal sp
            if depth < 0 or depth >= stack_size():
                raise IndexError("Stack pop exceeds the stack")
            address = sp + depth
            value = memory[address]
            while address > sp:
                memory[address] = memory[address - 1]
                address -= 1
            memory[sp] = 0
            sp += 1
            return value

        def peek(depth=0):
            if depth < 0 or depth >= stack_size():
                raise IndexError("Stack access exceeds the stack")
            return memory[sp + depth]

        def check_address(address):
            if type(address) is not int or address < 0 or address >= self.memory_size:
                raise MemoryError(f"Memory address {address!r} is out of range")

        pc = 0
        bp = self.memory_size

        malloc_index = 0

        counter = 0

        while True:

            counter += 1

            if pc >= len(instructions):
                break

            op = instructions[pc]


            if isinstance(op, ir.Call):
                push(LinkAddress(pc + 1))
                push(BasePointer(bp))
                bp = sp

                pc = op.location

                continue
            elif isinstance(op, ir.Alloc):
                for i in range(op.variable_count):
                    push(0)
            elif isinstance(op, ir.Return):
                arg_count = op.arg_count
                if arg_count < 0:
                    raise Exception("RETURN argument count cannot be negative")
                if bp < sp or bp >= self.memory_size:
                    raise Exception("RETURN has no valid call frame")

                while sp < bp:
                    pop()

                saved_bp = pop()
                if not isinstance(saved_bp, BasePointer):
                    raise Exception("RETURN expected a saved base pointer")

                link = pop()
                if not isinstance(link, LinkAddress):
                    raise Exception("RETURN expected a link address")
                if arg_count > stack_size():
                    raise Exception("RETURN argument count exceeds the stack")

                for i in range(arg_count):
                    pop()

                bp = saved_bp.inner
                pc = link.inner

                continue
            elif isinstance(op, ir.StackPushVariable):
                variable = bp - op.offset
                if variable < sp or variable >= self.memory_size:
                    raise Exception("BP-relative variable offset exceeds the stack")
                value = memory[variable]
                if isinstance(value, StackControlItem):
                    raise Exception("BP-relative variable offset addresses frame metadata")
                push(value)
            elif isinstance(op, ir.StackPopVariable):
                variable = bp - op.offset
                if variable <= sp or variable >= self.memory_size:
                    raise Exception("BP-relative variable offset exceeds the stack")
                if isinstance(memory[variable], StackControlItem):
                    raise Exception("BP-relative variable offset addresses frame metadata")
                memory[variable] = pop()
            elif isinstance(op, ir.StackPushGlobal):
                if op.index < 0 or op.index >= stack_size():
                    raise Exception("Global stack index exceeds the stack")
                variable = self.memory_size - 1 - op.index
                value = memory[variable]
                if isinstance(value, StackControlItem):
                    raise Exception("Global stack index addresses frame metadata")
                push(value)
            elif isinstance(op, ir.StackPopGlobal):
                if op.index < 0 or op.index >= stack_size() - 1:
                    raise Exception("Global stack index exceeds the stack")
                variable = self.memory_size - 1 - op.index
                if isinstance(memory[variable], StackControlItem):
                    raise Exception("Global stack index addresses frame metadata")
                memory[variable] = pop()
            elif isinstance(op, ir.StackPushLiteral):
                push(op.value)
            elif isinstance(op, ir.BuiltInInstruction):
                raise Exception(f"Interpreter has no implementation for external built-in '{op.name}'")
            elif isinstance(op, ir.BuiltInFunction):
                raise Exception(f"Interpreter has no implementation for external built-in '{op.name}'")

            elif isinstance(op, ir.Input):
                maximum_length = peek()
                pointer = peek(1)
                if maximum_length < 0:
                    raise Exception("INPUT maximum length cannot be negative")
                value = input()[:maximum_length]
                for index, character in enumerate(value):
                    check_address(pointer + index)
                    memory[pointer + index] = ord(character)
                memory[sp] = len(value)

            elif isinstance(op, ir.PrintInt):
                print_vm_output(pop())
            elif isinstance(op, ir.PrintFloat):
                print_vm_output(pop())
            elif isinstance(op, ir.PrintString):
                length = pop()
                pointer = pop()
                for index in range(length):
                    check_address(pointer + index)
                print_vm_output(
                    "".join(chr(memory[pointer + index]) for index in range(length))
                )
            elif isinstance(op, ir.PrintBool):
                print_vm_output("True" if bool(pop()) else "False")
            elif isinstance(op, ir.PrintChar):
                print_vm_output(chr(pop()))

            elif isinstance(op, ir.Jump):
                pc = op.location
                continue
            elif isinstance(op, ir.JumpIfTrue):
                if pop() != 0:
                    pc = op.location
                    continue
            elif isinstance(op, ir.JumpIfFalse):
                if pop() == 0:
                    pc = op.location
                    continue
            elif isinstance(op, ir.Equal):
                b = pop()
                a = pop()
                push(int(a == b))
            elif isinstance(op, ir.NotEqual):
                b = pop()
                a = pop()
                push(int(a != b))
            elif isinstance(op, ir.LessThan):
                b = pop()
                a = pop()
                push(int(a < b))
            elif isinstance(op, ir.GreaterThan):
                b = pop()
                a = pop()
                push(int(a > b))
            elif isinstance(op, ir.LessThanEqualTo):
                b = pop()
                a = pop()
                push(int(a <= b))
            elif isinstance(op, ir.GreaterThanEqualTo):
                b = pop()
                a = pop()
                push(int(a >= b))
            elif isinstance(op, (ir.IAdd, ir.FAdd)):
                b = pop()
                a = pop()
                push(a + b)
            elif isinstance(op, (ir.ISub, ir.FSub)):
                b = pop()
                a = pop()
                push(a - b)
            elif isinstance(op, (ir.IMultiply, ir.FMultiply)):
                b = pop()
                a = pop()
                push(a * b)
            elif isinstance(op, ir.IMod):
                b = pop()
                a = pop()
                push(a % b)
            elif isinstance(op, ir.LogicalAnd):
                b = pop()
                a = pop()
                push(int(bool(a) and bool(b)))
            elif isinstance(op, ir.LogicalOr):
                b = pop()
                a = pop()
                push(int(bool(a) or bool(b)))
            elif isinstance(op, (ir.IUnaryNegative, ir.FUnaryNegative)):
                a = pop()
                push(-a)
            elif isinstance(op, (ir.IUnaryPositive, ir.FUnaryPositive)):
                a = pop()
                push(+a)
            elif isinstance(op, ir.IntToFloat):
                push(float(pop()))
            elif isinstance(op, ir.LogicalNot):
                a = pop()
                push(int(not bool(a)))
            elif isinstance(op, ir.And):
                b = pop()
                a = pop()
                push(a & b)
            elif isinstance(op, ir.Or):
                b = pop()
                a = pop()
                push(a | b)
            elif isinstance(op, ir.Xor):
                b = pop()
                a = pop()
                push(a ^ b)
            elif isinstance(op, ir.ShiftLeft):
                b = pop()
                a = pop()
                push(a << b)
            elif isinstance(op, ir.ShiftRight):
                b = pop()
                a = pop()
                push(a >> b)
            elif isinstance(op, ir.OnesComplement):
                a = pop()
                push(~a)
            elif isinstance(op, ir.Malloc):
                size = pop()
                if type(size) is not int or size < 0:
                    raise MemoryError("MALLOC size must be a non-negative integer")
                if malloc_index + size >= sp:
                    raise MemoryError("Allocated memory collided with the stack")
                pointer = malloc_index
                malloc_index += size
                push(pointer)
            elif isinstance(op, ir.Free):
                _pointer = pop()
            elif isinstance(op, ir.Store):
                value = pop()
                index = pop()

                check_address(index)
                memory[index] = value
            elif isinstance(op, ir.Load):
                index = pop()

                check_address(index)
                push(memory[index])

            elif isinstance(op, ir.Dupe):
                push(peek())
            elif isinstance(op, ir.Drop):
                if op.count < 0:
                    raise Exception("DROP count cannot be negative")
                if op.count > stack_size():
                    raise Exception("DROP count exceeds the value stack")
                if op.count:
                    for _ in range(op.count):
                        pop()
            elif isinstance(op, ir.Roll):
                if op.depth < 0:
                    raise Exception("ROLL depth cannot be negative")
                if op.depth >= stack_size():
                    raise Exception("ROLL depth exceeds the value stack")
                value = pop(op.depth)
                push(value)
            else:
                raise Exception(f"Unknown or unhandled instruction {op}")

            pc += 1

        print(f"Executed {counter} instructions")

        self.memory = memory
        self.sp = sp
        self.bp = bp
        return peek() if stack_size() else None
