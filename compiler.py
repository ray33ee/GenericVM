from itertools import count

# Compiler needs the following:
# - A list of features supported by the language
# - A list of constants
# - A list of built-in functions (using the op stack)
# - A list of built-in functions (using constant immediates, no op stack)

import ir
import hr
import ast
from symbols import Symbols

class _Compiler(hr.Walker):
    def __init__(self, table: Symbols, built_in_instructions: dict, built_in_functions: dict):
        self.table = table
        self.instructions = []
        self.context = None
        self.bi_instructions = built_in_instructions
        self.bi_functions = built_in_functions
        self.function_locations = {}
        #todo: Make sure there are no conflicts between built in instructions, functions and user defined functions
        print(self.table.top_level)
        print(self.table.functions)

        self.breaks = []
        self.continues = []



    def generic_walk(self, node):
        raise Exception(f"Node {type(node).__name__} not implemented for compiler")

    def is_name_global(self, id):
        return id in self.table.top_level

    def visit_Module(self, node):
        # Check for global variables first
        global_var_count = len(self.table.top_level)

        if global_var_count != 0:
            self.instructions.append(ir.GlobalAlloc(global_var_count))

        self.traverse(node.body)

    def visit_FunctionDef(self, node):
        self.context = self.table.functions[node.name]

        self.function_locations[node.name] = len(self.instructions)

        self.instructions.append(ir.LocalAlloc(self.table.count_locals(node.name)))

        self.traverse(node.body)

        self.context = None

    def visit_Return(self, node):


        if node.value is not None:
            self.traverse(node.value)

        self.instructions.append(ir.Return(len(self.context[1].args)))

    def visit_Expr(self, node):
        self.traverse(node.expr)

    def visit_Assign(self, node):
        if isinstance(node.lhs, hr.Subscript):
            raise Exception(f"Subscript assignment not supported yet")

        self.traverse(node.rhs)

        if self.is_name_global(node.lhs.id):
            self.instructions.append(ir.OpStackPopGlobal(self.table.top_level[node.lhs.id].stack_offset))
        else:
            symbol = self.context[0][node.lhs.id]
            if symbol.is_arg:
                self.instructions.append(ir.OpStackPopArg(symbol.stack_offset))
            else:
                self.instructions.append(ir.OpStackPopLocal(symbol.stack_offset))

    def visit_Break(self, node):
        b = ir.Jump(None)
        self.instructions.append(b)
        self.breaks.append(b)

    def visit_Continue(self, node):
        b = ir.Jump(None)
        self.instructions.append(b)
        self.continues.append(b)

    def visit_Pass(self, node):
        pass

    def visit_Call(self, node):
        if node.func in self.table.functions:

            #todo: make sure that the number of args in self.table.functions[node.func] matches len(node.args)
            if self.table.count_args(node.func) != len(node.args):
                raise Exception(f"User defined function '{node.func}' expects {self.table.count_args(node.func)} args, found {len(node.args)}. (lineno: {node.lineno})")

            for a in reversed(node.args):
                self.traverse(a)
                self.instructions.append(ir.OpStackPopToCallStack())
            #Call contains a string identifying the caller which is later replaced by an address-like index
            self.instructions.append(ir.Call(node.func))
        elif node.func in self.bi_instructions:
            expected_arg_count = self.bi_instructions[node.func]

            if expected_arg_count != len(node.args):
                raise Exception(f"Built in instruction '{node.func}' expects {expected_arg_count} args, found {len(node.args)}. (lineno: {node.lineno})")

            self.instructions.append(ir.BuiltInInstruction(node.func, self.traverse(node.args)))
        else:
            #todo: implement the built in functions and instructions
            raise Exception(f"Built in functions and instructions not currently supported")

    def visit_If(self, node):
        end = ir.JumpIfFalse(None)

        self.traverse(node.condition)

        self.instructions.append(end)

        self.traverse(node.body)

        end.location = len(self.instructions)

        if len(node.orelse) != 0 and node.orelse is not None:
            else_jump = ir.Jump(None)
            end.location += 1

            self.instructions.append(else_jump)

            self.traverse(node.orelse)

            else_jump.location = len(self.instructions)


    def visit_While(self, node):
        condition_jump = ir.JumpIfFalse(None)

        start_location = len(self.instructions)

        self.traverse(node.condition)

        self.instructions.append(condition_jump)

        self.traverse(node.body)

        self.instructions.append(ir.Jump(start_location))

        condition_jump.location = len(self.instructions)

        if len(node.orelse) != 0 and node.orelse is not None:
            self.traverse(node.orelse)

        break_location = len(self.instructions)

        for breaker in self.breaks:
            breaker.location = break_location

        self.breaks = []

        for continuer in self.continues:
            continuer.location = start_location

        self.continues = []








    def visit_Name(self, node):
        if self.is_name_global(node.id):
            self.instructions.append(ir.OpStackPushGlobal(self.table.top_level[node.id].stack_offset))
        else:
            symbol = self.context[0][node.id]
            if symbol.is_arg:
                self.instructions.append(ir.OpStackPushArg(symbol.stack_offset))
            else:
                self.instructions.append(ir.OpStackPushLocal(symbol.stack_offset))

    def visit_Constant(self, node):
        self.instructions.append(ir.OpStackPushLiteral(node.value))

    def visit_BinOp(self, node):

        self.traverse(node.left)
        self.traverse(node.right)

        op = type(node.operator)
        if op == ast.Add:
            self.instructions.append(ir.Add())
        elif op == ast.Mult:
            self.instructions.append(ir.Multiply())
        elif op == ast.Sub:
            self.instructions.append(ir.Sub())
        elif op == ast.Eq:
            self.instructions.append(ir.Equal())
        elif op == ast.NotEq:
            self.instructions.append(ir.NotEqual())
        elif op == ast.Lt:
            self.instructions.append(ir.LessThan())
        elif op == ast.Gt:
            self.instructions.append(ir.GreaterThan())
        elif op == ast.LtE:
            self.instructions.append(ir.LessThanEqualTo())
        elif op == ast.GtE:
            self.instructions.append(ir.GreaterThanEqualTo())
        else:
            #todo: Add support for remaining binops
            raise Exception(f"Bin op {op.__name__} is not supported yet")

    def visit_UnaryOp(self, node):

        self.traverse(node.operand)

        op = type(node.operator)
        if op == ast.Invert:
            self.instructions.append(ir.OnesComplement())
        elif op == ast.Not:
            self.instructions.append(ir.LogicalNot())
        elif op == ast.UAdd:
            self.instructions.append(ir.UnaryPositive())
        elif op == ast.USub:
            self.instructions.append(ir.UnaryNegative())
        else:
            raise Exception(f"Invalid unary op {op.__name__}")



def compile(ast: hr.Module, table: Symbols, extra_instructions: dict, extra_functions: dict):
    c = _Compiler(table, extra_instructions, extra_functions)
    c.walk(ast)

    # Loop over all calls replace the functions names with function indices
    for instruction in c.instructions:
        if type(instruction) == ir.Call:
            instruction.location = c.function_locations[instruction.location]

    return c.instructions
