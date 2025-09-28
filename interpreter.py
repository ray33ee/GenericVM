import ir

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

    def run(self, instructions: list[ir.Instruction]):

        op_stack = []
        call_stack = []
        globals = []

        pc = 0
        bp = 0

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
                pass
            elif isinstance(op, ir.OpStackPopGlobal):
                pass
            elif isinstance(op, ir.OpStackPopToCallStack):
                call_stack.append(Argument(op_stack.pop()))
            elif isinstance(op, ir.OpStackPushLiteral):
                op_stack.append(op.value)
            elif isinstance(op, ir.BuiltInInstruction):
                name = op.name

                if name == "finish":
                    break
                elif name == "print":
                    print(f"Print function: {op_stack.pop()}")
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




            pc += 1
