import ir
from instruction_set import CompilationResult, InstructionSet, validate_instruction_set


INTERPRETER_INSTRUCTION_SET = InstructionSet(frozenset({
    ir.Add, ir.And, ir.Assert, ir.Call, ir.Drop, ir.Dupe, ir.Equal, ir.Free,
    ir.GlobalAlloc, ir.GreaterThan, ir.GreaterThanEqualTo, ir.Jump,
    ir.JumpIfFalse, ir.JumpIfTrue, ir.LessThan, ir.LessThanEqualTo, ir.Load,
    ir.LocalAlloc, ir.LogicalAnd, ir.LogicalNot, ir.LogicalOr, ir.Malloc,
    ir.Multiply, ir.NotEqual, ir.OnesComplement, ir.OpStackPopArg,
    ir.OpStackPopGlobal, ir.OpStackPopLocal, ir.OpStackPopToCallStack,
    ir.OpStackPushArg, ir.OpStackPushGlobal, ir.OpStackPushLiteral,
    ir.OpStackPushLocal, ir.Or, ir.PrintBool, ir.PrintChar, ir.PrintInt,
    ir.PrintString, ir.Return, ir.Roll, ir.ShiftLeft, ir.ShiftRight, ir.Store,
    ir.Sub, ir.UnaryNegative, ir.UnaryPositive, ir.Xor,
}))

class CallStackItem:
    def __repr__(self):
        return f"{type(self).__name__}({self.inner})"

class LinkAddress(CallStackItem):
    def __init__(self, inner):
        self.inner = inner

class BasePointer(CallStackItem):
    def __init__(self, inner):
        self.inner = inner

class LocalVariable(CallStackItem):
    def __init__(self, inner):
        self.inner = inner

class Argument(CallStackItem):
    def __init__(self, inner):
        self.inner = inner


