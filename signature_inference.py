import ast

import hr
import string_runtime
from symbols import FieldInfo, Symbols
from typesystem import (
    BOOL,
    CHAR,
    FLOAT,
    INT,
    NONE,
    PTR,
    STR,
    BuiltinSignature,
    ClassType,
    DUNDER_BUILTINS,
    ListType,
    TupleType,
    Type,
)


class SignatureInferenceError(Exception):
    pass


class DeadCodeError(Exception):
    pass


def check_dead_code(module: hr.Module, symbols: Symbols):
    """Reject unreachable functions and statements before type inference."""
    functions = {
        node.name: node for node in module.body if isinstance(node, hr.FunctionDef)
    }

    def named_calls(nodes):
        calls = set()

        class Collect(hr.Walker):
            def visit_Call(self, node):
                if node.func in functions:
                    calls.add(node.func)
                self.generic_walk(node)

        Collect().traverse(nodes)
        return calls

    roots = named_calls([
        node for node in module.body if isinstance(node, hr.Statement)
    ])
    edges = {name: named_calls(function.body) for name, function in functions.items()}

    # A constructed class may call ordinary functions from any of its methods.
    # Method dispatch is resolved later, so this is deliberately conservative.
    class_calls = set()
    for class_info in symbols.classes.values():
        for method in class_info.methods.values():
            class_calls.update(named_calls(method.body))

    constructed_classes = set()

    class FindConstructors(hr.Walker):
        def visit_Call(self, node):
            if node.func in symbols.classes:
                constructed_classes.add(node.func)
            self.generic_walk(node)

    reachable = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(edges[name] - reachable)
        FindConstructors().traverse(functions[name].body)

    FindConstructors().traverse([
        node for node in module.body if isinstance(node, hr.Statement)
    ])
    if constructed_classes:
        pending = list(class_calls - reachable)
        while pending:
            name = pending.pop()
            if name in reachable:
                continue
            reachable.add(name)
            pending.extend(edges[name] - reachable)

    # A definition-only module may be a library fragment. Once the module has
    # executable entry code, however, every function must be reachable from it.
    if roots:
        for name, function in functions.items():
            if name not in reachable and not name.startswith(string_runtime.PREFIX) and not name.startswith("__gvm_"):
                raise DeadCodeError(
                    f"Function '{name}' is never called (line: {function.lineno})"
                )

    def block_terminates(statements):
        terminated = False
        for statement in statements:
            if terminated:
                raise DeadCodeError(
                    f"Unreachable {type(statement).__name__} statement (line: {getattr(statement, 'lineno', 'unknown')})"
                )
            if isinstance(statement, (hr.Return, hr.Break, hr.Continue)):
                terminated = True
            elif isinstance(statement, hr.If):
                body_ends = block_terminates(statement.body)
                else_ends = bool(statement.orelse) and block_terminates(statement.orelse)
                terminated = body_ends and else_ends
            elif isinstance(statement, (hr.While, hr.For)):
                block_terminates(statement.body)
                if hasattr(statement, "orelse"):
                    block_terminates(statement.orelse or [])
        return terminated

    for function in functions.values():
        block_terminates(function.body)
    for class_info in symbols.classes.values():
        for method in class_info.methods.values():
            block_terminates(method.body)


