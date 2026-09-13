
import ir
import obfuscate
import random


# Obscurio uses a 32-bit word-addressed memory. GenericVM globals are numbered
# from the logical bottom of its downward-growing stack, so global zero occupies
# the highest address.
STACK_BOTTOM_ADDRESS = 0xFFFFFFFF

########## Stack operations
def rotate_ops(l):
    l.append(ir.StackSwap(2))
    l.append(ir.StackSwap(1))

def deep_ops(l):
    l.append(ir.StackSwap(1))
    l.append(ir.StackSwap(2))
    l.append(ir.StackSwap(3))

def dupe_ops(l):
    l.append(ir.StackCopy(0))

def swap_ops(l):
    l.append(ir.StackSwap(1))

def drop_ops(output, count):
    DROP_SCRATCH = 1

    for _ in range(count):
        output.append(ir.OpStackPushLiteral(DROP_SCRATCH))
        swap_ops(output)
        output.append(ir.Store())

########## Basic booleans
def and_ops(l):
    l.append(ir.MathNAND())
    dupe_ops(l)
    l.append(ir.MathNAND())

def or_ops(l):
    dupe_ops(l)
    l.append(ir.MathNAND())
    swap_ops(l)
    dupe_ops(l)
    l.append(ir.MathNAND())
    l.append(ir.MathNAND())

def not_ops(l):
    dupe_ops(l)
    l.append(ir.MathNAND())

def xor_ops(l):

    # a, b
    l.append(ir.StackCopy(1)) # a, b, a
    l.append(ir.StackCopy(1)) # a, b, a, b
    and_ops(l) # a, b, a&b
    not_ops(l) # a, b, ~(a&b)
    rotate_ops(l) # ~(a&b), a, b
    or_ops(l) # ~(a&b), a|b
    and_ops(l) # ~(a&b) & (a|b)

########## Logical bool ops and conversions
def convert_to_bool_ops(l):
    dupe_ops(l)
    l.append(ir.OpStackPushLiteral(16))
    shiftr_ops(l)
    or_ops(l)

    dupe_ops(l)
    l.append(ir.OpStackPushLiteral(8))
    shiftr_ops(l)
    or_ops(l)

    dupe_ops(l)
    l.append(ir.OpStackPushLiteral(4))
    shiftr_ops(l)
    or_ops(l)

    dupe_ops(l)
    l.append(ir.OpStackPushLiteral(2))
    shiftr_ops(l)
    or_ops(l)

    dupe_ops(l)
    l.append(ir.OpStackPushLiteral(1))
    shiftr_ops(l)
    or_ops(l)

    l.append(ir.OpStackPushLiteral(1))
    and_ops(l)

def convert_2_to_bool_ops(l):
    convert_to_bool_ops(l)
    swap_ops(l)
    convert_to_bool_ops(l)
    swap_ops(l)

def invert_bool_ops(l):
    l.append(ir.OpStackPushLiteral(1))
    xor_ops(l)

########## Addition & subtraction
def add_ops(l):
    for _ in range(32):
        l.append(ir.StackCopy(1))
        l.append(ir.StackCopy(1))
        and_ops(l)
        l.append(ir.OpStackPushLiteral(1))
        shiftl_ops(l)
        rotate_ops(l)
        xor_ops(l)

    or_ops(l)

def twos_complement_ops(l):
    not_ops(l)
    l.append(ir.OpStackPushLiteral(1))
    add_ops(l)

def subtract_ops(l):
    twos_complement_ops(l)
    add_ops(l)

