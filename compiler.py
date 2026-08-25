from itertools import count

# The compiler always performs normal lowering. A target InstructionSet is
# checked afterward, alongside its stack-based and immediate built-ins.

import ir
import hr
import ast
import string_runtime
from instruction_set import (
    CompilationResult,
    InstructionOrigin,
    InstructionSet,
    validate_instruction_set,
)
from symbols import Symbols
from typecheck import check_types
from typesystem import BOOL, CHAR, FLOAT, INT, NONE, STR, BuiltinSignature, ClassType, TupleType, word_count

class _InstructionBuffer(list):
    """A list-compatible IR sink which records origin metadata on append."""

    def __init__(self, compiler):
        super().__init__()
        self.compiler = compiler

    def append(self, instruction):
        super().append(instruction)
        node = self.compiler.current_source_node
        span = getattr(node, "source_span", None) if node is not None else None
        construct = self.compiler.construct_name(node)
        self.compiler.origins.append(InstructionOrigin(span, construct) if node else None)


class _Compiler(hr.Walker):
    def __init__(self, table: Symbols, built_in_instructions: dict, built_in_functions: dict):
        self.table = table
        self.current_source_node = None
        self.origins = []
        self.instructions = _InstructionBuffer(self)
        self.context = None
        self.bi_instructions = built_in_instructions
        self.bi_functions = built_in_functions
        self.function_locations = {}
        #todo: Make sure there are no conflicts between built in instructions, functions and user defined functions
        self.breaks = []
        self.continues = []
        self.string_runtime_functions = frozenset()

    @staticmethod
    def construct_name(node):
        if node is None:
            return "compiler-generated instruction"
        names = {
            hr.Constant: "literal",
            hr.List: "list literal",
            hr.Tuple: "tuple expression",
            hr.Call: "function call",
            hr.MethodCall: "method call",
            hr.FunctionDef: "function definition",
            hr.ClassDef: "class definition",
            hr.Assign: "assignment",
            hr.Subscript: "subscript operation",
            hr.Attribute: "field access",
            hr.If: "if statement",
            hr.IfExpr: "conditional expression",
            hr.While: "while loop",
            hr.For: "for loop",
            hr.Return: "return statement",
            hr.Assert: "assert statement",
            hr.BinOp: "operator expression",
            hr.UnaryOp: "unary expression",
            hr.Expr: "expression statement",
        }
        if isinstance(node, hr.Constant) and isinstance(node.value, str):
            return "string literal"
        return names.get(type(node), type(node).__name__)

    def walk(self, node):
        previous = self.current_source_node
        # Compiler-created helper HR nodes have no source span. Attribute their
        # instructions to the surrounding real source construct instead.
        self.current_source_node = (
            node if hasattr(node, "source_span") or previous is None else previous
        )
        try:
            return super().walk(node)
        finally:
            self.current_source_node = previous



    def generic_walk(self, node):
        raise Exception(f"Node '{type(node).__name__}' not implemented for compiler")

    def is_name_global(self, id):
        return (
            id in self.table.top_level
            and (self.context is None or id not in self.context[0])
        )

    def visit_Module(self, node):
        # Check for global variables first
        global_var_count = self.table.count_globals()

        if global_var_count != 0:
            self.instructions.append(ir.GlobalAlloc(global_var_count))

        self.traverse(node.body)

    def visit_ClassDef(self, node):
        self.traverse(node.methods)

    def visit_FunctionDef(self, node):
        if (
            node.name.startswith("__gvm_")
            and node.name not in self.string_runtime_functions
        ):
            return
        skip = ir.Jump(None)

        self.instructions.append(skip)

        qualified_name = node.qualified_name
        self.context = self.table.functions[qualified_name]

        self.function_locations[qualified_name] = len(self.instructions)

        self.instructions.append(ir.LocalAlloc(self.table.count_locals(qualified_name)))

        self.traverse(node.body)

        if node.return_type == NONE and (
            not node.body or not isinstance(node.body[-1], hr.Return)
        ):
            self.instructions.append(ir.Return(self.table.count_arg_words(qualified_name)))

        skip.location = len(self.instructions)

        self.context = None

    def visit_Return(self, node):


        if node.value is not None:
            self.traverse(node.value)

        self.instructions.append(ir.Return(self.table.count_arg_words(self.context[1].qualified_name)))

    def visit_Expr(self, node):
        self.traverse(node.expr)
        preserve_entry_result = (
            self.context is None
            and isinstance(node.expr, hr.Call)
            and node.expr.func == "main"
        )
        if not preserve_entry_result:
            self.emit_projection(word_count(node.expr.type), 0, 0)

    def visit_Assign(self, node):
        if isinstance(node.lhs, hr.TupleTarget):
            self.traverse(node.rhs)
            targets = self.flatten_tuple_target(node.lhs)
            for target in reversed(targets):
                symbol = self.name_symbol(target.id)
                for relative_offset in reversed(range(symbol.word_width)):
                    self.emit_pop_symbol(symbol, relative_offset)
            return

        if isinstance(node.lhs, hr.Subscript):
            #raise Exception(f"Subscript assignment not supported yet")

            self.traverse(node.lhs) # Calculate the index
            self.traverse(node.rhs) # Calculate the rvalue

            self.instructions.append(ir.Store())

            return

        if isinstance(node.lhs, hr.Attribute):
            self.traverse(node.lhs.value)
            field = self.table.classes[node.lhs.resolved_class].fields[node.lhs.attr]
            self.instructions.append(ir.OpStackPushLiteral(field.offset))
            self.instructions.append(ir.IAdd())
            self.traverse(node.rhs)
            self.instructions.append(ir.Store())
            return

        self.traverse(node.rhs)
        symbol = self.name_symbol(node.lhs.id)
        for relative_offset in reversed(range(symbol.word_width)):
            self.emit_pop_symbol(symbol, relative_offset)

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

    def visit_Assert(self, node):
        self.traverse(node.test)
        self.instructions.append(ir.Assert())

    def visit_Call(self, node):
        if hasattr(node, "streamed_class"):
            self.traverse(node.args[0])
            self.emit_streamed_auto_repr(self.table.classes[node.streamed_class])
        elif hasattr(node, "streamed_method"):
            self.traverse(node.args[0])
            self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call(node.streamed_method))
            self.instructions.append(ir.PrintString())
        elif hasattr(node, "resolved_intrinsic"):
            if node.resolved_intrinsic == "len_heap":
                self.traverse(node.args[0])
                self.instructions.append(ir.OpStackPushLiteral(1))
                self.instructions.append(ir.ISub())
                self.instructions.append(ir.Load())
            elif node.resolved_intrinsic == "str_char":
                self.emit_char_string(node.args[0])
            elif node.resolved_intrinsic == "str_alloc":
                self.traverse(node.args[0])
                self.instructions.append(ir.OpStackPushLiteral(1))
                self.instructions.append(ir.IAdd())
                self.instructions.append(ir.Malloc())
                self.instructions.append(ir.Dupe())
                self.traverse(node.args[0])
                self.instructions.append(ir.Store())
                self.instructions.append(ir.OpStackPushLiteral(1))
                self.instructions.append(ir.IAdd())
            elif node.resolved_intrinsic == "str_set":
                self.traverse(node.args[0])
                self.traverse(node.args[1])
                self.instructions.append(ir.IAdd())
                self.traverse(node.args[2])
                self.instructions.append(ir.Store())
            else:
                self.traverse(node.args[0])
        elif hasattr(node, "resolved_runtime"):
            self.traverse(node.args[0])
            self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call(node.resolved_runtime))
        elif hasattr(node, "resolved_builtin"):
            if node.args and isinstance(node.args[0], hr.Call) and hasattr(node.args[0], "auto_repr_class"):
                inner = node.args[0]
                self.traverse(inner.args[0])
                self.emit_streamed_auto_repr(self.table.classes[inner.auto_repr_class])
                return
            if node.args and isinstance(node.args[0], hr.JoinedStr):
                for fragment in node.args[0].values:
                    if isinstance(fragment, hr.FormattedValue):
                        self.emit_streamed_formatted_value(fragment)
                    elif fragment.value:
                        self.traverse(fragment)
                        self.emit_builtin("prints")
                return
            if node.args:
                self.traverse(node.args[0])
            else:
                newline = hr.Constant(node.lineno, "\n")
                newline.type = STR
                self.visit_Constant(newline)
            self.emit_builtin(node.resolved_builtin)
        elif hasattr(node, "auto_repr_class"):
            raise Exception("Automatic class strings may only be streamed by print")
        elif hasattr(node, "resolved_method"):
            self.traverse(node.args[0])
            self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call(node.resolved_method))
        elif node.func in self.table.classes:
            class_info = self.table.classes[node.func]
            constructor = class_info.methods["__init__"]
            self.instructions.append(ir.OpStackPushLiteral(class_info.word_width))
            self.instructions.append(ir.Malloc())
            for argument in reversed(node.args):
                self.traverse(argument)
                for _ in range(word_count(argument.type)):
                    self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Dupe())
            self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call(constructor.qualified_name))
        elif node.func in self.table.functions:

            if self.table.count_args(node.func) != node.expanded_argument_count:
                raise Exception("Typed call argument count changed before code generation")

            for a in reversed(node.args):
                self.traverse(a)
                for _ in range(word_count(a.type)):
                    self.instructions.append(ir.OpStackPopToCallStack())
            #Call contains a string identifying the caller which is later replaced by an address-like index
            self.instructions.append(ir.Call(node.func))
        elif node.func in self.bi_instructions:
            expected_arg_count = len(self.bi_instructions[node.func].parameter_types)

            if expected_arg_count != node.expanded_argument_count:
                raise Exception("Typed built-in argument count changed before code generation")

            self.instructions.append(ir.BuiltInInstruction(node.func, self.traverse(node.args)))
        elif node.func in self.bi_functions:
            expected_arg_count = len(self.bi_functions[node.func].parameter_types)

            if expected_arg_count != node.expanded_argument_count:
                raise Exception("Typed built-in argument count changed before code generation")

            self.instructions.append(ir.BuiltInFunction(node.func, self.traverse(node.args)))
        else:
            #todo: implement the built in functions and instructions
            raise Exception(f"Built in functions and instructions not currently supported '{node.func}'")

    def visit_MethodCall(self, node):
        for argument in reversed(node.args):
            self.traverse(argument)
            for _ in range(word_count(argument.type)):
                self.instructions.append(ir.OpStackPopToCallStack())
        self.traverse(node.receiver)
        self.instructions.append(ir.OpStackPopToCallStack())
        self.instructions.append(ir.Call(node.resolved_method))

    def visit_Attribute(self, node):
        self.traverse(node.value)
        field = self.table.classes[node.resolved_class].fields[node.attr]
        self.instructions.append(ir.OpStackPushLiteral(field.offset))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Load())

    def emit_builtin(self, name):
        if name == "printi":
            self.instructions.append(ir.PrintInt())
        elif name == "printf":
            self.instructions.append(ir.PrintFloat())
        elif name == "printb":
            self.instructions.append(ir.PrintBool())
        elif name == "prints":
            self.instructions.append(ir.PrintString())
        elif name == "printc":
            self.instructions.append(ir.PrintChar())
        elif name in self.bi_instructions:
            self.instructions.append(ir.BuiltInInstruction(name, None))
        elif name in self.bi_functions:
            self.instructions.append(ir.BuiltInFunction(name, None))
        else:
            raise Exception(f"Resolved built-in '{name}' is unavailable")

    def emit_char_string(self, character):
        # Heap layout: [length, character], returned pointer: first character.
        self.instructions.append(ir.OpStackPushLiteral(2))
        self.instructions.append(ir.Malloc())
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.Store())
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.traverse(character)
        self.instructions.append(ir.Store())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())

    def visit_JoinedStr(self, node):
        raise Exception("F-strings may only be streamed directly by print")

    def visit_FormattedValue(self, node):
        raise Exception("Formatted values may only be streamed directly by print")

    def emit_streamed_formatted_value(self, node):
        value_type = node.value.type
        if value_type == INT:
            self.traverse(node.value)
            self.instructions.append(ir.PrintInt())
        elif value_type == FLOAT:
            self.traverse(node.value)
            self.instructions.append(ir.PrintFloat())
        elif value_type == BOOL:
            self.traverse(node.value)
            self.instructions.append(ir.PrintBool())
        elif value_type == STR:
            self.traverse(node.value)
            self.instructions.append(ir.PrintString())
        elif value_type == CHAR:
            self.traverse(node.value)
            self.instructions.append(ir.PrintChar())
        elif isinstance(value_type, ClassType):
            self.traverse(node.value)
            if hasattr(node, "resolved_method"):
                self.instructions.append(ir.OpStackPopToCallStack())
                self.instructions.append(ir.Call(node.resolved_method))
                self.instructions.append(ir.PrintString())
            elif hasattr(node, "auto_repr_class"):
                self.emit_streamed_auto_repr(self.table.classes[node.auto_repr_class])
            else:
                raise Exception(f"No string representation for {value_type}")
        else:
            raise Exception(f"Cannot stream formatted value of type {value_type}")

    def emit_streamed_auto_repr(self, class_info):
        prefix = hr.Constant(class_info.definition.lineno, f"{class_info.name}(")
        prefix.type = STR
        self.visit_Constant(prefix)
        self.instructions.append(ir.PrintString())
        for index, field in enumerate(class_info.fields.values()):
            if index:
                separator = hr.Constant(class_info.definition.lineno, ", ")
                separator.type = STR
                self.visit_Constant(separator)
                self.instructions.append(ir.PrintString())

            self.instructions.append(ir.Dupe())
            self.instructions.append(ir.OpStackPushLiteral(field.offset))
            self.instructions.append(ir.IAdd())
            self.instructions.append(ir.Load())
            self.emit_streamed_value(field.type)

        suffix = hr.Constant(class_info.definition.lineno, ")")
        suffix.type = STR
        self.visit_Constant(suffix)
        self.instructions.append(ir.PrintString())
        self.instructions.append(ir.Drop(1))

    def emit_streamed_value(self, value_type):
        if value_type == STR:
            self.instructions.append(ir.PrintString())
        elif value_type == CHAR:
            self.instructions.append(ir.PrintChar())
        elif value_type == INT:
            self.instructions.append(ir.PrintInt())
        elif value_type == FLOAT:
            self.instructions.append(ir.PrintFloat())
        elif value_type == BOOL:
            self.instructions.append(ir.PrintBool())
        elif isinstance(value_type, ClassType):
            class_info = self.table.classes[value_type.name]
            method = class_info.methods.get("__str__") or class_info.methods.get("__repr__")
            if method is not None:
                self.instructions.append(ir.OpStackPopToCallStack())
                self.instructions.append(ir.Call(method.qualified_name))
                self.instructions.append(ir.PrintString())
            else:
                self.emit_streamed_auto_repr(class_info)
        else:
            raise Exception(f"Cannot automatically stream {value_type}")

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

    def visit_For(self, node):
        # 1. Make sure the Forloop is suitable - target is just a Name, iter is just a range, etc.
        # 2. Get the start, stop and end for the given range
        # 3. Initialise the variable with the start value
        symbol = self.context[0][node.assignable.id]
        if isinstance(node.start, int):
            self.instructions.append(ir.OpStackPushLiteral(node.start))
        else:
            self.traverse(node.start)

        if symbol.is_arg:
            self.instructions.append(ir.OpStackPopArg(symbol.stack_offset))
        else:
            self.instructions.append(ir.OpStackPopLocal(symbol.stack_offset))
        # 4. Insert a loop label
        loop_location = len(self.instructions)
        # 5. If Target variable >= stop, goto done label
        done = ir.JumpIfFalse(None)

        if symbol.is_arg:
            self.instructions.append(ir.OpStackPushArg(symbol.stack_offset))
        else:
            self.instructions.append(ir.OpStackPushLocal(symbol.stack_offset))

        self.traverse(node.end)

        self.instructions.append(ir.LessThan())

        self.instructions.append(done)

        # 6. Body of loop
        self.traverse(node.body)

        # 7. Add step to i
        if symbol.is_arg:
            self.instructions.append(ir.OpStackPushArg(symbol.stack_offset))
        else:
            self.instructions.append(ir.OpStackPushLocal(symbol.stack_offset))

        if isinstance(node.step, int):
            self.instructions.append(ir.OpStackPushLiteral(node.step))
        else:
            self.traverse(node.step)

        self.instructions.append(ir.IAdd())

        if symbol.is_arg:
            self.instructions.append(ir.OpStackPopArg(symbol.stack_offset))
        else:
            self.instructions.append(ir.OpStackPopLocal(symbol.stack_offset))

        # 8. Goto loop label
        self.instructions.append(ir.Jump(loop_location))

        # 9. Insert done label

        done.location = len(self.instructions)





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




    def visit_IfExpr(self, node):
        end = ir.JumpIfFalse(None)

        self.traverse(node.condition)

        self.instructions.append(end)

        self.traverse(node.true_expr)

        end.location = len(self.instructions) + 1

        else_jump = ir.Jump(None)

        self.instructions.append(else_jump)

        self.traverse(node.false_expr)

        else_jump.location = len(self.instructions)


    def visit_Name(self, node):
        symbol = self.name_symbol(node.id)
        for relative_offset in range(symbol.word_width):
            self.emit_push_symbol(symbol, relative_offset)

    def visit_Subscript(self, node):

        if isinstance(node.value.type, TupleType):
            self.traverse(node.value)
            self.emit_projection(
                node.projection_total_width,
                node.projection_offset,
                node.projection_width,
            )
            return

        self.traverse(node.value)
        self.traverse(node.slice)
        self.instructions.append(ir.IAdd())

        if type(node.context) is ast.Load:
            self.instructions.append(ir.Load())


    def visit_List(self, node):
        # First we call malloc which pushes the ptr on the op stack
        self.instructions.append(ir.OpStackPushLiteral(len(node.elements) + 1))
        self.instructions.append(ir.Malloc())

        # First u64 contains the length of string
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(len(node.elements)))
        self.instructions.append(ir.Store())

        for i, v in enumerate(node.elements):
            self.instructions.append(ir.Dupe())
            self.instructions.append(ir.OpStackPushLiteral(i + 1))
            self.instructions.append(ir.IAdd())

            self.traverse(v)

            self.instructions.append(ir.Store())

        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())

    def visit_Tuple(self, node):
        self.traverse(node.elements)

    def visit_Starred(self, node):
        self.traverse(node.value)

    def visit_Constant(self, node):

        if type(node.value) is str and node.type == CHAR:
            self.instructions.append(ir.OpStackPushLiteral(ord(node.value)))

        elif type(node.value) is str:

            # First we call malloc which pushes the ptr on the op stack
            self.instructions.append(ir.OpStackPushLiteral(len(node.value) + 1))
            self.instructions.append(ir.Malloc())

            # First u64 contains the length of string
            self.instructions.append(ir.Dupe())
            self.instructions.append(ir.OpStackPushLiteral(len(node.value)))
            self.instructions.append(ir.Store())

            for i, c in enumerate(node.value):
                self.instructions.append(ir.Dupe())
                self.instructions.append(ir.OpStackPushLiteral(i+1))
                self.instructions.append(ir.IAdd())
                self.instructions.append(ir.OpStackPushLiteral(ord(c)))
                self.instructions.append(ir.Store())

            # Bit unorthodox, but the returned pointer points to the start of the list, so skip past the stored length
            self.instructions.append(ir.OpStackPushLiteral(1))
            self.instructions.append(ir.IAdd())

        elif node.value is not None:
            literal = (
                float(node.value)
                if node.type == FLOAT and type(node.value) is int
                else node.value
            )
            self.instructions.append(ir.OpStackPushLiteral(literal))

    def name_symbol(self, identifier):
        if self.context is not None and identifier in self.context[0]:
            return self.context[0][identifier]
        return self.table.top_level[identifier]

    def emit_push_symbol(self, symbol, relative_offset):
        offset = symbol.stack_offset + relative_offset
        if symbol.is_global:
            self.instructions.append(ir.OpStackPushGlobal(offset))
        elif symbol.is_arg:
            self.instructions.append(ir.OpStackPushArg(offset))
        else:
            self.instructions.append(ir.OpStackPushLocal(offset))

    def emit_pop_symbol(self, symbol, relative_offset):
        offset = symbol.stack_offset + relative_offset
        if symbol.is_global:
            self.instructions.append(ir.OpStackPopGlobal(offset))
        elif symbol.is_arg:
            self.instructions.append(ir.OpStackPopArg(offset))
        else:
            self.instructions.append(ir.OpStackPopLocal(offset))

    def emit_projection(self, total_width, offset, selected_width):
        if total_width == selected_width and offset == 0:
            return

        suffix_width = total_width - offset - selected_width
        if min(total_width, offset, selected_width, suffix_width) < 0:
            raise Exception("Invalid operand-stack projection layout")

        if suffix_width:
            self.instructions.append(ir.Drop(suffix_width))

        for _ in range(offset):
            self.instructions.append(ir.Roll(selected_width))
            self.instructions.append(ir.Drop(1))

    def flatten_tuple_target(self, target):
        flattened = []
        for element in target.elements:
            if isinstance(element, hr.TupleTarget):
                flattened.extend(self.flatten_tuple_target(element))
            else:
                flattened.append(element)
        return flattened

    def visit_BinOp(self, node):

        if node.type is None or not hasattr(node, "operand_type"):
            raise Exception("Compiler received an unresolved binary expression")

        if hasattr(node, "resolved_method"):
            operand = node.left if node.resolved_reverse else node.right
            receiver = node.right if node.resolved_reverse else node.left
            self.traverse(operand)
            for _ in range(word_count(operand.type)):
                self.instructions.append(ir.OpStackPopToCallStack())
            self.traverse(receiver)
            self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call(node.resolved_method))
            return

        op = type(node.operator)
        if op in {ast.In, ast.NotIn} and node.right_type == STR:
            needle = node.left
            if node.left_type == CHAR:
                self.emit_char_string(needle)
            else:
                self.traverse(needle)
            self.instructions.append(ir.OpStackPopToCallStack())
            self.traverse(node.right)
            self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call("__gvm_str_find"))
            self.instructions.append(ir.OpStackPushLiteral(-1))
            self.instructions.append((ir.NotEqual if op is ast.In else ir.Equal)())
            return
        if node.left_type == STR and node.right_type == STR and op in {
            ast.Eq, ast.NotEq, ast.Lt, ast.Gt, ast.LtE, ast.GtE,
        }:
            for argument in (node.right, node.left):
                self.traverse(argument)
                self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call("__gvm_str_compare"))
            self.instructions.append(ir.OpStackPushLiteral(0))
            comparisons = {
                ast.Eq: ir.Equal, ast.NotEq: ir.NotEqual,
                ast.Lt: ir.LessThan, ast.Gt: ir.GreaterThan,
                ast.LtE: ir.LessThanEqualTo, ast.GtE: ir.GreaterThanEqualTo,
            }
            self.instructions.append(comparisons[op]())
            return
        if node.type == STR and op in {ast.Add, ast.Mult}:
            if op is ast.Add:
                arguments = (node.left, node.right)
                runtime = "__gvm_str_concat"
            elif node.left_type == STR:
                arguments = (node.left, node.right)
                runtime = "__gvm_str_repeat"
            else:
                arguments = (node.right, node.left)
                runtime = "__gvm_str_repeat"
            for argument in reversed(arguments):
                if op is ast.Add and argument.type == CHAR:
                    self.emit_char_string(argument)
                else:
                    self.traverse(argument)
                self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call(runtime))
            return

        self.traverse(node.left)
        if node.operand_type == FLOAT and node.left_type == INT:
            self.instructions.append(ir.IntToFloat())
        self.traverse(node.right)
        if node.operand_type == FLOAT and node.right_type == INT:
            self.instructions.append(ir.IntToFloat())

        op = type(node.operator)
        integer_numeric = {
            ast.Add: ir.IAdd,
            ast.Mult: ir.IMultiply,
            ast.Sub: ir.ISub,
        }
        floating_numeric = {
            ast.Add: ir.FAdd,
            ast.Mult: ir.FMultiply,
            ast.Sub: ir.FSub,
        }
        comparisons = {
            ast.Lt: ir.LessThan,
            ast.Gt: ir.GreaterThan,
            ast.LtE: ir.LessThanEqualTo,
            ast.GtE: ir.GreaterThanEqualTo,
        }
        integer = {
            ast.BitAnd: ir.And,
            ast.BitOr: ir.Or,
            ast.BitXor: ir.Xor,
            ast.LShift: ir.ShiftLeft,
            ast.RShift: ir.ShiftRight,
        }
        logical = {ast.And: ir.LogicalAnd, ast.Or: ir.LogicalOr}
        equality = {ast.Eq: ir.Equal, ast.NotEq: ir.NotEqual}

        if op in integer_numeric and node.operand_type == INT:
            instruction = integer_numeric[op]
        elif op in floating_numeric and node.operand_type == FLOAT:
            instruction = floating_numeric[op]
        elif op in comparisons and node.operand_type in {INT, FLOAT, CHAR}:
            instruction = comparisons[op]
        elif op in integer and node.operand_type == INT:
            instruction = integer[op]
        elif op in logical and node.operand_type == BOOL:
            instruction = logical[op]
        elif op in equality and node.operand_type in {INT, FLOAT, BOOL, CHAR}:
            instruction = equality[op]
        else:
            raise Exception(
                f"No VM instruction for {node.operand_type} {op.__name__} "
                f"(line: {node.lineno})"
            )

        self.instructions.append(instruction())

    def visit_UnaryOp(self, node):

        if node.type is None or not hasattr(node, "operand_type"):
            raise Exception("Compiler received an unresolved unary expression")

        if hasattr(node, "resolved_method"):
            self.traverse(node.operand)
            self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call(node.resolved_method))
            return

        self.traverse(node.operand)

        op = type(node.operator)
        typed_operations = {
            (ast.Invert, INT): ir.OnesComplement,
            (ast.Not, BOOL): ir.LogicalNot,
            (ast.UAdd, INT): ir.IUnaryPositive,
            (ast.UAdd, FLOAT): ir.FUnaryPositive,
            (ast.USub, INT): ir.IUnaryNegative,
            (ast.USub, FLOAT): ir.FUnaryNegative,
        }
        instruction = typed_operations.get((op, node.operand_type))
        if instruction is None:
            raise Exception(
                f"No VM instruction for {op.__name__} {node.operand_type} "
                f"(line: {node.lineno})"
            )
        self.instructions.append(instruction())