class Interpreter:

    INSTRUCTION_SET = INTERPRETER_INSTRUCTION_SET

    def run(self, instructions: list[ir.Instruction]):

        if isinstance(instructions, CompilationResult):
            validate_instruction_set(instructions, self.INSTRUCTION_SET)
        else:
            validate_instruction_set(
                CompilationResult(list(instructions), [None] * len(instructions)),
                self.INSTRUCTION_SET,
            )

        op_stack = []
        call_stack = []
        globals = []

        heap = {}

        pc = 0
        bp = 0

        malloc_index = 0

        while True:

            if pc >= len(instructions):
                break

            op = instructions[pc]


            if isinstance(op, ir.Call):
                call_stack.append(LinkAddress(pc + 1))

                pc = op.location

                continue
            elif isinstance(op, ir.LocalAlloc):
                local_count = op.variable_count

                call_stack.append(BasePointer(bp))

                bp = len(call_stack) - 1

                for i in range(local_count):
                    call_stack.append(LocalVariable(None))
            elif isinstance(op, ir.GlobalAlloc):
                for i in range(op.variable_count):
                    globals.append(0)
            elif isinstance(op, ir.Return):
                arg_count = op.arg_count

                call_stack = call_stack[:bp+1]

                bp = call_stack.pop().inner

                link = call_stack.pop()

                for i in range(arg_count):
                    call_stack.pop()

                pc = link.inner

                continue
            elif isinstance(op, ir.OpStackPushLocal):
                op_stack.append(call_stack[bp+op.offset+1])
            elif isinstance(op, ir.OpStackPopLocal):
                call_stack[bp+op.offset+1] = op_stack.pop()
            elif isinstance(op, ir.OpStackPushArg):
                op_stack.append(call_stack[bp-2 - op.offset].inner)
            elif isinstance(op, ir.OpStackPopArg):
                call_stack[bp-2 - op.offset].inner = op_stack.pop()
            elif isinstance(op, ir.OpStackPushGlobal):
                op_stack.append(globals[op.offset])
            elif isinstance(op, ir.OpStackPopGlobal):
                globals[op.offset] = op_stack.pop()
            elif isinstance(op, ir.OpStackPopToCallStack):
                call_stack.append(Argument(op_stack.pop()))
            elif isinstance(op, ir.OpStackPushLiteral):
                op_stack.append(op.value)
            elif isinstance(op, ir.BuiltInInstruction):
                raise Exception(f"Interpreter has no implementation for external built-in '{op.name}'")

            elif isinstance(op, ir.PrintInt):
                print(f"{op_stack.pop()}", end='')
            elif isinstance(op, ir.PrintString):
                pointer = op_stack.pop()
                length = heap[pointer - 1]
                print(
                    "".join(chr(heap[pointer + index]) for index in range(length)),
                    end='',
                )
            elif isinstance(op, ir.PrintBool):
                print("True" if bool(op_stack.pop()) else "False", end='')
            elif isinstance(op, ir.PrintChar):
                print(chr(op_stack.pop()), end='')

            elif isinstance(op, ir.Jump):
                pc = op.location
                continue
            elif isinstance(op, ir.JumpIfTrue):
                if op_stack.pop() != 0:
                    pc = op.location
                    continue
            elif isinstance(op, ir.JumpIfFalse):
                if op_stack.pop() == 0:
                    pc = op.location
                    continue
            elif isinstance(op, ir.Equal):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(int(a == b))
            elif isinstance(op, ir.NotEqual):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(int(a != b))
            elif isinstance(op, ir.LessThan):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(int(a < b))
            elif isinstance(op, ir.GreaterThan):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(int(a > b))
            elif isinstance(op, ir.LessThanEqualTo):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(int(a <= b))
            elif isinstance(op, ir.GreaterThanEqualTo):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(int(a >= b))
            elif isinstance(op, ir.Add):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(a + b)
            elif isinstance(op, ir.Sub):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(a - b)
            elif isinstance(op, ir.Multiply):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(a * b)
            elif isinstance(op, ir.LogicalAnd):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(int(bool(a) and bool(b)))
            elif isinstance(op, ir.LogicalOr):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(int(bool(a) or bool(b)))
            elif isinstance(op, ir.UnaryNegative):
                a = op_stack.pop()
                op_stack.append(-a)
            elif isinstance(op, ir.UnaryPositive):
                a = op_stack.pop()
                op_stack.append(+a)
            elif isinstance(op, ir.LogicalNot):
                a = op_stack.pop()
                op_stack.append(int(not bool(a)))
            elif isinstance(op, ir.And):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(a & b)
            elif isinstance(op, ir.Or):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(a | b)
            elif isinstance(op, ir.Xor):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(a ^ b)
            elif isinstance(op, ir.ShiftLeft):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(a << b)
            elif isinstance(op, ir.ShiftRight):
                b = op_stack.pop()
                a = op_stack.pop()
                op_stack.append(a >> b)
            elif isinstance(op, ir.OnesComplement):
                a = op_stack.pop()
                op_stack.append(~a)
            elif isinstance(op, ir.Malloc):
                size = op_stack.pop()

                op_stack.append(malloc_index)

                malloc_index += size
            elif isinstance(op, ir.Free):
                pass
            elif isinstance(op, ir.Store):
                value = op_stack.pop()
                index = op_stack.pop()

                heap[index] = value
            elif isinstance(op, ir.Load):
                index = op_stack.pop()

                if index not in heap:
                    heap[index] = 0

                op_stack.append(heap[index])

            elif isinstance(op, ir.Dupe):
                op_stack.append(op_stack[-1])
            elif isinstance(op, ir.Drop):
                if op.count < 0:
                    raise Exception("DROP count cannot be negative")
                if op.count > len(op_stack):
                    raise Exception("DROP count exceeds the operand stack")
                if op.count:
                    del op_stack[-op.count:]
            elif isinstance(op, ir.Roll):
                if op.depth < 0:
                    raise Exception("ROLL depth cannot be negative")
                if op.depth >= len(op_stack):
                    raise Exception("ROLL depth exceeds the operand stack")
                value = op_stack.pop(-op.depth - 1)
                op_stack.append(value)
            elif isinstance(op, ir.Assert):
                if not op_stack.pop():
                    raise AssertionError("VM assertion failed")


            else:
                raise Exception(f"Unknown or unhandled instruction {op}")

            pc += 1

        return op_stack[0] if len(op_stack) != 0 else None