class SignatureInferer:
    """Infer monomorphic function signatures from external call sites and bodies."""

    def __init__(
        self,
        module: hr.Module,
        symbols: Symbols,
        builtins: dict[str, BuiltinSignature],
    ):
        self.module = module
        self.symbols = symbols
        self.builtins = builtins
        self.functions = {
            node.name: node for node in module.body if isinstance(node, hr.FunctionDef)
        }
        self.explicit_returns = {
            name: function.return_type is not None
            for name, function in self.functions.items()
        }
        self.explicit_parameters = {
            (name, index): argument.annotation is not None
            for name, function in self.functions.items()
            for index, argument in enumerate(function.args)
        }
        self.anchored_parameters = {
            key for key, explicit in self.explicit_parameters.items() if explicit
        }
        self.anchored_locals = set()
        self.anchored_method_parameters = {
            (method.qualified_name, index)
            for class_info in symbols.classes.values()
            for method in class_info.methods.values()
            for index, argument in enumerate(method.args[1:])
            if argument.annotation is not None
        }
        self.call_graph = self._build_call_graph()
        self.components = self._find_components()
        self.changed = False
        self._infer_constructor_fields()

    def infer(self):
        # Calls and returns can propagate types across several functions, so scan
        # until a complete pass makes no signature changes.
        for _ in range(max(2, len(self.functions) * 4 + 2)):
            self.changed = False
            self._infer_constructor_fields()
            self._scan_top_level()
            for function in self.functions.values():
                self._scan_function(function)
            self._scan_class_methods()
            if not self.changed:
                break
        else:
            raise SignatureInferenceError("Function signature inference did not converge")

        self._require_complete_signatures()

    def _scan_class_methods(self):
        for class_info in self.symbols.classes.values():
            for method in class_info.methods.values():
                if method.name == "__init__" or method.return_type is not None:
                    continue
                environment = {
                    name: symbol.type
                    for name, symbol in self.symbols.functions[method.qualified_name][0].items()
                }
                returns = self._scan_block(method.body, environment, method.qualified_name)
                concrete = [item for item in returns if item is not None]
                if concrete:
                    inferred = concrete[0]
                    for candidate in concrete[1:]:
                        inferred = self._merge_return_types(method, inferred, candidate)
                    method.return_type = inferred
                    self.changed = True
                elif not self._contains_return(method.body):
                    method.return_type = NONE
                    self.changed = True

    def _build_call_graph(self):
        graph = {name: set() for name in self.symbols.functions}

        class Calls(hr.Walker):
            def __init__(self, destination, owner_class=None):
                self.destination = destination
                self.owner_class = owner_class

            def visit_Call(self, node):
                if node.func in graph:
                    self.destination.add(node.func)
                self.generic_walk(node)

            def visit_MethodCall(self, node):
                if (
                    self.owner_class is not None
                    and isinstance(node.receiver, hr.Name)
                    and node.receiver.id == "self"
                ):
                    qualified = f"{self.owner_class}.{node.method}"
                    if qualified in graph:
                        self.destination.add(qualified)
                self.generic_walk(node)

        for function in self.functions.values():
            Calls(graph[function.name]).traverse(function.body)
        for class_info in self.symbols.classes.values():
            for method in class_info.methods.values():
                Calls(graph[method.qualified_name], class_info.name).traverse(method.body)
        return graph

    def _find_components(self):
        index = 0
        indices = {}
        lowlinks = {}
        stack = []
        on_stack = set()
        component_by_function = {}
        component_id = 0

        def visit(name):
            nonlocal index, component_id
            indices[name] = index
            lowlinks[name] = index
            index += 1
            stack.append(name)
            on_stack.add(name)

            for called in self.call_graph[name]:
                if called not in indices:
                    visit(called)
                    lowlinks[name] = min(lowlinks[name], lowlinks[called])
                elif called in on_stack:
                    lowlinks[name] = min(lowlinks[name], indices[called])

            if lowlinks[name] == indices[name]:
                while True:
                    member = stack.pop()
                    on_stack.remove(member)
                    component_by_function[member] = component_id
                    if member == name:
                        break
                component_id += 1

        for name in self.call_graph:
            if name not in indices:
                visit(name)
        return component_by_function

    def _scan_top_level(self):
        environment = {
            name: symbol.type for name, symbol in self.symbols.top_level.items()
        }
        statements = [
            node for node in self.module.body if isinstance(node, hr.Statement)
        ]
        self._scan_block(statements, environment, None)

    def _scan_function(self, function):
        function_symbols = self.symbols.functions[function.name][0]
        environment = {
            name: symbol.type for name, symbol in function_symbols.items()
        }
        returns = self._scan_block(function.body, environment, function.name)

        if not self.explicit_returns[function.name]:
            concrete_returns = [item for item in returns if item is not None]
            if concrete_returns:
                inferred = concrete_returns[0]
                for candidate in concrete_returns[1:]:
                    inferred = self._merge_return_types(function, inferred, candidate)
                self._set_return_type(function, inferred)
            elif function.return_type is None and not self._contains_return(function.body):
                self._set_return_type(function, NONE)

    def _scan_block(self, statements, environment, caller):
        returns = []
        for statement in statements:
            if isinstance(statement, hr.Assign):
                value_type = self._infer_expression(statement.rhs, environment, caller)
                if value_type is not None:
                    self._bind_assignment_target(statement.lhs, value_type, environment)
                    if caller is not None and self._caller_expression_is_anchored(statement.rhs, caller):
                        for name in self._assignment_names(statement.lhs):
                            self.anchored_locals.add((caller, name))
            elif isinstance(statement, hr.Return):
                if statement.value is None:
                    returns.append(NONE)
                else:
                    returns.append(
                        self._infer_expression(statement.value, environment, caller)
                    )
            elif isinstance(statement, hr.Expr):
                self._infer_expression(statement.expr, environment, caller)
            elif isinstance(statement, (hr.If, hr.While)):
                self._infer_expression(statement.condition, environment, caller)
                returns.extend(self._scan_block(statement.body, dict(environment), caller))
                returns.extend(self._scan_block(statement.orelse or [], dict(environment), caller))
            elif isinstance(statement, hr.For):
                environment[statement.assignable.id] = INT
                for value in (statement.start, statement.end, statement.step):
                    if isinstance(value, hr.Expression):
                        self._infer_expression(value, environment, caller)
                returns.extend(self._scan_block(statement.body, dict(environment), caller))
            elif isinstance(statement, hr.Assert):
                self._infer_expression(statement.test, environment, caller)
        return returns

    def _infer_expression(self, node, environment, caller, expected=None):
        if isinstance(node, hr.Constant):
            if type(node.value) is bool:
                return BOOL
            if type(node.value) is int:
                return FLOAT if expected == FLOAT else INT
            if type(node.value) is float:
                return FLOAT
            if type(node.value) is str:
                return STR if expected == STR or len(node.value) != 1 else CHAR
            if node.value is None:
                return NONE
            return None

        if isinstance(node, hr.Name):
            return environment.get(node.id)

        if isinstance(node, hr.List):
            expected_element = expected.element_type if isinstance(expected, ListType) else None
            if not node.elements:
                return ListType(expected_element) if expected_element is not None else None
            elements = [
                self._infer_expression(item, environment, caller, expected_element)
                for item in node.elements
            ]
            if any(item is None for item in elements):
                return None
            merged = elements[0]
            for item in elements[1:]:
                if item != merged:
                    return None
            return ListType(merged)

        if isinstance(node, hr.Tuple):
            expected_elements = expected.element_types if isinstance(expected, TupleType) else None
            if expected_elements is not None and len(expected_elements) != len(node.elements):
                return None
            elements = tuple(
                self._infer_expression(
                    item,
                    environment,
                    caller,
                    expected_elements[index] if expected_elements else None,
                )
                for index, item in enumerate(node.elements)
            )
            return None if any(item is None for item in elements) else TupleType(elements)

        if isinstance(node, hr.Starred):
            return self._infer_expression(node.value, environment, caller, expected)

        if isinstance(node, hr.JoinedStr):
            for value in node.values:
                self._infer_expression(value, environment, caller)
            return STR

        if isinstance(node, hr.FormattedValue):
            self._infer_expression(node.value, environment, caller)
            return STR

        if isinstance(node, hr.Subscript):
            container = self._infer_expression(node.value, environment, caller)
            self._infer_expression(node.slice, environment, caller, INT)
            if isinstance(container, ListType):
                return container.element_type
            if container == STR:
                return CHAR
            if isinstance(container, TupleType):
                index = self._integer_literal(node.slice)
                if index is None:
                    return None
                if index < 0:
                    index += len(container.element_types)
                if 0 <= index < len(container.element_types):
                    return container.element_types[index]
            return None

        if isinstance(node, hr.Attribute):
            receiver_type = self._infer_expression(node.value, environment, caller)
            if not isinstance(receiver_type, ClassType):
                return None
            class_info = self.symbols.classes.get(receiver_type.name)
            field = class_info.fields.get(node.attr) if class_info is not None else None
            return field.type if field is not None else None

        if isinstance(node, hr.UnaryOp):
            operand = self._infer_expression(node.operand, environment, caller, expected)
            if isinstance(operand, ClassType):
                magic = {ast.UAdd: "__pos__", ast.USub: "__neg__", ast.Invert: "__invert__"}.get(type(node.operator))
                class_info = self.symbols.classes.get(operand.name)
                method = class_info.methods.get(magic) if class_info is not None and magic else None
                return method.return_type if method is not None else None
            if isinstance(node.operator, ast.Not):
                return BOOL
            return operand

        if isinstance(node, hr.BinOp):
            left = self._infer_expression(node.left, environment, caller)
            right = self._infer_expression(node.right, environment, caller, left)
            operator = type(node.operator)
            if isinstance(left, ClassType) or isinstance(right, ClassType):
                methods = {
                    ast.Add: ("__add__", "__radd__"), ast.Sub: ("__sub__", "__rsub__"),
                    ast.Mult: ("__mul__", "__rmul__"), ast.Mod: ("__mod__", "__rmod__"),
                    ast.BitAnd: ("__and__", "__rand__"),
                    ast.BitOr: ("__or__", "__ror__"), ast.BitXor: ("__xor__", "__rxor__"),
                    ast.LShift: ("__lshift__", "__rlshift__"), ast.RShift: ("__rshift__", "__rrshift__"),
                    ast.Eq: ("__eq__", "__eq__"), ast.NotEq: ("__ne__", "__ne__"),
                    ast.Lt: ("__lt__", "__gt__"), ast.Gt: ("__gt__", "__lt__"),
                    ast.LtE: ("__le__", "__ge__"), ast.GtE: ("__ge__", "__le__"),
                }
                forward, reverse = methods.get(operator, (None, None))
                receiver = left if isinstance(left, ClassType) else right
                magic = forward if isinstance(left, ClassType) else reverse
                class_info = self.symbols.classes.get(receiver.name)
                method = class_info.methods.get(magic) if class_info is not None and magic else None
                return method.return_type if method is not None else None
            if operator in {
                ast.Eq, ast.NotEq, ast.Lt, ast.Gt, ast.LtE, ast.GtE,
                ast.And, ast.Or, ast.In, ast.NotIn,
            }:
                return BOOL
            if operator is ast.Add and left in {STR, CHAR} and right in {STR, CHAR}:
                return STR
            if operator is ast.Add and (
                (left == PTR and right in {INT, BOOL})
                or (left in {INT, BOOL} and right == PTR)
            ):
                return PTR
            if operator is ast.Sub and left == PTR and right in {INT, BOOL}:
                return PTR
            if operator is ast.Sub and left == PTR and right == PTR:
                return INT
            if operator is ast.Mult and (
                (left == STR and right in {INT, BOOL})
                or (left in {INT, BOOL} and right in {STR, CHAR})
            ):
                return STR
            if operator is ast.Mod:
                return INT if left in {INT, BOOL} and right in {INT, BOOL} else None
            if left is None or right is None:
                return None
            if left == FLOAT or right == FLOAT:
                return FLOAT if left in {INT, BOOL, FLOAT} and right in {INT, BOOL, FLOAT} else None
            if left in {INT, BOOL} and right in {INT, BOOL}:
                return INT
            return left if left == right else None

        if isinstance(node, hr.IfExpr):
            self._infer_expression(node.condition, environment, caller, BOOL)
            true_type = self._infer_expression(node.true_expr, environment, caller, expected)
            false_type = self._infer_expression(node.false_expr, environment, caller, expected or true_type)
            if true_type is None:
                return false_type
            if false_type is None:
                return true_type
            if true_type == false_type:
                return true_type
            if {true_type, false_type} == {INT, FLOAT}:
                return FLOAT
            return None

        if isinstance(node, hr.Call):
            return self._infer_call(node, environment, caller)

        if isinstance(node, hr.MethodCall):
            receiver_type = self._infer_expression(node.receiver, environment, caller)
            if receiver_type in {STR, CHAR} and node.method in string_runtime.METHODS:
                for argument, parameter_type in zip(
                    node.args, string_runtime.METHODS[node.method][1]
                ):
                    self._infer_expression(argument, environment, caller, parameter_type)
                return string_runtime.METHODS[node.method][2]
            if not isinstance(receiver_type, ClassType):
                return None
            class_info = self.symbols.classes.get(receiver_type.name)
            method = class_info.methods.get(node.method) if class_info is not None else None
            if method is None:
                return None
            self._infer_method_arguments(node, method, environment, caller)
            return method.return_type

        return None

    def _infer_call(self, node, environment, caller):
        if node.func in {"cast_str", "cast_int", "cast_ptr"} and len(node.args) == 1:
            source_type = PTR if node.func == "cast_str" else STR
            self._infer_expression(node.args[0], environment, caller, source_type)
            return {"cast_str": STR, "cast_int": INT, "cast_ptr": PTR}[node.func]
        if node.func in {"malloc", "free"} and len(node.args) == 1:
            argument_type = INT if node.func == "malloc" else PTR
            self._infer_expression(node.args[0], environment, caller, argument_type)
            return PTR if node.func == "malloc" else NONE
        if node.func == "input" and len(node.args) == 1:
            self._infer_expression(node.args[0], environment, caller, INT)
            return STR
        if node.func == "len" and len(node.args) == 1:
            value_type = self._infer_expression(node.args[0], environment, caller)
            if value_type == STR or isinstance(value_type, ListType):
                return INT
        if node.func in {"print", "printi", "prints", "printb", "printc"}:
            for argument in node.args:
                self._infer_expression(argument, environment, caller)
            return NONE
        if node.func in {"ord", "chr"}:
            required = CHAR if node.func == "ord" else INT
            if node.args:
                self._infer_expression(node.args[0], environment, caller, required)
            return INT if node.func == "ord" else CHAR
        if node.func in self.symbols.classes:
            class_info = self.symbols.classes[node.func]
            constructor = class_info.methods["__init__"]
            self._infer_method_arguments(node, constructor, environment, caller)
            return class_info.type
        if node.func not in self.functions and node.func in DUNDER_BUILTINS and len(node.args) == 1:
            receiver_type = self._infer_expression(node.args[0], environment, caller)
            if node.func == "str" and receiver_type in {INT, FLOAT, BOOL, CHAR, STR}:
                return STR
            if node.func == "str" and receiver_type == CHAR:
                return STR
            if isinstance(receiver_type, ClassType):
                dunder, required_return = DUNDER_BUILTINS[node.func]
                method = self.symbols.classes[receiver_type.name].methods.get(dunder)
                if node.func == "str" and method is None:
                    method = self.symbols.classes[receiver_type.name].methods.get("__repr__")
                    return STR
                if method is not None:
                    return required_return or method.return_type
        if node.func in self.functions:
            function = self.functions[node.func]
            parameter_types = [argument.annotation for argument in function.args]
            external = caller is None or caller not in self.components or self.components[caller] != self.components[node.func]
        elif node.func in self.builtins:
            builtin = self.builtins[node.func]
            parameter_types = list(builtin.parameter_types)
            external = False
            function = None
        else:
            return None

        argument_index = 0
        for argument in node.args:
            expected = parameter_types[argument_index] if argument_index < len(parameter_types) else None
            if (
                function is not None
                and external
                and argument_index < len(parameter_types)
                and not self.explicit_parameters[(function.name, argument_index)]
            ):
                # Every external call is independent evidence for an inferred
                # parameter. Do not contextualize it using an earlier call.
                expected = None
            actual = self._infer_expression(argument, environment, caller, expected)
            if isinstance(argument, hr.Starred):
                if not isinstance(actual, TupleType):
                    continue
                actual_types = actual.element_types
            else:
                actual_types = (actual,)

            for actual_type in actual_types:
                if argument_index >= len(parameter_types):
                    break
                anchored_internal = (
                    function is not None
                    and not external
                    and caller is not None
                    and caller in self.functions
                    and self._expression_is_anchored(argument, caller)
                )
                if function is not None and (external or anchored_internal) and actual_type is not None:
                    self._constrain_parameter(
                        function,
                        argument_index,
                        actual_type,
                        node,
                        external,
                    )
                    parameter_types[argument_index] = function.args[argument_index].annotation
                argument_index += 1

        if function is not None:
            return function.return_type
        return self.builtins[node.func].return_type

    def _infer_method_arguments(self, call, method, environment, caller):
        parameters = method.args[1:]
        parameter_index = 0
        for argument in call.args:
            expected = parameters[parameter_index].annotation if parameter_index < len(parameters) else None
            actual = self._infer_expression(argument, environment, caller, expected)
            actual_types = actual.element_types if isinstance(argument, hr.Starred) and isinstance(actual, TupleType) else (actual,)
            for actual_type in actual_types:
                if parameter_index >= len(parameters):
                    return
                parameter = parameters[parameter_index]
                external = (
                    caller is None
                    or caller not in self.components
                    or self.components[caller] != self.components[method.qualified_name]
                )
                anchored_internal = (
                    not external
                    and caller is not None
                    and self._method_expression_is_anchored(argument, caller)
                )
                if actual_type is not None and (external or anchored_internal):
                    if parameter.annotation is None:
                        parameter.annotation = actual_type
                        symbol = self.symbols.functions[method.qualified_name][0][parameter.name]
                        symbol.type = actual_type
                        self.anchored_method_parameters.add((method.qualified_name, parameter_index))
                        self.changed = True
                    elif parameter.annotation != actual_type:
                        raise SignatureInferenceError(
                            f"Conflicting calls for parameter '{parameter.name}' of "
                            f"'{method.qualified_name}': found {parameter.annotation} and {actual_type} "
                            f"(line: {call.lineno})"
                        )
                parameter_index += 1

    def _method_expression_is_anchored(self, node, caller):
        if isinstance(node, hr.Name):
            _, method = self.symbols.functions[caller]
            for index, argument in enumerate(method.args[1:]):
                if argument.name == node.id:
                    return (caller, index) in self.anchored_method_parameters
            return (caller, node.id) in self.anchored_locals
        if isinstance(node, hr.Attribute):
            return True
        if isinstance(node, hr.Starred):
            return self._method_expression_is_anchored(node.value, caller)
        if isinstance(node, (hr.Tuple, hr.List)):
            return any(self._method_expression_is_anchored(item, caller) for item in node.elements)
        if isinstance(node, hr.Subscript):
            return self._method_expression_is_anchored(node.value, caller)
        if isinstance(node, hr.UnaryOp):
            return self._method_expression_is_anchored(node.operand, caller)
        if isinstance(node, hr.BinOp):
            return self._method_expression_is_anchored(node.left, caller) or self._method_expression_is_anchored(node.right, caller)
        return isinstance(node, hr.Constant)

    def _caller_expression_is_anchored(self, node, caller):
        if caller in self.functions:
            return self._expression_is_anchored(node, caller)
        if caller in self.symbols.functions:
            return self._method_expression_is_anchored(node, caller)
        return False

    def _infer_constructor_fields(self):
        """Make fields assigned by __init__ available to call-site inference."""
        for class_info in self.symbols.classes.values():
            constructor = class_info.methods["__init__"]
            environment = {
                argument.name: argument.annotation for argument in constructor.args
            }

            class FindAssignments(hr.Walker):
                def visit_Assign(inner_self, assignment):
                    target = assignment.lhs
                    if (
                        isinstance(target, hr.Attribute)
                        and isinstance(target.value, hr.Name)
                        and target.value.id == "self"
                    ):
                        field_type = self._infer_expression(
                            assignment.rhs, environment, None
                        )
                        if field_type is not None:
                            existing = class_info.fields.get(target.attr)
                            if existing is None:
                                class_info.fields[target.attr] = FieldInfo(target.attr, field_type)
                            elif existing.type != field_type:
                                raise SignatureInferenceError(
                                    f"Field '{class_info.name}.{target.attr}' is assigned incompatible types "
                                    f"{existing.type} and {field_type} (line: {assignment.lineno})"
                                )
                    inner_self.generic_walk(assignment)

            FindAssignments().traverse(constructor.body)

    def _constrain_parameter(self, function, index, actual_type, call, external):
        argument = function.args[index]
        if argument.annotation is None:
            argument.annotation = actual_type
            symbol = self.symbols.functions[function.name][0][argument.name]
            symbol.type = actual_type
            self.anchored_parameters.add((function.name, index))
            self.changed = True
        elif (
            not self.explicit_parameters[(function.name, index)]
            and argument.annotation != actual_type
        ):
            if {argument.annotation, actual_type} == {INT, BOOL}:
                argument.annotation = INT
                symbol = self.symbols.functions[function.name][0][argument.name]
                symbol.type = INT
                self.changed = True
                return
            raise SignatureInferenceError(
                f"Conflicting {'external' if external else 'recursive'} calls for parameter "
                f"'{argument.name}' of "
                f"'{function.name}': found {argument.annotation} and {actual_type} "
                f"(line: {call.lineno})"
            )

    def _set_return_type(self, function, inferred):
        if function.return_type is None:
            function.return_type = inferred
            self.changed = True
        elif function.return_type != inferred:
            merged = self._merge_return_types(function, function.return_type, inferred)
            if merged != function.return_type:
                function.return_type = merged
                self.changed = True

    def _merge_return_types(self, function, left, right):
        if left == right:
            return left
        if {left, right} == {INT, FLOAT}:
            return FLOAT
        if {left, right} == {INT, BOOL}:
            return INT
        raise SignatureInferenceError(
            f"Function '{function.name}' has incompatible inferred return types "
            f"{left} and {right} (line: {function.lineno})"
        )

    def _bind_assignment_target(self, target, value_type, environment):
        if isinstance(target, hr.Name):
            environment[target.id] = value_type
        elif isinstance(target, hr.TupleTarget) and isinstance(value_type, TupleType):
            for element, element_type in zip(target.elements, value_type.element_types):
                self._bind_assignment_target(element, element_type, environment)

    def _contains_return(self, statements):
        for statement in statements:
            if isinstance(statement, hr.Return):
                return True
            if isinstance(statement, (hr.If, hr.While, hr.For)):
                if self._contains_return(statement.body):
                    return True
                if hasattr(statement, "orelse") and self._contains_return(statement.orelse or []):
                    return True
        return False

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

    def _expression_is_anchored(self, node, caller):
        if isinstance(node, hr.Name):
            function = self.functions[caller]
            for index, argument in enumerate(function.args):
                if argument.name == node.id:
                    return (caller, index) in self.anchored_parameters
            return (caller, node.id) in self.anchored_locals
        if isinstance(node, hr.Starred):
            return self._expression_is_anchored(node.value, caller)
        if isinstance(node, (hr.Tuple, hr.List)):
            return any(self._expression_is_anchored(item, caller) for item in node.elements)
        if isinstance(node, hr.Subscript):
            return self._expression_is_anchored(node.value, caller)
        if isinstance(node, hr.Attribute):
            return self._expression_is_anchored(node.value, caller)
        if isinstance(node, hr.UnaryOp):
            return self._expression_is_anchored(node.operand, caller)
        if isinstance(node, hr.BinOp):
            return self._expression_is_anchored(node.left, caller) or self._expression_is_anchored(node.right, caller)
        if isinstance(node, hr.IfExpr):
            return self._expression_is_anchored(node.true_expr, caller) or self._expression_is_anchored(node.false_expr, caller)
        return False

    def _assignment_names(self, target):
        if isinstance(target, hr.Name):
            return [target.id]
        if isinstance(target, hr.TupleTarget):
            names = []
            for element in target.elements:
                names.extend(self._assignment_names(element))
            return names
        return []

    def _require_complete_signatures(self):
        for function in self.functions.values():
            for argument in function.args:
                if argument.annotation is None:
                    raise SignatureInferenceError(
                        f"Cannot infer parameter '{argument.name}' of function "
                        f"'{function.name}' from an external call; add an annotation"
                    )
            if function.return_type is None:
                raise SignatureInferenceError(
                    f"Cannot infer return type of function '{function.name}'; "
                    f"add an annotation or a concrete return value"
                )
        for class_info in self.symbols.classes.values():
            for method in class_info.methods.values():
                for argument in method.args:
                    if argument.annotation is None:
                        raise SignatureInferenceError(
                            f"Cannot infer parameter '{argument.name}' of method "
                            f"'{method.qualified_name}' from a call; add an annotation"
                        )
                if method.return_type is None:
                    raise SignatureInferenceError(
                        f"Cannot infer return type of method '{method.qualified_name}'; "
                        f"add an annotation or a concrete return value"
                    )


def infer_function_signatures(module, symbols, builtins):
    check_dead_code(module, symbols)
    SignatureInferer(module, symbols, builtins).infer()