def compile(
    ast: hr.Module,
    table: Symbols,
    extra_instructions: dict | None = None,
    extra_functions: dict | None = None,
    instruction_set: InstructionSet | None = None,
):
    if not getattr(ast, "_string_runtime_added", False):
        ast.body.extend(string_runtime.runtime_definitions())
        ast._string_runtime_added = True
        rebuilt = Symbols(ast)
        table.__dict__.clear()
        table.__dict__.update(rebuilt.__dict__)
    extra_instructions = extra_instructions or {}
    extra_functions = extra_functions or {}
    if instruction_set is not None:
        for name, signature in extra_instructions.items():
            configured = instruction_set.builtin_instructions.get(name)
            if configured is not None and configured != signature:
                raise ValueError(f"Built-in instruction '{name}' disagrees with the target instruction set")
            if name in instruction_set.builtin_functions:
                raise ValueError(f"Built-in '{name}' has conflicting calling conventions")
        for name, signature in extra_functions.items():
            configured = instruction_set.builtin_functions.get(name)
            if configured is not None and configured != signature:
                raise ValueError(f"Built-in function '{name}' disagrees with the target instruction set")
            if name in instruction_set.builtin_instructions:
                raise ValueError(f"Built-in '{name}' has conflicting calling conventions")
        extra_instructions = {**instruction_set.builtin_instructions, **extra_instructions}
        extra_functions = {**instruction_set.builtin_functions, **extra_functions}
    builtins = {**extra_instructions, **extra_functions}
    for name, signature in builtins.items():
        if not isinstance(signature, BuiltinSignature):
            raise TypeError(
                f"Built-in instruction '{name}' must use BuiltinSignature, "
                f"not {type(signature).__name__}"
            )

    check_types(ast, table, builtins)
    table.calculate_layouts()
    c = _Compiler(table, extra_instructions, extra_functions)
    c.string_runtime_functions = string_runtime.required_functions(ast)
    c.walk(ast)

    # Loop over all calls replace the functions names with function indices
    for instruction in c.instructions:
        if type(instruction) == ir.Call:
            instruction.location = c.function_locations[instruction.location]

    result = CompilationResult(list(c.instructions), c.origins)
    if instruction_set is not None:
        validate_instruction_set(result, instruction_set)
    return result


def compile_source(
    source: str,
    *,
    filename: str = "<source>",
    instruction_set: InstructionSet | None = None,
    extra_instructions: dict | None = None,
    extra_functions: dict | None = None,
):
    """Parse, analyse, compile, and target-check source with rich locations."""
    python_ast = ast.parse(source, filename)
    module = hr.ast_to_hr(python_ast, source=source, filename=filename)
    table = Symbols(module)
    return compile(
        module, table, extra_instructions, extra_functions,
        instruction_set=instruction_set,
    )
