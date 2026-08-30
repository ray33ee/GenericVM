import ast

import hr
import string_runtime
from symbols import FieldInfo, Symbol, Symbols
from signature_inference import infer_function_signatures
from typesystem import (
    BOOL,
    CHAR,
    FLOAT,
    INT,
    NONE,
    STR,
    BuiltinSignature,
    ClassType,
    DUNDER_BUILTINS,
    FunctionType,
    ListType,
    TupleType,
    Type,
    contains_tuple,
    tuple_member_layout,
    word_count,
)


class TypeCheckError(Exception):
    pass


class TypeChecker(hr.Walker):
    """Resolve and validate every type before VM instruction generation."""

    def __init__(self, symbols: Symbols, builtins: dict[str, BuiltinSignature]):
        self.symbols = symbols
        self.builtins = builtins
        for name in builtins:
            if name in symbols.classes or name in symbols.functions or name in symbols.top_level:
                raise TypeCheckError(f"Name '{name}' conflicts with a built-in")
        self.context: tuple[dict[str, Symbol], hr.FunctionDef] | None = None
        self.expected_return_type: Type | None = None
        self.allow_joined_str = False
        self.allow_auto_string = False
        self.function_types = {
            function.qualified_name: FunctionType(
                tuple(argument.annotation for argument in function.args),
                function.return_type,
            )
            for _, function in symbols.functions.values()
        }
        for function in (
            node for node in symbols.module.body if isinstance(node, hr.FunctionDef)
        ):
            for argument in function.args:
                self._validate_type(argument, argument.annotation)
                self._reject_tuple_in_heap_container(argument, argument.annotation)
            self._validate_type(function, function.return_type)
            self._reject_tuple_in_heap_container(function, function.return_type)
        for class_info in symbols.classes.values():
            for field in class_info.fields.values():
                self._validate_type(class_info.definition, field.type)
                if contains_tuple(field.type):
                    self.error(
                        class_info.definition,
                        f"Field '{class_info.name}.{field.name}' cannot store stack-only tuple type {field.type}",
                    )
                if word_count(field.type) != 1:
                    self.error(
                        class_info.definition,
                        f"Field '{class_info.name}.{field.name}' must occupy exactly one heap word, found {field.type}",
                    )
        for name, builtin in builtins.items():
            for parameter_type in builtin.parameter_types:
                if isinstance(parameter_type, ListType) and contains_tuple(parameter_type.element_type):
                    raise TypeCheckError(
                        f"Built-in '{name}' cannot store tuples inside heap type {parameter_type}"
                    )
            if isinstance(builtin.return_type, ListType) and contains_tuple(builtin.return_type.element_type):
                raise TypeCheckError(
                    f"Built-in '{name}' cannot return heap type {builtin.return_type} containing tuples"
                )

    def check(self, module: hr.Module) -> hr.Module:
        self.walk(module)
        self._assert_all_expressions_typed(module)
        self.symbols.dead_global_check()
        return module

    def error(self, node, message: str):
        lineno = getattr(node, "lineno", "unknown")
        raise TypeCheckError(f"{message} (line: {lineno})")

    def set_type(self, node: hr.Expression, result: Type) -> Type:
        node.type = result
        return result

    def symbol(self, node: hr.Name) -> Symbol:
        if self.context is not None and node.id in self.context[0]:
            return self.context[0][node.id]
        if node.id in self.symbols.top_level:
            return self.symbols.top_level[node.id]
        self.error(node, f"Unknown variable '{node.id}'")

    def require(self, node, actual: Type, expected: Type, description: str):
        if actual != expected:
            self.error(node, f"{description}: expected {expected}, found {actual}")

    def infer(self, node: hr.Expression, expected: Type | None = None) -> Type:
        method = getattr(self, f"visit_{type(node).__name__}", None)
        if method is None:
            self.error(node, f"Cannot infer type of {type(node).__name__}")
        return method(node, expected)

    def visit_Module(self, node):
        for statement in node.body:
            self.walk(statement)

    def visit_ClassDef(self, node):
        for method in node.methods:
            self.walk(method)
        self._check_definite_field_initialization(node)

    def visit_FunctionDef(self, node):
        previous_context = self.context
        previous_return = self.expected_return_type
        self.context = self.symbols.functions[node.qualified_name]
        self.expected_return_type = node.return_type

        for statement in node.body:
            self.walk(statement)

        if node.return_type != NONE and not self._block_definitely_returns(node.body):
            self.error(node, f"Function '{node.qualified_name}' does not return {node.return_type} on every path")

        self.context = previous_context
        self.expected_return_type = previous_return

    def visit_Assign(self, node):
        if isinstance(node.lhs, hr.TupleTarget):
            expected = self._tuple_target_expected_type(node.lhs)
            value_type = self.infer(node.rhs, expected)
            if not isinstance(value_type, TupleType):
                self.error(node.rhs, f"Cannot unpack non-tuple type {value_type}")
            self._bind_tuple_target(node.lhs, value_type, set())
            return

        if isinstance(node.lhs, hr.Subscript):
            target_type = self.infer(node.lhs)
            if isinstance(node.lhs.value.type, TupleType):
                self.error(node.lhs, "Tuples are immutable")
            if node.lhs.value.type == STR:
                self.error(node.lhs, "Strings are immutable")
            value_type = self.infer(node.rhs, target_type)
            self.require(node.rhs, value_type, target_type, "Invalid subscript assignment")
            return

        if isinstance(node.lhs, hr.Attribute):
            receiver_type = self.infer(node.lhs.value)
            if not isinstance(receiver_type, ClassType):
                self.error(node.lhs, f"Type {receiver_type} has no attributes")
            class_info = self.symbols.classes[receiver_type.name]
            if node.lhs.attr not in class_info.fields:
                current_function = self.context[1] if self.context is not None else None
                if (
                    current_function is None
                    or current_function.owner_class != receiver_type.name
                    or current_function.name != "__init__"
                    or not isinstance(node.lhs.value, hr.Name)
                    or node.lhs.value.id != "self"
                ):
                    self.error(
                        node.lhs,
                        f"Class '{receiver_type.name}' has no field '{node.lhs.attr}'",
                    )
                value_type = self.infer(node.rhs)
                if contains_tuple(value_type):
                    self.error(node.rhs, "Tuples cannot be stored in class fields")
                class_info.fields[node.lhs.attr] = FieldInfo(node.lhs.attr, value_type)
                node.lhs.resolved_class = receiver_type.name
                self.set_type(node.lhs, value_type)
                return
            target_type = self.infer(node.lhs)
            value_type = self.infer(node.rhs, target_type)
            self.require(node.rhs, value_type, target_type, "Invalid attribute assignment")
            return

        symbol = self.symbol(node.lhs)
        expected = node.annotation or symbol.type
        value_type = self.infer(node.rhs, expected)

        self._reject_tuple_in_heap_container(node, value_type)

        if expected is not None:
            self.require(node.rhs, value_type, expected, f"Cannot assign to '{node.lhs.id}'")
            symbol.type = expected
        else:
            symbol.type = value_type

        self.set_type(node.lhs, symbol.type)

    def visit_Return(self, node):
        if self.expected_return_type is None:
            self.error(node, "Return statement outside a function")

        if node.value is None:
            actual = NONE
        else:
            actual = self.infer(node.value, self.expected_return_type)

        self.require(node, actual, self.expected_return_type, "Invalid return type")

    def visit_Expr(self, node):
        self.infer(node.expr)

    def visit_If(self, node):
        self._check_condition(node.condition)
        self.traverse(node.body)
        self.traverse(node.orelse)

    def visit_While(self, node):
        self._check_condition(node.condition)
        self.traverse(node.body)
        self.traverse(node.orelse)

    def visit_Assert(self, node):
        self._check_condition(node.test)

    def visit_For(self, node):
        if isinstance(node.assignable, hr.Name):
            target_symbol = self.symbol(node.assignable)
            if target_symbol.type is None:
                target_symbol.type = INT
        target_type = self.infer(node.assignable)
        self.require(node.assignable, target_type, INT, "Range loop target must be int")
        for value in (node.start, node.end, node.step):
            if isinstance(value, hr.Expression):
                actual = self.infer(value, INT)
                self.require(value, actual, INT, "Range argument must be int")
        self.traverse(node.body)

    def visit_Pass(self, node):
        pass

    def visit_Break(self, node):
        pass

    def visit_Continue(self, node):
        pass

    def visit_Constant(self, node, expected=None):
        if type(node.value) is bool:
            result = BOOL
        elif type(node.value) is int:
            result = FLOAT if expected == FLOAT else INT
        elif type(node.value) is float:
            result = FLOAT
        elif type(node.value) is str:
            result = STR if expected == STR or len(node.value) != 1 else CHAR
        elif node.value is None:
            result = NONE
        else:
            self.error(node, f"Unsupported constant type {type(node.value).__name__}")
        return self.set_type(node, result)

    def visit_Name(self, node, expected=None):
        symbol = self.symbol(node)
        if symbol.type is None:
            self.error(node, f"Cannot determine type of '{node.id}' before its first assignment")
        return self.set_type(node, symbol.type)

    def visit_List(self, node, expected=None):
        expected_element = expected.element_type if isinstance(expected, ListType) else None
        if not node.elements:
            if expected_element is None:
                self.error(node, "Cannot infer the element type of an empty list")
            result = ListType(expected_element)
            self._reject_tuple_in_heap_container(node, result)
            return self.set_type(node, result)

        element_types = [self.infer(item, expected_element) for item in node.elements]
        element_type = expected_element or element_types[0]
        for item, actual in zip(node.elements, element_types):
            self.require(item, actual, element_type, "List elements must have one type")
        result = ListType(element_type)
        self._reject_tuple_in_heap_container(node, result)
        return self.set_type(node, result)

    def visit_Tuple(self, node, expected=None):
        expected_elements = expected.element_types if isinstance(expected, TupleType) else None
        if expected_elements is not None and len(expected_elements) != len(node.elements):
            self.error(
                node,
                f"Tuple length mismatch: expected {len(expected_elements)}, found {len(node.elements)}",
            )

        element_types = tuple(
            self.infer(item, expected_elements[index] if expected_elements else None)
            for index, item in enumerate(node.elements)
        )
        return self.set_type(node, TupleType(element_types))

    def visit_Starred(self, node, expected=None):
        value_type = self.infer(node.value, expected)
        if not isinstance(value_type, TupleType):
            self.error(node, f"Only tuples can be expanded with '*', found {value_type}")
        return self.set_type(node, value_type)

    def visit_Subscript(self, node, expected=None):
        container_type = self.infer(node.value)
        index_type = self.infer(node.slice, INT)
        self.require(node.slice, index_type, INT, "Subscript index must be int")

        if isinstance(container_type, ListType):
            result = container_type.element_type
        elif container_type == STR:
            result = CHAR
        elif isinstance(container_type, TupleType):
            index = self._integer_literal(node.slice)
            if index is None:
                self.error(node.slice, "Tuple index must be an integer literal")
            if index < 0:
                index += len(container_type.element_types)
            if index < 0 or index >= len(container_type.element_types):
                self.error(node.slice, "Tuple index is out of range")
            result = container_type.element_types[index]
            offset, width = tuple_member_layout(container_type, index)
            node.projection_total_width = word_count(container_type)
            node.projection_offset = offset
            node.projection_width = width
            node.resolved_index = index
        else:
            self.error(node.value, f"Type {container_type} cannot be subscripted")

        return self.set_type(node, result)

    def visit_Call(self, node, expected=None):
        if node.func == "input":
            if len(node.args) != 1:
                self.error(node, "input expects exactly one maximum-length argument")
            actual = self.infer(node.args[0], INT)
            self.require(node.args[0], actual, INT, "input maximum length must be int")
            node.resolved_intrinsic = "input"
            node.expanded_argument_count = 1
            return self.set_type(node, STR)
        if node.func == "__gvm_str_alloc":
            if len(node.args) != 1:
                self.error(node, "Internal string allocation expects one argument")
            actual = self.infer(node.args[0], INT)
            self.require(node.args[0], actual, INT, "String allocation length")
            node.resolved_intrinsic = "str_alloc"
            node.expanded_argument_count = 1
            return self.set_type(node, STR)
        if node.func == "__gvm_str_set":
            required = (STR, INT, CHAR)
            if len(node.args) != 3:
                self.error(node, "Internal string store expects three arguments")
            for argument, expected_type in zip(node.args, required):
                actual = self.infer(argument, expected_type)
                self.require(argument, actual, expected_type, "Invalid internal string store argument")
            node.resolved_intrinsic = "str_set"
            node.expanded_argument_count = 3
            return self.set_type(node, NONE)
        if node.func == "len" and len(node.args) == 1 and not isinstance(node.args[0], hr.Starred):
            value_type = self.infer(node.args[0])
            if value_type == STR or isinstance(value_type, ListType):
                node.resolved_intrinsic = "len_heap"
                node.expanded_argument_count = 1
                return self.set_type(node, INT)
        if node.func in {"ord", "chr"}:
            if len(node.args) != 1:
                self.error(node, f"{node.func} expects exactly one argument")
            required = CHAR if node.func == "ord" else INT
            result = INT if node.func == "ord" else CHAR
            actual = self.infer(node.args[0], required)
            self.require(node.args[0], actual, required, f"Invalid argument to '{node.func}'")
            node.resolved_intrinsic = node.func
            node.expanded_argument_count = 1
            return self.set_type(node, result)
        if node.func in {"printi", "printf", "prints", "printb", "printc"}:
            if len(node.args) != 1:
                self.error(node, f"{node.func} expects exactly one argument")
            argument_type = self.infer(node.args[0], STR if node.func == "prints" else None)
            if node.func == "printi" and argument_type != INT:
                self.error(node.args[0], f"printi expects int, found {argument_type}")
            if node.func == "printf" and argument_type != FLOAT:
                self.error(node.args[0], f"printf expects float, found {argument_type}")
            if node.func == "prints" and argument_type != STR:
                self.error(node.args[0], f"prints expects str, found {argument_type}")
            if node.func == "printc" and argument_type != CHAR:
                self.error(node.args[0], f"printc expects char, found {argument_type}")
            if node.func == "printb" and argument_type != BOOL:
                self.error(node.args[0], f"printb expects bool, found {argument_type}")
            node.resolved_builtin = node.func
            node.expanded_argument_count = 1
            return self.set_type(node, NONE)
        if node.func == "print":
            if len(node.args) > 1:
                self.error(node, "print accepts zero or one argument")
            if not node.args:
                node.resolved_builtin = "prints"
            else:
                previous = self.allow_joined_str
                previous_auto = self.allow_auto_string
                self.allow_joined_str = True
                self.allow_auto_string = True
                try:
                    argument_type = self.infer(node.args[0])
                finally:
                    self.allow_joined_str = previous
                    self.allow_auto_string = previous_auto
                if argument_type == INT:
                    target = "printi"
                elif argument_type == FLOAT:
                    target = "printf"
                elif argument_type == BOOL:
                    target = "printb"
                elif argument_type == CHAR:
                    target = "printc"
                elif argument_type == STR:
                    target = "prints"
                elif isinstance(argument_type, ClassType):
                    self._resolve_streamed_class(node, argument_type)
                    node.expanded_argument_count = 1
                    return self.set_type(node, NONE)
                else:
                    self.error(node.args[0], f"print does not support {argument_type}")
                node.resolved_builtin = target
            node.expanded_argument_count = len(node.args)
            return self.set_type(node, NONE)
        if node.func in self.symbols.classes:
            class_info = self.symbols.classes[node.func]
            constructor = class_info.methods["__init__"]
            signature = FunctionType(
                tuple(argument.annotation for argument in constructor.args[1:]),
                class_info.type,
            )
        elif node.func in self.function_types:
            signature = self.function_types[node.func]
        elif node.func in DUNDER_BUILTINS and len(node.args) == 1 and not isinstance(node.args[0], hr.Starred):
            receiver_type = self.infer(node.args[0])
            if node.func == "str" and receiver_type in {STR, BOOL, INT, FLOAT}:
                node.expanded_argument_count = 1
                if receiver_type == STR:
                    node.resolved_intrinsic = "identity"
                else:
                    if receiver_type == BOOL:
                        node.resolved_runtime = "__gvm_str_bool"
                    elif receiver_type == INT:
                        node.resolved_runtime = "__gvm_str_int"
                    else:
                        node.resolved_runtime = "__gvm_str_float"
                return self.set_type(node, STR)
            if isinstance(receiver_type, ClassType):
                dunder, required_return = DUNDER_BUILTINS[node.func]
                class_info = self.symbols.classes[receiver_type.name]
                method = class_info.methods.get(dunder)
                if node.func == "str" and method is None:
                    method = class_info.methods.get("__repr__")
                    if method is None:
                        if not self.allow_auto_string:
                            self.error(node, "Automatic class strings are streaming-only and may be used only inside print or a printed f-string")
                        self._validate_auto_string_fields(node, receiver_type, set())
                        node.auto_repr_class = receiver_type.name
                        node.expanded_argument_count = 1
                        return self.set_type(node, STR)
                if method is None:
                    self.error(node, f"Class '{receiver_type.name}' does not implement {dunder}")
                if len(method.args) != 1:
                    self.error(method, f"Protocol method '{method.qualified_name}' takes no explicit arguments")
                if required_return is not None:
                    self.require(method, method.return_type, required_return, f"Invalid return type for '{method.qualified_name}'")
                node.resolved_method = method.qualified_name
                node.expanded_argument_count = 1
                return self.set_type(node, required_return or method.return_type)
            if node.func == "str" and receiver_type == CHAR:
                node.resolved_intrinsic = "str_char"
                node.expanded_argument_count = 1
                return self.set_type(node, STR)
            if node.func in self.builtins:
                builtin = self.builtins[node.func]
                signature = FunctionType(builtin.parameter_types, builtin.return_type)
            else:
                self.error(node, f"Protocol call '{node.func}' requires a supported built-in type or class instance")
        elif node.func in self.builtins:
            builtin = self.builtins[node.func]
            signature = FunctionType(builtin.parameter_types, builtin.return_type)
        else:
            self.error(node, f"Unknown function '{node.func}'")

        parameter_index = 0
        for argument in node.args:
            if isinstance(argument, hr.Starred):
                expansion_expected = None
                if isinstance(argument.value, hr.Tuple):
                    expansion_size = len(argument.value.elements)
                    if parameter_index + expansion_size > len(signature.parameter_types):
                        self.error(node, f"Function '{node.func}' received too many arguments")
                    expansion_expected = TupleType(
                        signature.parameter_types[
                            parameter_index:parameter_index + expansion_size
                        ]
                    )
                expanded_type = self.infer(argument, expansion_expected)
                for actual in expanded_type.element_types:
                    if parameter_index >= len(signature.parameter_types):
                        self.error(node, f"Function '{node.func}' received too many arguments")
                    parameter_type = signature.parameter_types[parameter_index]
                    self.require(
                        argument,
                        actual,
                        parameter_type,
                        f"Invalid expanded argument to '{node.func}'",
                    )
                    parameter_index += 1
            else:
                if parameter_index >= len(signature.parameter_types):
                    self.error(node, f"Function '{node.func}' received too many arguments")
                parameter_type = signature.parameter_types[parameter_index]
                actual = self.infer(argument, parameter_type)
                self.require(argument, actual, parameter_type, f"Invalid argument to '{node.func}'")
                parameter_index += 1

        if parameter_index != len(signature.parameter_types):
            self.error(
                node,
                f"Function '{node.func}' expects {len(signature.parameter_types)} arguments, "
                f"found {parameter_index}",
            )
        node.expanded_argument_count = parameter_index

        return self.set_type(node, signature.return_type)

    def visit_JoinedStr(self, node, expected=None):
        if not self.allow_joined_str:
            self.error(node, "F-strings are streaming-only and may be used only as a direct argument to print")
        targets = []
        for value in node.values:
            if isinstance(value, hr.Constant):
                self.infer(value, STR)
                targets.append("prints")
            elif isinstance(value, hr.FormattedValue):
                self.infer(value)
                targets.append(value.resolved_builtin)
            else:
                self.error(value, "Invalid f-string fragment")
        # Tuple metadata is intentionally not traversed as HR child nodes.
        node.resolved_builtins = tuple(targets)
        return self.set_type(node, STR)

    def _resolve_streamed_class(self, node, class_type):
        class_info = self.symbols.classes[class_type.name]
        method = class_info.methods.get("__str__") or class_info.methods.get("__repr__")
        if method is not None:
            self.require(method, method.return_type, STR, f"Invalid string method '{method.qualified_name}'")
            node.streamed_method = method.qualified_name
        else:
            self._validate_auto_string_fields(node, class_type, set())
            node.streamed_class = class_type.name

    def visit_FormattedValue(self, node, expected=None):
        value_type = self.infer(node.value)
        if value_type == INT:
            node.resolved_builtin = "printi"
        elif value_type == FLOAT:
            node.resolved_builtin = "printf"
        elif value_type == BOOL:
            node.resolved_builtin = "printb"
        elif value_type == CHAR:
            node.resolved_builtin = "printc"
        elif value_type == STR:
            node.resolved_builtin = "prints"
        elif isinstance(value_type, ClassType):
            class_info = self.symbols.classes[value_type.name]
            method = class_info.methods.get("__str__") or class_info.methods.get("__repr__")
            if method is not None:
                self.require(method, method.return_type, STR, f"Invalid string method '{method.qualified_name}'")
                node.resolved_method = method.qualified_name
            else:
                self._validate_auto_string_fields(node, value_type, set())
                node.auto_repr_class = value_type.name
            node.resolved_builtin = "prints"
        else:
            self.error(node.value, f"F-string interpolation does not support {value_type}")
        return self.set_type(node, STR)

    def _validate_auto_string_fields(self, node, class_type, visiting):
        if class_type.name in visiting:
            return
        visiting.add(class_type.name)
        for field in self.symbols.classes[class_type.name].fields.values():
            if field.type in {INT, FLOAT, BOOL, STR, CHAR}:
                continue
            if isinstance(field.type, ClassType):
                self._validate_auto_string_fields(node, field.type, visiting)
                continue
            self.error(node, f"Automatic string representation does not support field '{class_type.name}.{field.name}' of type {field.type}")
        visiting.remove(class_type.name)

    def visit_Attribute(self, node, expected=None):
        receiver_type = self.infer(node.value)
        if not isinstance(receiver_type, ClassType):
            self.error(node, f"Type {receiver_type} has no attributes")
        class_info = self.symbols.classes.get(receiver_type.name)
        if class_info is None or node.attr not in class_info.fields:
            self.error(node, f"Class '{receiver_type.name}' has no field '{node.attr}'")
        node.resolved_class = receiver_type.name
        return self.set_type(node, class_info.fields[node.attr].type)

    def visit_MethodCall(self, node, expected=None):
        receiver_type = self.infer(node.receiver)
        if receiver_type == CHAR and isinstance(node.receiver, hr.Constant):
            receiver_type = self.infer(node.receiver, STR)
        if receiver_type == STR:
            definition = string_runtime.METHODS.get(node.method)
            if definition is None:
                self.error(node, f"String has no method '{node.method}'")
            _, parameter_types, return_type = definition
            if len(node.args) != len(parameter_types):
                self.error(node, f"str.{node.method} expects {len(parameter_types)} arguments")
            for argument, parameter_type in zip(node.args, parameter_types):
                actual = self.infer(argument, parameter_type)
                self.require(argument, actual, parameter_type, f"Invalid argument to str.{node.method}")
            node.resolved_method = string_runtime.runtime_name(node.method)
            return self.set_type(node, return_type)
        if not isinstance(receiver_type, ClassType):
            self.error(node, f"Type {receiver_type} has no methods")
        class_info = self.symbols.classes.get(receiver_type.name)
        if class_info is None or node.method not in class_info.methods:
            self.error(node, f"Class '{receiver_type.name}' has no method '{node.method}'")
        method = class_info.methods[node.method]
        parameter_types = tuple(argument.annotation for argument in method.args[1:])
        self._check_expanded_arguments(node, node.args, parameter_types, method.qualified_name)
        node.resolved_method = method.qualified_name
        return self.set_type(node, method.return_type)

    def visit_IfExpr(self, node, expected=None):
        self._check_condition(node.condition)
        true_type = self.infer(node.true_expr, expected)
        false_type = self.infer(node.false_expr, expected or true_type)
        self.require(node.false_expr, false_type, true_type, "Conditional branches differ")
        return self.set_type(node, true_type)

    def visit_BinOp(self, node, expected=None):
        left_type = self.infer(node.left)
        right_type = self.infer(node.right, left_type)
        operator = type(node.operator)
        if (
            operator is ast.Mult and left_type == INT and right_type == CHAR
            and isinstance(node.right, hr.Constant)
        ):
            right_type = self.infer(node.right, STR)

        magic_methods = {
            ast.Add: ("__add__", "__radd__"), ast.Sub: ("__sub__", "__rsub__"),
            ast.Mult: ("__mul__", "__rmul__"), ast.BitAnd: ("__and__", "__rand__"),
            ast.BitOr: ("__or__", "__ror__"), ast.BitXor: ("__xor__", "__rxor__"),
            ast.LShift: ("__lshift__", "__rlshift__"), ast.RShift: ("__rshift__", "__rrshift__"),
            ast.Eq: ("__eq__", "__eq__"), ast.NotEq: ("__ne__", "__ne__"),
            ast.Lt: ("__lt__", "__gt__"), ast.Gt: ("__gt__", "__lt__"),
            ast.LtE: ("__le__", "__ge__"), ast.GtE: ("__ge__", "__le__"),
        }
        if isinstance(left_type, ClassType) or isinstance(right_type, ClassType):
            forward, reverse = magic_methods.get(operator, (None, None))
            receiver_type = left_type if isinstance(left_type, ClassType) else right_type
            magic = forward if isinstance(left_type, ClassType) else reverse
            class_info = self.symbols.classes[receiver_type.name]
            method = class_info.methods.get(magic) if magic is not None else None
            if method is None:
                self.error(node, f"Class '{receiver_type.name}' does not implement {magic or operator.__name__}")
            parameters = method.args[1:]
            if len(parameters) != 1:
                self.error(method, f"Operator method '{method.qualified_name}' must accept one operand")
            operand_node = node.right if isinstance(left_type, ClassType) else node.left
            operand_type = right_type if isinstance(left_type, ClassType) else left_type
            self.require(operand_node, operand_type, parameters[0].annotation, f"Invalid operand to '{method.qualified_name}'")
            node.resolved_method = method.qualified_name
            node.resolved_reverse = not isinstance(left_type, ClassType)
            node.operand_type = receiver_type
            return self.set_type(node, method.return_type)

        arithmetic = {ast.Add, ast.Sub, ast.Mult}
        ordering = {ast.Lt, ast.Gt, ast.LtE, ast.GtE}
        equality = {ast.Eq, ast.NotEq}
        bitwise = {ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift}
        logical = {ast.And, ast.Or}
        membership = {ast.In, ast.NotIn}

        if operator in arithmetic:
            if (
                operator is ast.Add
                and left_type in {STR, CHAR}
                and right_type in {STR, CHAR}
            ):
                result = STR
            elif operator is ast.Mult and (
                (left_type == STR and right_type == INT)
                or (left_type == INT and right_type == STR)
            ):
                result = STR
            elif left_type not in {INT, FLOAT} or right_type not in {INT, FLOAT}:
                # Add will also gain a separate string-concatenation branch later.
                self.error(node, f"Operator {operator.__name__} requires numeric operands")
            else:
                result = FLOAT if FLOAT in {left_type, right_type} else INT
        elif operator in ordering:
            if left_type == STR and right_type == STR:
                result = BOOL
            elif left_type not in {INT, FLOAT, CHAR} or right_type != left_type:
                self.error(node, f"Operator {operator.__name__} requires matching numeric operands")
            else:
                result = BOOL
        elif operator in equality:
            if right_type != left_type:
                self.error(node, f"Operator {operator.__name__} requires matching operand types")
            if left_type not in {INT, FLOAT, BOOL, CHAR, STR}:
                self.error(node, f"Equality is not implemented for {left_type}")
            result = BOOL
        elif operator in bitwise:
            if left_type != INT or right_type != INT:
                self.error(node, f"Operator {operator.__name__} requires int operands")
            result = INT
        elif operator in logical:
            if left_type != BOOL or right_type != BOOL:
                self.error(node, f"Operator {operator.__name__} requires bool operands")
            result = BOOL
        elif operator in membership:
            if left_type not in {STR, CHAR} or right_type != STR:
                self.error(node, "String membership requires a char or str on the left and str on the right")
            result = BOOL
        else:
            self.error(node, f"Operator {operator.__name__} is not supported")

        node.left_type = left_type
        node.right_type = right_type
        node.operand_type = result if operator in arithmetic else left_type
        return self.set_type(node, result)

    def visit_UnaryOp(self, node, expected=None):
        operand_type = self.infer(node.operand)
        operator = type(node.operator)

        if isinstance(operand_type, ClassType):
            magic = {ast.UAdd: "__pos__", ast.USub: "__neg__", ast.Invert: "__invert__"}.get(operator)
            method = self.symbols.classes[operand_type.name].methods.get(magic) if magic else None
            if method is None:
                self.error(node, f"Class '{operand_type.name}' does not implement {magic or operator.__name__}")
            if len(method.args) != 1:
                self.error(method, f"Unary operator method '{method.qualified_name}' takes no operands")
            node.resolved_method = method.qualified_name
            node.operand_type = operand_type
            return self.set_type(node, method.return_type)

        if operator in {ast.UAdd, ast.USub}:
            if operand_type not in {INT, FLOAT}:
                self.error(node, f"Operator {operator.__name__} requires a numeric operand")
            result = operand_type
        elif operator is ast.Invert:
            self.require(node.operand, operand_type, INT, "Invert requires an int operand")
            result = INT
        elif operator is ast.Not:
            self.require(node.operand, operand_type, BOOL, "Not requires a bool operand")
            result = BOOL
        else:
            self.error(node, f"Operator {operator.__name__} is not supported")

        node.operand_type = operand_type
        return self.set_type(node, result)

    def _check_condition(self, expression):
        actual = self.infer(expression, BOOL)
        self.require(expression, actual, BOOL, "Condition must be bool")

    def _assert_all_expressions_typed(self, module):
        unresolved = []

        class FindUnresolved(hr.Walker):
            def generic_walk(self, node):
                if isinstance(node, hr.Expression) and node.type is None:
                    unresolved.append(node)
                super().generic_walk(node)

        FindUnresolved().walk(module)
        if unresolved:
            node = unresolved[0]
            self.error(node, f"Internal error: {type(node).__name__} has no resolved type")

    def _block_definitely_returns(self, statements) -> bool:
        for statement in statements:
            if isinstance(statement, hr.Return):
                return True
            if isinstance(statement, hr.If):
                if statement.orelse and self._block_definitely_returns(statement.body) \
                        and self._block_definitely_returns(statement.orelse):
                    return True
        return False

    def _reject_tuple_in_heap_container(self, node, value_type: Type):
        if isinstance(value_type, ListType) and contains_tuple(value_type.element_type):
            self.error(node, f"Tuples cannot be stored inside heap type {value_type}")

    def _validate_type(self, node, value_type: Type):
        if isinstance(value_type, ClassType):
            if value_type.name not in self.symbols.classes:
                self.error(node, f"Unknown class type '{value_type.name}'")
        elif isinstance(value_type, ListType):
            self._validate_type(node, value_type.element_type)
        elif isinstance(value_type, TupleType):
            for element_type in value_type.element_types:
                self._validate_type(node, element_type)

    def _check_expanded_arguments(self, node, arguments, parameter_types, display_name):
        parameter_index = 0
        for argument in arguments:
            expansion_expected = None
            if isinstance(argument, hr.Starred) and isinstance(argument.value, hr.Tuple):
                size = len(argument.value.elements)
                expansion_expected = TupleType(parameter_types[parameter_index:parameter_index + size])
            actual = self.infer(argument, expansion_expected or (
                parameter_types[parameter_index] if parameter_index < len(parameter_types) else None
            ))
            actual_types = actual.element_types if isinstance(argument, hr.Starred) else (actual,)
            for actual_type in actual_types:
                if parameter_index >= len(parameter_types):
                    self.error(node, f"Method '{display_name}' received too many arguments")
                self.require(argument, actual_type, parameter_types[parameter_index], f"Invalid argument to '{display_name}'")
                parameter_index += 1
        if parameter_index != len(parameter_types):
            self.error(node, f"Method '{display_name}' expects {len(parameter_types)} arguments, found {parameter_index}")
        node.expanded_argument_count = parameter_index

    def _check_definite_field_initialization(self, class_node):
        class_info = self.symbols.classes[class_node.name]
        constructor = class_info.methods["__init__"]

        def require_initialized_reads(node, assigned):
            reads = []

            class FindReads(hr.Walker):
                def visit_Attribute(inner_self, attribute):
                    if (
                        isinstance(attribute.value, hr.Name)
                        and attribute.value.id == "self"
                        and isinstance(attribute.context, ast.Load)
                    ):
                        reads.append(attribute)
                    inner_self.generic_walk(attribute)

            FindReads().walk(node)
            for attribute in reads:
                if attribute.attr not in assigned:
                    self.error(attribute, f"Field '{class_node.name}.{attribute.attr}' is read before initialization")

        def assigned_by_block(statements, assigned):
            current = set(assigned)
            for statement in statements:
                if isinstance(statement, hr.Assign) and isinstance(statement.lhs, hr.Attribute):
                    target = statement.lhs
                    require_initialized_reads(statement.rhs, current)
                    if isinstance(target.value, hr.Name) and target.value.id == "self":
                        current.add(target.attr)
                elif isinstance(statement, hr.If):
                    require_initialized_reads(statement.condition, current)
                    body = assigned_by_block(statement.body, current)
                    other = assigned_by_block(statement.orelse or [], current)
                    current = body & other
                elif isinstance(statement, hr.While):
                    require_initialized_reads(statement.condition, current)
                    assigned_by_block(statement.body, current)
                elif isinstance(statement, hr.For):
                    for value in (statement.start, statement.end, statement.step):
                        if isinstance(value, hr.HRNode):
                            require_initialized_reads(value, current)
                    assigned_by_block(statement.body, current)
                else:
                    require_initialized_reads(statement, current)
                if isinstance(statement, hr.Return):
                    missing_at_return = sorted(set(class_info.fields) - current)
                    if missing_at_return:
                        self.error(statement, f"Constructor '{constructor.qualified_name}' returns before initializing fields: {', '.join(missing_at_return)}")
            return current

        initialized = assigned_by_block(constructor.body, set())
        missing = sorted(set(class_info.fields) - initialized)
        if missing:
            self.error(constructor, f"Constructor '{constructor.qualified_name}' does not initialize fields: {', '.join(missing)}")

    def _integer_literal(self, node):
        if isinstance(node, hr.Constant) and type(node.value) is int:
            return node.value
        if (
            isinstance(node, hr.UnaryOp)
            and isinstance(node.operator, ast.USub)
            and isinstance(node.operand, hr.Constant)
            and type(node.operand.value) is int
        ):
            return -node.operand.value
        return None

    def _bind_tuple_target(self, target, value_type: TupleType, seen_names: set[str]):
        if len(target.elements) != len(value_type.element_types):
            self.error(
                target,
                f"Cannot unpack tuple with {len(value_type.element_types)} members into "
                f"{len(target.elements)} targets",
            )

        target.type = value_type
        for element, element_type in zip(target.elements, value_type.element_types):
            if isinstance(element, hr.Name):
                if element.id in seen_names:
                    self.error(element, f"Duplicate tuple assignment target '{element.id}'")
                seen_names.add(element.id)
                symbol = self.symbol(element)
                if symbol.type is None:
                    symbol.type = element_type
                else:
                    self.require(
                        element,
                        element_type,
                        symbol.type,
                        f"Cannot unpack into '{element.id}'",
                    )
                self.set_type(element, symbol.type)
            elif isinstance(element, hr.TupleTarget):
                if not isinstance(element_type, TupleType):
                    self.error(element, f"Cannot unpack non-tuple member of type {element_type}")
                self._bind_tuple_target(element, element_type, seen_names)
            else:
                self.error(element, "Invalid tuple assignment target")

    def _tuple_target_expected_type(self, target):
        element_types = []
        for element in target.elements:
            if isinstance(element, hr.Name):
                element_type = self.symbol(element).type
            elif isinstance(element, hr.TupleTarget):
                element_type = self._tuple_target_expected_type(element)
            else:
                return None
            if element_type is None:
                return None
            element_types.append(element_type)
        return TupleType(tuple(element_types))


def check_types(
    module: hr.Module,
    symbols: Symbols,
    builtins: dict[str, BuiltinSignature],
) -> hr.Module:
    infer_function_signatures(module, symbols, builtins)
    return TypeChecker(symbols, builtins).check(module)