########## Multiplication & mod division
def multiply_ops(l):
    # 1. Prep the stack to turn a, b into 0, a, b:
    l.append(ir.OpStackPushLiteral(0))
    rotate_ops(l)

    # 2. Perform 16 rounds of the multiply algorithm
    for _ in range(32):
        l.append(ir.StackCopy(1))
        l.append(ir.StackCopy(1))
        l.append(ir.OpStackPushLiteral(1))
        and_ops(l)


        dupe_ops(l)
        l.append(ir.OpStackPushLiteral(1))
        shiftl_ops(l)
        or_ops(l)

        dupe_ops(l)
        l.append(ir.OpStackPushLiteral(2))
        shiftl_ops(l)
        or_ops(l)

        dupe_ops(l)
        l.append(ir.OpStackPushLiteral(4))
        shiftl_ops(l)
        or_ops(l)

        dupe_ops(l)
        l.append(ir.OpStackPushLiteral(8))
        shiftl_ops(l)
        or_ops(l)

        dupe_ops(l)
        l.append(ir.OpStackPushLiteral(16))
        shiftl_ops(l)
        or_ops(l)

        and_ops(l)


        deep_ops(l)
        add_ops(l)
        rotate_ops(l)

        swap_ops(l)
        l.append(ir.OpStackPushLiteral(1))
        shiftl_ops(l)
        swap_ops(l)

        l.append(ir.OpStackPushLiteral(1))
        shiftr_ops(l)

    # 3. Turn [..., a * b, 0, 0] into [..., a * b]:
    or_ops(l)
    or_ops(l)


def mod_ops(l):

    def subtract_with_borrow():


        l.append(ir.StackCopy(1))
        l.append(ir.StackCopy(1))
        subtract_ops(l)

        l.append(ir.StackCopy(2))                            # ..., a, b, d, a
        l.append(ir.StackCopy(2))                            # ..., a, b, d, a, b

        xor_ops(l)                         # ..., a, b, d, a^b
        not_ops(l)          # ..., a, b, d, ~(a^b)

        l.append(ir.StackCopy(1))                # ..., a, b, d, ~(a^b), d
        and_ops(l)             # ..., a, b, d, term2

        deep_ops(l)                # ..., b, d, term2, a
        not_ops(l)          # ..., b, d, term2, ~a

        deep_ops(l)                # ..., d, term2, ~a, b
        and_ops(l)             # ..., d, term2, term1

        # term1 | term2

        or_ops(l)              # ..., d, borrow_word

        # Extract bit 31.

        l.append(ir.OpStackPushLiteral(31))
        shiftr_ops(l)           # ..., d, borrow

    l.append(ir.OpStackPushLiteral(0))

    for _ in range(32):

        dupe_ops(l)

        l.append(ir.OpStackPushLiteral(31))
        shiftr_ops(l)

        deep_ops(l)

        dupe_ops(l)

        l.append(ir.OpStackPushLiteral(31))
        shiftr_ops(l)

        l.append(ir.StackCopy(1))

        l.append(ir.OpStackPushLiteral(1))
        shiftl_ops(l)

        rotate_ops(l)

        swap_ops(l)
        drop_ops(l, 1)

        deep_ops(l)

        l.append(ir.OpStackPushLiteral(1))
        shiftl_ops(l)

        or_ops(l)

        l.append(ir.StackSwap(1))
        l.append(ir.StackSwap(3))
        l.append(ir.StackSwap(2))
        l.append(ir.StackSwap(1))

        l.append(ir.StackCopy(2))                            # copy y
        l.append(ir.StackCopy(1))                # copy t
        swap_ops(l)                        # arrange t, y

        subtract_with_borrow()

        deep_ops(l)
        not_ops(l)          # ..., t, d, borrow, ~overflow

        and_ops(l)             # ..., t, d, keep

        twos_complement_ops(l)

        dupe_ops(l)
        not_ops(l)

        l.append(ir.StackCopy(2))

        and_ops(l)
        deep_ops(l)
        l.append(ir.StackCopy(2))
        and_ops(l)
        or_ops(l)
        rotate_ops(l)
        and_ops(l)

        l.append(ir.OpStackPushLiteral(0))
        and_ops(l)

        or_ops(l)

    rotate_ops(l)
    and_ops(l)
    or_ops(l)

########## Equalities and inequalities

def eq_ops(l):
    neq_ops(l)
    invert_bool_ops(l)

def neq_ops(l):
    subtract_ops(l)
    convert_to_bool_ops(l)

