
import ir

def bytecode(instructions: list[ir.Instruction], builtin_instructions):

    binary = []

    for instruction in instructions:

        if hasattr(instruction, "OPCODE"):
            if hasattr(instruction, "value"):
                bytecode = (instruction.OPCODE, instruction.value)
            elif hasattr(instruction, "offset"):
                bytecode = (instruction.OPCODE, instruction.offset)
            elif hasattr(instruction, "location"):
                bytecode = (instruction.OPCODE, instruction.location)
            elif hasattr(instruction, "arg_count"):
                bytecode = (instruction.OPCODE, instruction.arg_count)
            elif hasattr(instruction, "variable_count"):
                bytecode = (instruction.OPCODE, instruction.variable_count)
            else:
                bytecode = (instruction.OPCODE, 0)

            binary.append(bytecode)
        elif isinstance(instruction, ir.BuiltInInstruction):
            binary.append((builtin_instructions[instruction.name][1], 0))
        else:
            pass

    return binary