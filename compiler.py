from itertools import count

# The compiler always performs normal lowering. A target InstructionSet is
# checked afterward, alongside its stack-based and immediate built-ins.

import ir
import hr
import ast
import re
import list_runtime
import string_runtime
from instruction_set import (
    CompilationResult,
    InstructionOrigin,
    InstructionSet,
    validate_instruction_set,
)
from symbols import Symbols
from typecheck import check_types
from typesystem import BOOL, CHAR, FLOAT, INT, NONE, PTR, STR, BuiltinSignature, ClassType, ListType, TupleType, word_count

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
        self.loop_contexts = []
        self.runtime_functions = frozenset()

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
            and node.name not in self.runtime_functions
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
        retained = sum(context["retained_words"] for context in self.loop_contexts)
        if retained:
            self.instructions.append(ir.Drop(retained))
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
            self.traverse(node.lhs)
            self.traverse(node.rhs)
            self.emit_store_words(word_count(node.lhs.type))
            return

        if isinstance(node.lhs, hr.Attribute):
            self.traverse(node.lhs.value)
            field = self.table.classes[node.lhs.resolved_class].fields[node.lhs.attr]
            self.instructions.append(ir.OpStackPushLiteral(field.offset))
            self.instructions.append(ir.IAdd())
            self.traverse(node.rhs)
            self.emit_store_words(field.word_width)
            return

        self.traverse(node.rhs)
        symbol = self.name_symbol(node.lhs.id)
        for relative_offset in reversed(range(symbol.word_width)):
            self.emit_pop_symbol(symbol, relative_offset)

    def visit_Break(self, node):
        if not self.loop_contexts:
            raise Exception("break outside loop")
        context = self.loop_contexts[-1]
        if context["retained_words"]:
            self.instructions.append(ir.Drop(context["retained_words"]))
        b = ir.Jump(None)
        self.instructions.append(b)
        context["breaks"].append(b)

    def visit_Continue(self, node):
        if not self.loop_contexts:
            raise Exception("continue outside loop")
        b = ir.Jump(None)
        self.instructions.append(b)
        self.loop_contexts[-1]["continues"].append(b)

    def visit_Pass(self, node):
        pass

    def visit_Assert(self, node):
        self.traverse(node.test)
        self.instructions.append(ir.Assert())

    def visit_Call(self, node):
        if hasattr(node, "print_end"):
            self.emit_print(node)
            return
        if hasattr(node, "resolved_list_print"):
            self.traverse(node.args[0])
            self.emit_streamed_list(node.args[0].type.element_type)
        elif hasattr(node, "streamed_class"):
            self.traverse(node.args[0])
            self.emit_streamed_auto_repr(self.table.classes[node.streamed_class])
        elif hasattr(node, "streamed_method"):
            self.traverse(node.args[0])
            self.instructions.append(ir.OpStackPopToCallStack())
            self.instructions.append(ir.Call(node.streamed_method))
            self.instructions.append(ir.PrintString())
        elif hasattr(node, "resolved_intrinsic"):
            if node.resolved_intrinsic == "cast_str":
                self.traverse(node.args)
            elif node.resolved_intrinsic in {"cast_int", "cast_ptr"}:
                self.traverse(node.args[0])
                if getattr(node, "cast_source_type", None) == STR:
                    self.instructions.append(ir.Drop(1))
            elif node.resolved_intrinsic == "malloc":
                self.traverse(node.args[0])
                self.instructions.append(ir.Malloc())
            elif node.resolved_intrinsic == "free":
                self.traverse(node.args[0])
                self.instructions.append(ir.Free())
            elif node.resolved_intrinsic == "input":
                self.traverse(node.args[0])
                self.instructions.append(ir.Dupe())
                self.instructions.append(ir.Malloc())
                self.instructions.append(ir.Roll(1))
                self.instructions.append(ir.Input())
            elif node.resolved_intrinsic == "len_string":
                self.traverse(node.args[0])
                self.instructions.append(ir.Roll(1))
                self.instructions.append(ir.Drop(1))
            elif node.resolved_intrinsic == "len_heap":
                self.traverse(node.args[0])
                self.instructions.append(ir.OpStackPushLiteral(1))
                self.instructions.append(ir.IAdd())
                self.instructions.append(ir.Load())
            elif node.resolved_intrinsic == "str_char":
                self.emit_char_string(node.args[0])
            elif node.resolved_intrinsic == "str_alloc":
                self.traverse(node.args[0])
                self.instructions.append(ir.Dupe())
                self.instructions.append(ir.Malloc())
                self.instructions.append(ir.Roll(1))
            elif node.resolved_intrinsic == "str_set":
                self.traverse(node.args[0])
                self.instructions.append(ir.Drop(1))
                self.traverse(node.args[1])
                self.instructions.append(ir.IAdd())
                self.traverse(node.args[2])
                self.instructions.append(ir.Store())
            elif node.resolved_intrinsic == "bool_int":
                self.traverse(node.args[0])
                self.instructions.append(ir.OpStackPushLiteral(0))
                self.instructions.append(ir.NotEqual())
            elif node.resolved_intrinsic == "int_bool":
                self.traverse(node.args[0])
                self.instructions.append(ir.OpStackPushLiteral(0))
                self.instructions.append(ir.IAdd())
            elif node.resolved_intrinsic == "bool_str":
                self.traverse(node.args[0])
                self.instructions.append(ir.Roll(1))
                self.instructions.append(ir.Drop(1))
                self.instructions.append(ir.OpStackPushLiteral(0))
                self.instructions.append(ir.NotEqual())
            else:
                self.traverse(node.args[0])
        elif hasattr(node, "resolved_runtime"):
            self.traverse(node.args[0])
            self.emit_value_to_call_stack(node.args[0].type)
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
            self.emit_value_to_call_stack(node.args[0].type)
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

    def emit_print(self, node):
        if node.args:
            value = node.args[0]
            if hasattr(node, "resolved_list_print"):
                self.traverse(value)
                self.emit_streamed_list(value.type.element_type)
            elif hasattr(node, "resolved_tuple_print"):
                self.traverse(value)
                self.emit_streamed_tuple(value.type)
            elif hasattr(node, "streamed_class"):
                self.traverse(value)
                self.emit_streamed_auto_repr(self.table.classes[node.streamed_class])
            elif hasattr(node, "streamed_method"):
                self.traverse(value)
                self.instructions.append(ir.OpStackPopToCallStack())
                self.instructions.append(ir.Call(node.streamed_method))
                self.instructions.append(ir.PrintString())
            elif isinstance(value, hr.Call) and hasattr(value, "auto_repr_class"):
                self.traverse(value.args[0])
                self.emit_streamed_auto_repr(self.table.classes[value.auto_repr_class])
            elif isinstance(value, hr.JoinedStr):
                for fragment in value.values:
                    if isinstance(fragment, hr.FormattedValue):
                        self.emit_streamed_formatted_value(fragment)
                    elif fragment.value:
                        self.traverse(fragment)
                        self.emit_builtin("prints")
            else:
                self.traverse(value)
                self.emit_builtin(node.resolved_builtin)

        self.traverse(node.print_end)
        self.emit_builtin("prints")

    def visit_MethodCall(self, node):
        if hasattr(node, "contains_element_type"):
            self.emit_list_contains(node)
            return
        if getattr(node, "contains_char", False):
            self.emit_char_string(node.args[0])
            self.emit_value_to_call_stack(STR)
            self.traverse(node.receiver)
            self.emit_value_to_call_stack(STR)
            self.instructions.append(ir.Call(node.resolved_method))
            return
        if hasattr(node, "resolved_list_method"):
            arguments = list(node.args)
            if node.method == "pop" and not arguments:
                default_index = hr.Constant(node.lineno, -1)
                default_index.type = INT
                arguments = [default_index]
            for argument in reversed(arguments):
                self.traverse(argument)
                self.emit_value_to_call_stack(argument.type)
            self.traverse(node.receiver)
            self.emit_value_to_call_stack(node.receiver.type)
            self.instructions.append(ir.Call(node.resolved_list_method))
            return
        for argument in reversed(node.args):
            self.traverse(argument)
            for _ in range(word_count(argument.type)):
                self.instructions.append(ir.OpStackPopToCallStack())
        self.traverse(node.receiver)
        self.emit_value_to_call_stack(node.receiver.type)
        self.instructions.append(ir.Call(node.resolved_method))

    def emit_list_contains(self, node):
        """Keep [needle, descriptor, index] on the stack while searching."""
        width = word_count(node.contains_element_type)
        self.traverse(node.args[0])
        self.traverse(node.receiver)
        self.instructions.append(ir.OpStackPushLiteral(0))
        condition = len(self.instructions)
        self.instructions.append(ir.Dupe())
        self.emit_dupe_at_depth(2)
        for instruction in [ir.OpStackPushLiteral(1), ir.IAdd(), ir.Load(), ir.LessThan()]:
            self.instructions.append(instruction)
        exhausted = ir.JumpIfFalse(None)
        self.instructions.append(exhausted)
        # Copy the needle, then load the current element, for equality.
        for _ in range(width):
            self.emit_dupe_at_depth(width + 1)
        self.emit_dupe_at_depth(width + 1)
        self.instructions.append(ir.Load())
        self.emit_dupe_at_depth(width + 1)
        for instruction in [ir.OpStackPushLiteral(width), ir.IMultiply(), ir.IAdd()]:
            self.instructions.append(instruction)
        self.emit_load_words(width)
        comparison = node.contains_comparison
        if node.contains_element_type == STR or hasattr(comparison, "resolved_method"):
            if hasattr(comparison, "resolved_method"):
                self.instructions.append(ir.Roll(1))
            self.emit_value_to_call_stack(node.contains_element_type)
            self.emit_value_to_call_stack(node.contains_element_type)
            method = getattr(comparison, "resolved_method", "__gvm_str_compare")
            self.instructions.append(ir.Call(method))
            if node.contains_element_type == STR:
                for instruction in [ir.OpStackPushLiteral(0), ir.Equal()]:
                    self.instructions.append(instruction)
        else:
            self.instructions.append(ir.Equal())
        next_item = ir.JumpIfFalse(None)
        self.instructions.append(next_item)
        for instruction in [ir.Drop(width + 2), ir.OpStackPushLiteral(1)]:
            self.instructions.append(instruction)
        done = ir.Jump(None)
        self.instructions.append(done)
        next_item.location = len(self.instructions)
        for instruction in [ir.OpStackPushLiteral(1), ir.IAdd(), ir.Jump(condition)]:
            self.instructions.append(instruction)
        exhausted.location = len(self.instructions)
        for instruction in [ir.Drop(width + 2), ir.OpStackPushLiteral(0)]:
            self.instructions.append(instruction)
        done.location = len(self.instructions)

    def visit_Attribute(self, node):
        self.traverse(node.value)
        field = self.table.classes[node.resolved_class].fields[node.attr]
        self.instructions.append(ir.OpStackPushLiteral(field.offset))
        self.instructions.append(ir.IAdd())
        self.emit_load_words(field.word_width)

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

    def emit_value_to_call_stack(self, value_type):
        for _ in range(word_count(value_type)):
            self.instructions.append(ir.OpStackPopToCallStack())

    def emit_load_words(self, width):
        """Replace an address with its contiguous flattened value words."""
        for _ in range(width):
            self.instructions.append(ir.Dupe())
            self.instructions.append(ir.Load())
            self.instructions.append(ir.Roll(1))
            self.instructions.append(ir.OpStackPushLiteral(1))
            self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Drop(1))

    def emit_store_words(self, width):
        """Consume [address, value words...] and store the flattened value."""
        for offset in reversed(range(1, width)):
            self.instructions.append(ir.Roll(offset + 1))
            self.instructions.append(ir.Dupe())
            self.instructions.append(ir.OpStackPushLiteral(offset))
            self.instructions.append(ir.IAdd())
            self.instructions.append(ir.Roll(2))
            self.instructions.append(ir.Store())
            # STORE leaves the preserved base address above the remaining
            # value words. Rotate it back underneath them for the next store.
            for _ in range(offset):
                self.instructions.append(ir.Roll(offset))
        self.instructions.append(ir.Store())

    def emit_char_string(self, character):
        # String values are flattened as [pointer, length].
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.Malloc())
        self.instructions.append(ir.Dupe())
        self.traverse(character)
        self.instructions.append(ir.Store())
        self.instructions.append(ir.OpStackPushLiteral(1))

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
        elif isinstance(value_type, TupleType):
            self.traverse(node.value)
            self.emit_streamed_tuple(value_type)
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
            self.emit_load_words(field.word_width)
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
        elif isinstance(value_type, ListType):
            self.emit_streamed_list(value_type.element_type)
        elif isinstance(value_type, TupleType):
            self.emit_streamed_tuple(value_type)
        else:
            raise Exception(f"Cannot stream value of type {value_type}")

    def emit_print_text(self, text):
        literal = hr.Constant(0, text)
        literal.type = STR
        self.visit_Constant(literal)
        self.instructions.append(ir.PrintString())

    def emit_streamed_tuple(self, tuple_type):
        """Consume flattened tuple words and print a recursive tuple value."""
        element_types = tuple_type.element_types
        total_width = word_count(tuple_type)
        self.emit_print_text("(")
        if total_width == 0:
            self.emit_print_text(")")
            return

        # Preserve one scratch pointer while storing the flattened tuple into
        # a second copy of that pointer. This keeps recursive printers simple.
        self.instructions.append(ir.OpStackPushLiteral(total_width))
        self.instructions.append(ir.Malloc())
        self.instructions.append(ir.Dupe())
        for _ in range(total_width):
            self.instructions.append(ir.Roll(total_width + 1))
        self.emit_store_words(total_width)

        offset = 0
        for index, element_type in enumerate(element_types):
            if index:
                self.emit_print_text(", ")
            self.instructions.append(ir.Dupe())
            if offset:
                self.instructions.append(ir.OpStackPushLiteral(offset))
                self.instructions.append(ir.IAdd())
            self.emit_load_words(word_count(element_type))
            self.emit_streamed_value(element_type)
            offset += word_count(element_type)

        if len(element_types) == 1:
            self.emit_print_text(",")
        self.emit_print_text(")")
        self.instructions.append(ir.Free())

    def emit_streamed_list(self, element_type):
        """Consume a list descriptor and recursively print its typed elements."""
        element_width = word_count(element_type)

        # Scratch heap words hold [descriptor, index], keeping loop state away
        # from values consumed by recursive element printers.
        self.instructions.append(ir.OpStackPushLiteral(2))
        self.instructions.append(ir.Malloc())
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.Roll(2))
        self.instructions.append(ir.Store())
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.OpStackPushLiteral(0))
        self.instructions.append(ir.Store())

        self.emit_print_text("[")
        loop = len(self.instructions)

        # Preserve scratch and form index < descriptor.length.
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Load())
        self.instructions.append(ir.Roll(1))
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.Load())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Load())
        self.instructions.append(ir.Roll(1))
        self.instructions.append(ir.Roll(2))
        self.instructions.append(ir.Roll(2))
        self.instructions.append(ir.LessThan())
        done = ir.JumpIfFalse(None)
        self.instructions.append(done)

        # Print the separator after the first element.
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Load())
        self.instructions.append(ir.OpStackPushLiteral(0))
        self.instructions.append(ir.GreaterThan())
        first = ir.JumpIfFalse(None)
        self.instructions.append(first)
        self.emit_print_text(", ")
        first.location = len(self.instructions)

        # Load descriptor.data[index], retaining scratch below the value.
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.Load())
        self.instructions.append(ir.Load())
        self.instructions.append(ir.Roll(1))
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Load())
        self.instructions.append(ir.Roll(1))
        self.instructions.append(ir.Roll(2))
        self.instructions.append(ir.Roll(2))
        if element_width != 1:
            self.instructions.append(ir.OpStackPushLiteral(element_width))
            self.instructions.append(ir.IMultiply())
        self.instructions.append(ir.IAdd())
        self.emit_load_words(element_width)
        self.emit_streamed_value(element_type)

        # scratch.index += 1
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.Load())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Store())
        self.instructions.append(ir.Jump(loop))

        done.location = len(self.instructions)
        self.emit_print_text("]")
        self.instructions.append(ir.Free())

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

    def new_loop_context(self, retained_words, continue_target=None):
        context = {
            "retained_words": retained_words,
            "continue_target": continue_target,
            "breaks": [],
            "continues": [],
        }
        self.loop_contexts.append(context)
        return context

    def leave_loop_body(self, context, continue_target):
        assert self.loop_contexts.pop() is context
        for jump in context["continues"]:
            jump.location = continue_target

    @staticmethod
    def patch_loop_breaks(context, break_target):
        for jump in context["breaks"]:
            jump.location = break_target

    def emit_dupe_at_depth(self, depth):
        """Duplicate a word at *depth* without disturbing the surrounding stack."""
        if depth == 0:
            self.instructions.append(ir.Dupe())
            return
        self.instructions.append(ir.Roll(depth))
        self.instructions.append(ir.Dupe())
        for _ in range(depth + 1):
            self.instructions.append(ir.Roll(depth + 1))

    def emit_pop_for_target(self, target):
        symbol = self.name_symbol(target.id)
        for relative_offset in reversed(range(symbol.word_width)):
            self.emit_pop_symbol(symbol, relative_offset)

    def emit_for_epilogue(self, node, context, retained_words, continue_target, exhausted_jumps):
        self.instructions.append(ir.Jump(continue_target))
        exhausted = len(self.instructions)
        for jump in exhausted_jumps:
            jump.location = exhausted
        self.instructions.append(ir.Drop(retained_words))
        actual_continue = (
            context["continue_target"]
            if context["continue_target"] is not None
            else continue_target
        )
        self.leave_loop_body(context, actual_continue)
        self.traverse(node.orelse)
        done = len(self.instructions)
        self.patch_loop_breaks(context, done)

    def visit_For(self, node):
        kind = node.loop_kind
        if kind == "class_protocol":
            self.emit_class_for(node)
        elif kind == "string":
            self.emit_string_for(node)
        elif kind == "list":
            self.emit_list_for(node)
        elif kind == "range":
            self.emit_range_for(node)
        else:
            raise Exception(f"Unknown for-loop lowering {kind!r}")

    def emit_class_for(self, node):
        self.traverse(node.iterable)
        self.emit_value_to_call_stack(node.iterable.type)
        self.instructions.append(ir.Call(node.iter_method))
        condition = len(self.instructions)
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPopToCallStack())
        self.instructions.append(ir.Call(node.bool_method))
        exhausted = ir.JumpIfFalse(None)
        self.instructions.append(exhausted)
        context = self.new_loop_context(1, condition)
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPopToCallStack())
        self.instructions.append(ir.Call(node.next_method))
        self.emit_pop_for_target(node.target)
        self.traverse(node.body)
        self.emit_for_epilogue(node, context, 1, condition, [exhausted])

    def emit_string_for(self, node):
        self.traverse(node.iterable)  # [pointer, length]
        self.instructions.append(ir.OpStackPushLiteral(0))  # index
        condition = len(self.instructions)
        self.instructions.append(ir.Dupe())
        self.emit_dupe_at_depth(2)
        self.instructions.append(ir.LessThan())
        exhausted = ir.JumpIfFalse(None)
        self.instructions.append(exhausted)
        context = self.new_loop_context(3)
        self.emit_dupe_at_depth(2)  # pointer
        self.emit_dupe_at_depth(1)  # index
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Load())
        self.emit_pop_for_target(node.target)
        self.traverse(node.body)
        increment = len(self.instructions)
        context["continue_target"] = increment
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.emit_for_epilogue(node, context, 3, condition, [exhausted])

    def emit_list_for(self, node):
        self.traverse(node.iterable)  # [descriptor]
        self.instructions.append(ir.OpStackPushLiteral(0))  # index
        condition = len(self.instructions)
        self.instructions.append(ir.Dupe())
        self.emit_dupe_at_depth(2)  # descriptor below index and duplicate index
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Load())
        self.instructions.append(ir.LessThan())
        exhausted = ir.JumpIfFalse(None)
        self.instructions.append(exhausted)
        context = self.new_loop_context(2)
        self.emit_dupe_at_depth(1)  # descriptor
        self.instructions.append(ir.Load())  # data pointer
        self.emit_dupe_at_depth(1)  # index
        if node.element_width != 1:
            self.instructions.append(ir.OpStackPushLiteral(node.element_width))
            self.instructions.append(ir.IMultiply())
        self.instructions.append(ir.IAdd())
        self.emit_load_words(node.element_width)
        self.emit_pop_for_target(node.target)
        self.traverse(node.body)
        increment = len(self.instructions)
        context["continue_target"] = increment
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.emit_for_epilogue(node, context, 2, condition, [exhausted])

    def emit_range_for(self, node):
        self.traverse(node.range_start)
        self.traverse(node.range_stop)
        self.traverse(node.range_step)  # [current, stop, step]
        condition = len(self.instructions)
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(0))
        self.instructions.append(ir.GreaterThan())
        negative = ir.JumpIfFalse(None)
        self.instructions.append(negative)
        self.emit_dupe_at_depth(2)
        self.emit_dupe_at_depth(2)
        self.instructions.append(ir.LessThan())
        exhausted_positive = ir.JumpIfFalse(None)
        self.instructions.append(exhausted_positive)
        body_jump = ir.Jump(None)
        self.instructions.append(body_jump)
        negative.location = len(self.instructions)
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(0))
        self.instructions.append(ir.LessThan())
        exhausted_zero = ir.JumpIfFalse(None)
        self.instructions.append(exhausted_zero)
        self.emit_dupe_at_depth(2)
        self.emit_dupe_at_depth(2)
        self.instructions.append(ir.GreaterThan())
        exhausted_negative = ir.JumpIfFalse(None)
        self.instructions.append(exhausted_negative)
        body_jump.location = len(self.instructions)
        context = self.new_loop_context(3)
        self.emit_dupe_at_depth(2)
        self.emit_pop_for_target(node.target)
        self.traverse(node.body)
        increment = len(self.instructions)
        context["continue_target"] = increment
        self.emit_dupe_at_depth(2)
        self.emit_dupe_at_depth(1)
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.Roll(3))
        self.instructions.append(ir.Drop(1))
        self.instructions.append(ir.Roll(2))
        self.instructions.append(ir.Roll(2))
        self.emit_for_epilogue(
            node, context, 3, condition,
            [exhausted_positive, exhausted_zero, exhausted_negative],
        )

    def visit_While(self, node):
        start_location = len(self.instructions)
        self.traverse(node.condition)
        condition_jump = ir.JumpIfFalse(None)
        self.instructions.append(condition_jump)
        context = self.new_loop_context(0, start_location)
        self.traverse(node.body)
        self.instructions.append(ir.Jump(start_location))
        condition_jump.location = len(self.instructions)
        self.leave_loop_body(context, start_location)
        self.traverse(node.orelse)
        done = len(self.instructions)
        self.patch_loop_breaks(context, done)




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

        if isinstance(node.slice, hr.Slice):
            if node.value.type == STR and node.slice.lower is None and node.slice.upper is None:
                self.traverse(node.value)
                return

            if node.slice.upper is None:
                self.traverse(node.value)
                if node.value.type == STR:
                    self.instructions.append(ir.Dupe())
                else:
                    self.instructions.append(ir.Dupe())
                    self.instructions.append(ir.OpStackPushLiteral(1))
                    self.instructions.append(ir.IAdd())
                    self.instructions.append(ir.Load())
                self.instructions.append(ir.OpStackPopToCallStack())
                if node.slice.lower is None:
                    self.instructions.append(ir.OpStackPushLiteral(0))
                else:
                    self.traverse(node.slice.lower)
                self.instructions.append(ir.OpStackPopToCallStack())
                self.emit_value_to_call_stack(node.value.type)
            else:
                self.traverse(node.slice.upper)
                self.instructions.append(ir.OpStackPopToCallStack())
                if node.slice.lower is None:
                    self.instructions.append(ir.OpStackPushLiteral(0))
                else:
                    self.traverse(node.slice.lower)
                self.instructions.append(ir.OpStackPopToCallStack())
                self.traverse(node.value)
                self.emit_value_to_call_stack(node.value.type)
            runtime = getattr(node, "resolved_list_slice", None) or node.resolved_runtime
            self.instructions.append(ir.Call(runtime))
            return

        if isinstance(node.value.type, TupleType):
            self.traverse(node.value)
            self.emit_projection(
                node.projection_total_width,
                node.projection_offset,
                node.projection_width,
            )
            return

        self.traverse(node.value)
        if node.value.type == STR:
            self.instructions.append(ir.Drop(1))
        elif isinstance(node.value.type, ListType):
            self.instructions.append(ir.Load())
        self.traverse(node.slice)
        if isinstance(node.value.type, ListType):
            width = word_count(node.value.type.element_type)
            if width != 1:
                self.instructions.append(ir.OpStackPushLiteral(width))
                self.instructions.append(ir.IMultiply())
        self.instructions.append(ir.IAdd())

        if type(node.context) is ast.Load:
            self.emit_load_words(word_count(node.type))


    def visit_List(self, node):
        element_width = word_count(node.type.element_type)
        capacity = 10
        while capacity < len(node.elements):
            capacity *= 2
        # Allocate the stable [data pointer, length, capacity] descriptor.
        self.instructions.append(ir.OpStackPushLiteral(3))
        self.instructions.append(ir.Malloc())
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(capacity * element_width))
        self.instructions.append(ir.Malloc())
        self.instructions.append(ir.Store())

        for i, v in enumerate(node.elements):
            self.instructions.append(ir.Dupe())
            self.instructions.append(ir.Load())
            if i:
                self.instructions.append(ir.OpStackPushLiteral(i * element_width))
                self.instructions.append(ir.IAdd())

            self.traverse(v)

            self.emit_store_words(element_width)
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(1))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.OpStackPushLiteral(len(node.elements)))
        self.instructions.append(ir.Store())
        self.instructions.append(ir.Dupe())
        self.instructions.append(ir.OpStackPushLiteral(2))
        self.instructions.append(ir.IAdd())
        self.instructions.append(ir.OpStackPushLiteral(capacity))
        self.instructions.append(ir.Store())

    def visit_Tuple(self, node):
        self.traverse(node.elements)

    def visit_Starred(self, node):
        self.traverse(node.value)

    def visit_Constant(self, node):

        if type(node.value) is str and node.type == CHAR:
            self.instructions.append(ir.OpStackPushLiteral(ord(node.value)))

        elif type(node.value) is str:
            self.instructions.append(ir.OpStackPushLiteral(len(node.value)))
            self.instructions.append(ir.Malloc())

            for i, c in enumerate(node.value):
                self.instructions.append(ir.Dupe())
                self.instructions.append(ir.OpStackPushLiteral(i))
                self.instructions.append(ir.IAdd())
                self.instructions.append(ir.OpStackPushLiteral(ord(c)))
                self.instructions.append(ir.Store())

            self.instructions.append(ir.OpStackPushLiteral(len(node.value)))

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
            self.emit_value_to_call_stack(operand.type)
            self.traverse(receiver)
            self.emit_value_to_call_stack(receiver.type)
            self.instructions.append(ir.Call(node.resolved_method))
            return

        op = type(node.operator)
        if op in {ast.In, ast.NotIn} and node.right_type == STR:
            needle = node.left
            if node.left_type == CHAR:
                self.emit_char_string(needle)
            else:
                self.traverse(needle)
            self.emit_value_to_call_stack(STR)
            self.traverse(node.right)
            self.emit_value_to_call_stack(STR)
            self.instructions.append(ir.Call("__gvm_str_find"))
            self.instructions.append(ir.OpStackPushLiteral(-1))
            self.instructions.append((ir.NotEqual if op is ast.In else ir.Equal)())
            return
        if node.left_type == STR and node.right_type == STR and op in {
            ast.Eq, ast.NotEq, ast.Lt, ast.Gt, ast.LtE, ast.GtE,
        }:
            for argument in (node.right, node.left):
                self.traverse(argument)
                self.emit_value_to_call_stack(argument.type)
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
                self.emit_value_to_call_stack(STR if argument.type == CHAR else argument.type)
            self.instructions.append(ir.Call(runtime))
            return

        self.traverse(node.left)
        if node.operand_type == FLOAT and node.left_type in {INT, BOOL}:
            self.instructions.append(ir.IntToFloat())
        self.traverse(node.right)
        if node.operand_type == FLOAT and node.right_type in {INT, BOOL}:
            self.instructions.append(ir.IntToFloat())

        op = type(node.operator)
        integer_numeric = {
            ast.Add: ir.IAdd,
            ast.Mult: ir.IMultiply,
            ast.Sub: ir.ISub,
            ast.Mod: ir.IMod,
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

        if op in integer_numeric and node.operand_type in {INT, PTR}:
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
            self.emit_value_to_call_stack(node.operand.type)
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
    runtime_added = False
    if not getattr(ast, "_string_runtime_added", False):
        ast.body.extend(string_runtime.runtime_definitions())
        ast._string_runtime_added = True
        runtime_added = True
    if not getattr(ast, "_list_runtime_added", False):
        ast.body.extend(list_runtime.runtime_definitions())
        ast._list_runtime_added = True
        runtime_added = True
    if runtime_added:
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
    c.runtime_functions = (
        string_runtime.required_functions(ast) | list_runtime.required_functions(ast)
    )
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
    try:
        python_ast = ast.parse(source, filename)
        module = hr.ast_to_hr(python_ast, source=source, filename=filename)
        table = Symbols(module)
        return compile(
            module, table, extra_instructions, extra_functions,
            instruction_set=instruction_set,
        )
    except Exception as error:
        # Enrich legacy line-number diagnostics without changing their type or
        # traceback. Syntax and target errors already carry source context.
        match = re.search(r"\(line: (\d+)\)$", str(error))
        if match and len(error.args) == 1:
            lines = source.splitlines()
            index = int(match.group(1)) - 1
            if 0 <= index < len(lines):
                error.args = (f"{error}\n{lines[index]}",)
        raise