def lt_ops(l):
    subtract_ops(l)  # Subtract
    l.append(ir.OpStackPushLiteral(31))
    shiftr_ops(l)  # Move the sign bit down

def gt_ops(l):
    swap_ops(l)
    lt_ops(l)

def le_ops(l):
    gt_ops(l)
    invert_bool_ops(l)

def ge_ops(l):
    lt_ops(l)
    invert_bool_ops(l)

########## Malloc
def malloc(l):
    # Linear Allocator. Total number of bytes allocated so far stored in HEAP_TOP (This is also the pointer to the next allocation)

    HEAP_POINTER_LOCATION = 0

    l.append(ir.OpStackPushLiteral(HEAP_POINTER_LOCATION))
    l.append(ir.Load())
    l.append(ir.StackCopy(0))
    l.append(ir.StackSwap(2))

    add_ops(l)

    l.append(ir.OpStackPushLiteral(HEAP_POINTER_LOCATION))

    swap_ops(l)

    l.append(ir.Store())

########## Shifts

def shiftl_ops(l):
    l.append(ir.MathShift())

def shiftr_ops(l):
    not_ops(l)
    l.append(ir.MathShift())


def _finish_helper(instructions, fixups, base):
    """Resolve helper-local branch labels after its final location is known."""
    for jump, target in fixups:
        jump.location = base + target
    return instructions


def prints_helper(base):
    """Obscurio subroutine for GenericVM's [pointer, length] string value."""
    output = [ir.OpStackPushLiteral(0)]  # local 1: character index
    fixups = []

    loop = len(output)
    output.append(ir.OpStackPushVariable(1))    # index
    output.append(ir.OpStackPushVariable((-2) & 0xFFFFFFFF))   # length
    lt_ops(output)
    finished = ir.JumpIfZero(0)
    output.append(finished)

    output.append(ir.OpStackPushVariable((-3) & 0xFFFFFFFF))   # pointer
    output.append(ir.OpStackPushVariable(1))
    add_ops(output)
    output.append(ir.Load())
    output.append(ir.PrintC())

    output.append(ir.OpStackPushVariable(1))
    output.append(ir.OpStackPushLiteral(1))
    add_ops(output)
    output.append(ir.OpStackPopVariable(1))
    output.append(ir.OpStackPushLiteral(0))
    again = ir.JumpIfZero(0)
    output.append(again)

    end = len(output)
    output.append(ir.Return(2))
    fixups.extend(((finished, end), (again, loop)))
    return _finish_helper(output, fixups, base)


def printb_helper(base):
    """Print a boolean as hard-coded PrintC operations."""
    output = [ir.OpStackPushVariable((-2) & 0xFFFFFFFF)]
    print_false = ir.JumpIfZero(0)
    output.append(print_false)

    for character in "True":
        output.append(ir.OpStackPushLiteral(ord(character)))
        output.append(ir.PrintC())

    output.append(ir.OpStackPushLiteral(0))
    finished = ir.JumpIfZero(0)
    output.append(finished)

    false_branch = len(output)
    for character in "False":
        output.append(ir.OpStackPushLiteral(ord(character)))
        output.append(ir.PrintC())

    end = len(output)
    output.append(ir.Return(1))
    return _finish_helper(
        output,
        ((print_false, false_branch), (finished, end)),
        base,
    )


