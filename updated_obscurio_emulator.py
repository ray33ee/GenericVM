import obfuscate
import ir


ADDRESS_MASK = 0xFFFFFFFF
MEMORY_SIZE = 0x100000000

BLUE = "\033[34m"
RESET_COLOUR = "\033[0m"


def print_vm_output(value):
    print(f"{BLUE}{value}{RESET_COLOUR}", end='')

def run(instructions):
    # Sparse representation of Obscurio's single zero-initialized 32-bit,
    # word-addressed memory space.
    memory = {}

    # SP always points to the address where the next pushed word will be stored.
    # An empty stack therefore starts at the highest address.
    sp = ADDRESS_MASK
    bp = ADDRESS_MASK

    pc = 0
    counter = 0

    # Obscurio-specific allocator metadata. Allocation policy is not part of
    # GenericVM; its pointers still address this same memory dictionary.
    memory[0] = 2

    def push(value):
        nonlocal sp
        if sp < 0:
            raise Exception("stack overflow")
        memory[sp] = value & ADDRESS_MASK if type(value) is int else value
        sp -= 1

    def pop():
        nonlocal sp
        if sp == ADDRESS_MASK:
            raise Exception("stack underflow")
        sp += 1
        value = memory.get(sp, 0)
        memory.pop(sp, None)
        return value

    def peek(depth=0):
        if depth < 0 or depth >= ADDRESS_MASK - sp:
            raise Exception("stack access exceeds the stack")
        return memory.get(sp + 1 + depth, 0)

    def replace(depth, value):
        if depth < 0 or depth >= ADDRESS_MASK - sp:
            raise Exception("stack access exceeds the stack")
        memory[sp + 1 + depth] = value

    while True:
        counter += 1

        if pc >= len(instructions):
            break

        op = instructions[pc]

        if isinstance(op, ir.Call):
            # CALL now creates the complete frame. GenericVM ALLOC has already
            # been translated into ordinary zero pushes.
            push(pc + 1)
            push(bp)
            bp = sp + 1
            pc = obfuscate.deobfuscate_addresses(op.location)
            continue

        elif isinstance(op, ir.Return):
            arg_count = obfuscate.deobfuscate_ret_alloc(op.arg_count, pc)

            if arg_count < 0:
                raise Exception("RETURN argument count cannot be negative")

            # Discard evaluations and locals, stopping at the saved-BP word.
            while sp + 1 != bp:
                pop()

            bp = pop()
            link = pop()

            if arg_count > ADDRESS_MASK - sp:
                raise Exception("RETURN argument count exceeds the stack")
            for _ in range(arg_count):
                pop()

            pc = link
            continue

        elif isinstance(op, ir.OpStackPushVariable):
            offset = obfuscate.deobfuscate_stack_offsets(op.offset, pc)
            address = (bp - offset) & ADDRESS_MASK
            push(memory.get(address, 0))

        elif isinstance(op, ir.OpStackPopVariable):
            offset = obfuscate.deobfuscate_stack_offsets(op.offset, pc)
            address = (bp - offset) & ADDRESS_MASK
            memory[address] = pop()

        elif isinstance(op, ir.OpStackPushLiteral):
            push(obfuscate.deobfuscate_stack_literals(op.value, pc))

        elif isinstance(op, ir.JumpIfZero):
            if pop() == 0:
                pc = obfuscate.deobfuscate_addresses(op.location)
                continue

        elif isinstance(op, ir.MathShift):
            amount = pop() & ADDRESS_MASK
            value = pop() & ADDRESS_MASK

            # Positive is left shift. One's-complement negative is right shift.
            if amount & 0x80000000:
                amount = (~amount) & ADDRESS_MASK
                push((value >> amount) & ADDRESS_MASK if amount < 32 else 0)
            else:
                push((value << amount) & ADDRESS_MASK if amount < 32 else 0)

        elif isinstance(op, ir.MathNAND):
            b = pop()
            a = pop()
            push(~(a & b) & ADDRESS_MASK)

        elif isinstance(op, ir.StackSwap):
            top = peek()
            deep = peek(op.depth)
            replace(0, deep)
            replace(op.depth, top)

        elif isinstance(op, ir.StackCopy):
            push(peek(op.depth))

        elif isinstance(op, ir.PrintC):
            value = pop()
            if value <= 0x7F:
                print_vm_output(chr(value))

        elif isinstance(op, ir.Input):
            max_length = peek()
            location = peek(1)
            in_string = input()[:max_length]

            for index, character in enumerate(in_string):
                memory[(location + index) & ADDRESS_MASK] = ord(character)

            replace(0, len(in_string))

        elif isinstance(op, ir.Store):
            value = pop()
            address = pop() & ADDRESS_MASK
            memory[address] = value

        elif isinstance(op, ir.Load):
            address = pop() & ADDRESS_MASK
            push(memory.get(address, 0))

        else:
            raise Exception(f"unexpected instruction: {op}")

        pc += 1

    print(f"Executed {counter} instructions")

    return peek()
