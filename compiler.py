
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
    def __init__(self, table: Symbols, built_in_instructions: set, built_in_functions: set):
        self.table = table
        self.instructions = []
        self.context = None
        self.bi_instructions = built_in_instructions
        self.bi_functions = built_in_functions
        self.function_locations = {}
        #todo: Make sure there are no conflicts between built in instructions, functions and user defined functions
        print(self.table.top_level)
        print(self.table.functions)



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

        print("def")
        self.function_locations[node.name] = len(self.instructions)
        print(self.function_locations[node.name])

        self.traverse(node.body)

        self.context = None

    def visit_Return(self, node):

        self.traverse(node.value)

        self.instructions.append(ir.Return())

    def visit_Expr(self, node):
        self.traverse(node.expr)

    def visit_Assign(self, node):
        if isinstance(node.lhs, hr.Subscript):
            raise Exception(f"Subscript assignment not supported yet")

        self.traverse(node.rhs)

        if self.is_name_global(node.lhs.id):
            self.instructions.append(ir.OpStackPopGlobal(self.table.top_level[node.lhs.id].stack_offset))
        else:
            symbol = self.context[node.lhs.id]
            if symbol.is_arg:
                self.instructions.append(ir.OpStackPopArg(symbol.stack_offset))
            else:
                self.instructions.append(ir.OpStackPopLocal(symbol.stack_offset))

    def visit_Break(self, node):
        #todo: implement
        pass

    def visit_Continue(self, node):
        #todo: implement
        pass

    def visit_Pass(self, node):
        pass

    def visit_Call(self, node):
        if node.func in self.table.functions:
            for a in node.args:
                self.traverse(a)
                self.instructions.append(ir.OpStackPopToCallStack())
            #Call contains a string identifying the caller which is later replaced by an address-like index
            self.instructions.append(ir.Call(node.func))
        else:
            #todo: implement the built in functions and instructions
            raise Exception(f"Built in functions and instructions not currently supported")

    def visit_Name(self, node):
        if self.is_name_global(node.id):
            self.instructions.append(ir.OpStackPushGlobal(self.table.top_level[node.id].stack_offset))
        else:
            symbol = self.context[node.id]
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



def compile(ast: hr.Module, table: Symbols, extra_instructions: set, extra_functions: set):
    c = _Compiler(table, extra_instructions, extra_functions)
    c.walk(ast)

    # Loop over all calls replace the functions names with function indices
    for instruction in c.instructions:
        if type(instruction) == ir.Call:
            instruction.location = c.function_locations[instruction.location]

    return c.instructions