def printi_helper(base):
    """Bounded signed 32-bit decimal printer built solely on PrintC."""
    output = [
        ir.OpStackPushLiteral(0),  # local 1: magnitude
        ir.OpStackPushLiteral(0),  # local 2: have printed a digit
        ir.OpStackPushLiteral(0),  # local 3: current digit
        ir.OpStackPushVariable((-2) & 0xFFFFFFFF),
        ir.OpStackPopVariable(1),
    ]
    fixups = []

    # Print a sign and convert two's-complement negatives to their magnitude.
    output.append(ir.OpStackPushVariable(1))
    output.append(ir.OpStackPushLiteral(31))
    shiftr_ops(output)
    nonnegative = ir.JumpIfZero(0)
    output.append(nonnegative)
    output.append(ir.OpStackPushLiteral(45))
    output.append(ir.PrintC())
    output.append(ir.OpStackPushVariable(1))
    twos_complement_ops(output)
    output.append(ir.OpStackPopVariable(1))
    after_sign = len(output)
    fixups.append((nonnegative, after_sign))

    # At most nine subtractions are needed at each decimal place.
    for place in (1000000000, 100000000, 10000000, 1000000, 100000,
                  10000, 1000, 100, 10, 1):
        output.append(ir.OpStackPushLiteral(0))
        output.append(ir.OpStackPopVariable(3))
        subtract_loop = len(output)
        output.append(ir.OpStackPushVariable(1))
        output.append(ir.OpStackPushLiteral(place))
        ge_ops(output)
        digit_ready = ir.JumpIfZero(0)
        output.append(digit_ready)
        output.append(ir.OpStackPushVariable(1))
        output.append(ir.OpStackPushLiteral(place))
        subtract_ops(output)
        output.append(ir.OpStackPopVariable(1))
        output.append(ir.OpStackPushVariable(3))
        output.append(ir.OpStackPushLiteral(1))
        add_ops(output)
        output.append(ir.OpStackPopVariable(3))
        output.append(ir.OpStackPushLiteral(0))
        repeat = ir.JumpIfZero(0)
        output.append(repeat)
        ready = len(output)
        fixups.extend(((digit_ready, ready), (repeat, subtract_loop)))

        skip_digit = None
        if place != 1:
            output.append(ir.OpStackPushVariable(2))
            output.append(ir.OpStackPushVariable(3))
            or_ops(output)
            skip_digit = ir.JumpIfZero(0)
            output.append(skip_digit)

        output.append(ir.OpStackPushVariable(3))
        output.append(ir.OpStackPushLiteral(48))
        add_ops(output)
        output.append(ir.PrintC())
        output.append(ir.OpStackPushLiteral(1))
        output.append(ir.OpStackPopVariable(2))
        if skip_digit is not None:
            fixups.append((skip_digit, len(output)))

    output.append(ir.Return(1))
    return _finish_helper(output, fixups, base)

def translate(generic_program):

    obscurio_program = []
    printi_calls = []
    prints_calls = []
    printb_calls = []

    for opcode, operand in generic_program:
        if opcode == 0:  # StackPushVariable
            # GenericVM has already combined local and argument addressing into
            # a signed BP-relative offset. Obscurio stores it as a 32-bit word.
            offset = operand & 0xFFFFFFFF
            obscurio_program.append([
                ir.OpStackPushVariable(offset)
            ])

        elif opcode == 1:  # StackPopVariable
            offset = operand & 0xFFFFFFFF
            obscurio_program.append([
                ir.OpStackPopVariable(offset)
            ])

        elif opcode == 2:  # StackPushGlobal
            address = (STACK_BOTTOM_ADDRESS - operand) & 0xFFFFFFFF
            obscurio_program.append([
                ir.OpStackPushLiteral(address),
                ir.Load(),
            ])

        elif opcode == 3:  # StackPopGlobal
            address = (STACK_BOTTOM_ADDRESS - operand) & 0xFFFFFFFF
            store = [ir.OpStackPushLiteral(address)]
            swap_ops(store)  # Store consumes [address, value].
            store.append(ir.Store())
            obscurio_program.append(store)

        elif opcode == 4: # StackPushLiteral
            obscurio_program.append([ir.OpStackPushLiteral(operand)])
        elif opcode == 20: # JMP
            # Simulate an unconditional jump by ensuring the condition is always tre
            jump = []
            # Pushing zero on the stack with a dedicated instruction is BORING
            # jump.append(ir.OpStackPushLiteral(0))
            # Lets think of some other ways to make 0 instead...

            make_index = random.randrange(7)

            if make_index == 0:
                jump.append(ir.OpStackPushLiteral(random.randrange(50000)))
                dupe_ops(jump)
                subtract_ops(jump)
            elif make_index == 1:
                jump.append(ir.OpStackPushLiteral(random.randrange(50000)))
                dupe_ops(jump)
                not_ops(jump)
                or_ops(jump)
                not_ops(jump)
            elif make_index == 2:
                x = random.randrange(50000)
                jump.append(ir.OpStackPushLiteral(x))
                jump.append(ir.OpStackPushLiteral(x))
                xor_ops(jump)
            elif make_index == 3:
                x = random.randrange(50000)
                jump.append(ir.OpStackPushLiteral(x))
                jump.append(ir.OpStackPushLiteral(0x100000000 - x))
                add_ops(jump)
            elif make_index == 4:
                jump.append(ir.OpStackPushLiteral(random.randrange(50000)))
                jump.append(ir.OpStackPushLiteral(random.randint(32, 50000)))
                shiftr_ops(jump)
            elif make_index == 5:
                jump.append(ir.OpStackPushLiteral(random.randrange(50000)))
                jump.append(ir.OpStackPushLiteral(1))
                shiftl_ops(jump)
                jump.append(ir.OpStackPushLiteral(1))
                and_ops(jump)
            elif make_index == 6:
                x = random.randrange(50000)
                jump.append(ir.OpStackPushLiteral(x))
                jump.append(ir.OpStackPushLiteral(0xFFFFFFFF - x))
                and_ops(jump)
            else:
                jump.append(ir.OpStackPushLiteral(0))

            jump.append(ir.JumpIfZero(operand))

            # For a laugh, add a bunch of random instructions in this unreachable section
            INSTRUCTION_SET = [ir.OpStackPushLiteral, ir.OpStackPushVariable, ir.OpStackPopVariable, ir.JumpIfZero, ir.MathNAND]

            for i in range(random.randint(100, 500)):
                choice = random.choice(INSTRUCTION_SET).randomise()
                jump.append(choice)

            obscurio_program.append(jump)
        elif opcode == 22:
            obscurio_program.append([ir.JumpIfZero(operand)])
        elif opcode == 40:
            obscurio_program.append([ir.Call(operand)])
        elif opcode == 41:
            obscurio_program.append([ir.Return(operand)])
        elif opcode == 42:
            obscurio_program.append([
                ir.OpStackPushLiteral(0) for _ in range(operand)
            ])
        elif opcode == 60:
            eq = []
            eq_ops(eq)
            obscurio_program.append(eq)
        elif opcode == 61:
            neq = []
            neq_ops(neq)
            obscurio_program.append(neq)
        elif opcode == 62:
            lt = []
            lt_ops(lt)
            obscurio_program.append(lt)
        elif opcode == 63:
            gt = []
            gt_ops(gt)
            obscurio_program.append(gt)
        elif opcode == 64:
            le = []
            le_ops(le)
            obscurio_program.append(le)
        elif opcode == 65:
            ge = []
            ge_ops(ge)
            obscurio_program.append(ge)
        elif opcode == 100:
            add = []
            add_ops(add)
            obscurio_program.append(add)
        elif opcode == 101:
            sub = []
            subtract_ops(sub)
            obscurio_program.append(sub)
        elif opcode == 102:
            mul = []
            multiply_ops(mul)
            obscurio_program.append(mul)
        elif opcode == 103:
            a = []
            and_ops(a)
            obscurio_program.append(a)
        elif opcode == 104:
            o = []
            or_ops(o)
            obscurio_program.append(o)
        elif opcode == 105:
            xor = []
            xor_ops(xor)
            obscurio_program.append(xor)
        elif opcode == 106:
            ls = []
            shiftl_ops(ls)
            obscurio_program.append(ls)
        elif opcode == 107:
            rs = []
            shiftr_ops(rs)
            obscurio_program.append(rs)
        elif opcode == 108:
            logical_and = []
            convert_2_to_bool_ops(logical_and)
            and_ops(logical_and)
            obscurio_program.append(logical_and)
        elif opcode == 109:
            logical_or = []
            convert_2_to_bool_ops(logical_or)
            or_ops(logical_or)
            obscurio_program.append(logical_or)
        elif opcode == 113:
            mod = []
            mod_ops(mod)
            obscurio_program.append(mod)
        elif opcode == 150:
            neg = []
            twos_complement_ops(neg)
            obscurio_program.append(neg)
        elif opcode == 151:
            obscurio_program.append([])
        elif opcode == 152:
            n = []
            not_ops(n)
            obscurio_program.append(n)

        elif opcode == 153:
            logical_not = []
            convert_to_bool_ops(logical_not)
            invert_bool_ops(logical_not)
            obscurio_program.append(logical_not)

        elif opcode == 200:
            d = []
            dupe_ops(d)
            obscurio_program.append(d)
        elif opcode == 201:
            # Drop N
            drops = []

            drop_ops(drops, operand)

            obscurio_program.append(drops)



        elif opcode == 202:

            roll = []

            for i in range(1, operand + 1):
                roll.append(ir.StackSwap(i))

            obscurio_program.append(roll)

        elif opcode == 162:
            call = ir.Call(0)
            printi_calls.append(call)
            obscurio_program.append([call])
        elif opcode == 163:
            call = ir.Call(0)
            prints_calls.append(call)
            obscurio_program.append([call])
        elif opcode == 164:
            call = ir.Call(0)
            printb_calls.append(call)
            obscurio_program.append([call])
        elif opcode == 165:
            obscurio_program.append([ir.PrintC()])
        elif opcode == 1003:
            obscurio_program.append([ir.Load()])
        elif opcode == 1004:
            obscurio_program.append([ir.Store()])
        elif opcode == 1005:
            obscurio_program.append([ir.Input()])
        elif opcode == 1006:
            m = []

            malloc(m)

            obscurio_program.append(m)

            pass #malloc
        elif opcode == 1007:
            obscurio_program.append([])
        else:
            raise Exception(f"Not implemented/supported (code {opcode})")

    cum_size = 0
    sum_sizes = []

    for group in obscurio_program:
        sum_sizes.append(cum_size)
        cum_size += len(group)

    for group in obscurio_program:
        for instruction in group:
            if isinstance(instruction, ir.JumpIfZero) or isinstance(instruction, ir.Call):
                location = obfuscate.deobfuscate_addresses(instruction.location)
                if location >= len(sum_sizes):
                    # Some jumps are past the end so we need to do a bit of math to calculate the
                    # location of the last instruction+1
                    instruction.location = sum_sizes[-1] + len(obscurio_program[-1])
                else:
                    instruction.location = sum_sizes[location]

    obscurio_program = [x for sublist in obscurio_program for x in sublist]

    # Append only the source-level printing routines actually referenced by the
    # GenericVM program. Calls are patched after expansion, using final Obscurio
    # instruction addresses rather than GenericVM instruction indexes.
    skip_helpers = None
    if prints_calls or printi_calls or printb_calls:
        # Existing jumps to one-past-the-end resolve to this boundary. Keep that
        # boundary as program termination instead of allowing execution to fall
        # through into a helper that has no call frame.
        obscurio_program.append(ir.OpStackPushLiteral(0))
        skip_helpers = ir.JumpIfZero(0)
        obscurio_program.append(skip_helpers)

    if prints_calls:
        location = len(obscurio_program)
        for call in prints_calls:
            call.location = location
        obscurio_program.extend(prints_helper(location))

    if printb_calls:
        location = len(obscurio_program)
        for call in printb_calls:
            call.location = location
        obscurio_program.extend(printb_helper(location))

    if printi_calls:
        location = len(obscurio_program)
        for call in printi_calls:
            call.location = location
        obscurio_program.extend(printi_helper(location))

    if skip_helpers is not None:
        skip_helpers.location = len(obscurio_program)

    for i, instruction in enumerate(obscurio_program):
        instruction.obfuscate(i)

    return obscurio_program
