# Symbol table with entries for each function and a final entry for top level code (i.e. any statements in the module)
# This must be versatile, working with code that has a module containing statements, main, functions, and any combination of these

import hr
from typesystem import ClassType, NONE, Type, word_count


class FieldInfo:
    def __init__(self, name, field_type):
        self.name = name
        self.type = field_type
        self.offset = None
        self.word_width = None


class ClassInfo:
    def __init__(self, definition):
        self.definition = definition
        self.name = definition.name
        self.type = ClassType(definition.name)
        self.fields = {}
        self.methods = {}
        self.word_width = None



class Symbol:
    def __init__(self, identifier: str, declared_type: Type | None, is_global: bool, is_arg: bool, offset: int):
        self.identifier = identifier
        self.declared_type = declared_type
        # Milestone 2 may infer this when no declared type is present.
        self.type: Type | None = declared_type
        self.is_global = is_global
        self.is_arg = is_arg
        self.stack_offset = offset
        self.word_width = word_count(declared_type) if declared_type is not None else None

    def __repr__(self):
        return f"Symbol('{self.identifier}', {self.type!r}, {'Global' if self.is_global else 'Local'}, {'Argument' if self.is_arg else 'NonArg'}, {self.stack_offset}, width={self.word_width})"



class ExtractVariables(hr.Walker):
    def __init__(self, is_top_level: bool, globals):
        self.is_top_level = is_top_level
        # List of declared variables, either by assignment or by argument
        self.declared = { k: globals[k] for k in globals }
        self.all = {}
        self.global_offset = 0
        self.arg_offset = 0
        self.local_offset = 0

    def dead_variable_check(self):
        # Globals require a module-wide check after every function has been
        # visited, because a function body may be their only reader.
        if self.is_top_level:
            return

        # If declared contains local variables that do not appear in all then there are dead variables

        used_locals = list(filter(lambda x: self.declared[x].is_global == False, self.all))
        declared_locals = list(filter(lambda x: self.declared[x].is_global == False, self.declared))

        for declared in declared_locals:
            if declared == "self" and self.declared[declared].is_arg:
                # Methods may legitimately ignore their receiver, but it still
                # occupies an argument word in the VM call frame.
                self.all[declared] = self.declared[declared]
                continue
            if declared not in used_locals:
                raise Exception(f"Variable {declared} is declared but never read")


    def visit_Name(self, node):
        if node.id not in self.declared:
            raise Exception(f"Variable '{node.id}' is used before it is declared (line: {node.lineno})")

        self.all[node.id] = self.declared[node.id]

    def visit_Argument(self, node):


        if node.name in self.declared:
            if self.declared[node.name].type != node.annotation and node.annotation is not None:
                raise Exception(f"Redeclaring variables not supported (line: {node.lineno})")
            return

        self.declared[node.name] = Symbol(node.name, node.annotation, self.is_top_level, True, self.arg_offset)

        self.arg_offset += 1

    def visit_Assign(self, node):

        # Go ahead and walk rhs FIRST, that way if it contains any expressions containng LHS, this will be flagged as 'used before declared' error
        self.walk(node.rhs)

        if isinstance(node.lhs, hr.Subscript):
            self.walk(node.lhs.value)
            self.walk(node.lhs.slice)
            return

        if isinstance(node.lhs, hr.Attribute):
            self.walk(node.lhs.value)
            return

        if isinstance(node.lhs, hr.TupleTarget):
            self._declare_tuple_target(node.lhs)
            return

        self._declare_name(node.lhs, node.annotation)

    def _declare_name(self, node, annotation=None):
        if node.id in self.declared:
            if self.declared[node.id].type != annotation and annotation is not None:
                raise Exception(f"Redeclaring variables not supported (line: {node.lineno})")
            return
        self.declared[node.id] = Symbol(
            node.id,
            annotation,
            self.is_top_level,
            False,
            self.global_offset if self.is_top_level else self.local_offset,
        )

        if self.is_top_level:
            self.global_offset += 1
        else:
            self.local_offset += 1

    def _declare_tuple_target(self, target):
        for element in target.elements:
            if isinstance(element, hr.Name):
                self._declare_name(element)
            elif isinstance(element, hr.TupleTarget):
                self._declare_tuple_target(element)
            else:
                raise Exception(
                    f"Tuple assignment targets must be names or nested tuples (line: {target.lineno})"
                )

    def visit_For(self, node):
        self.walk(node.iterable)
        if node.target.id not in self.declared:
            self.declared[node.target.id] = Symbol(
                node.target.id,
                None,
                self.is_top_level,
                False,
                self.global_offset if self.is_top_level else self.local_offset,
            )
            if self.is_top_level:
                self.global_offset += 1
            else:
                self.local_offset += 1
        self.traverse(node.body)
        self.traverse(node.orelse)

    def results(self):
        return self.declared



class Symbols:
    def __init__(self, module: hr.Module):
        self.module = module
        self.functions = {}
        self.classes = {}

        for class_definition in (
            node for node in self.module.body if isinstance(node, hr.ClassDef)
        ):
            if class_definition.name in self.classes:
                raise Exception(f"Class '{class_definition.name}' is already defined")
            class_info = ClassInfo(class_definition)
            for field in class_definition.fields:
                if field.name in class_info.fields:
                    raise Exception(f"Field '{class_definition.name}.{field.name}' is duplicated")
                class_info.fields[field.name] = FieldInfo(field.name, field.type)
            for method in class_definition.methods:
                if method.name in class_info.methods:
                    raise Exception(f"Method '{method.qualified_name}' is duplicated")
                if method.name in class_info.fields:
                    raise Exception(f"Class member '{method.qualified_name}' conflicts with a field")
                if not method.args or method.args[0].name != "self":
                    raise Exception(f"Method '{method.qualified_name}' must have self as its first argument")
                if method.args[0].annotation is None:
                    method.args[0].annotation = class_info.type
                elif method.args[0].annotation != class_info.type:
                    raise Exception(f"Method '{method.qualified_name}' has an invalid self annotation")
                if method.name == "__init__":
                    if method.return_type is None:
                        method.return_type = NONE
                    elif method.return_type != NONE:
                        raise Exception(f"Constructor '{method.qualified_name}' must return NoneType")
                class_info.methods[method.name] = method
            if "__init__" not in class_info.methods:
                raise Exception(f"Class '{class_definition.name}' must define __init__")
            self.classes[class_definition.name] = class_info


        top = Symbols.process(list(filter(lambda x : isinstance(x, hr.Statement), self.module.body)), True)
        self.top_level = top.declared

        for name in self.top_level:
            if name in self.classes:
                raise Exception(f"Name '{name}' is already defined as a class")



        for func in filter(lambda x : isinstance(x, hr.FunctionDef), self.module.body):
            if func.name in self.functions or func.name in self.classes or func.name in self.top_level:
                raise Exception(f"Name '{func.name}' is already defined")
            visible_globals = {} if func.name.startswith("__gvm_") else top.declared
            self.functions[func.name] = Symbols.process(func, False, visible_globals).all, func
            #print(func.name + ": " + str(Symbols.process(func, False, top.declared).results()))

        for class_info in self.classes.values():
            for method in class_info.methods.values():
                self.functions[method.qualified_name] = (
                    Symbols.process(method, False, top.declared).all,
                    method,
                )

        self._top_level_extraction = top

    def dead_global_check(self):
        used_globals = {
            name
            for name, symbol in self._top_level_extraction.all.items()
            if symbol.is_global
        }
        for function_symbols, _ in self.functions.values():
            used_globals.update(
                name
                for name, symbol in function_symbols.items()
                if symbol.is_global
            )

        for name in self.top_level:
            if name not in used_globals:
                raise Exception(f"Global variable {name} is declared but never read")


    def count_args(self, func):
        return len(self.functions[func][1].args)

    def count_locals(self, func):
        return sum(
            symbol.word_width
            for symbol in self.functions[func][0].values()
            if not symbol.is_global and not symbol.is_arg
        )

    def count_arg_words(self, func):
        return sum(
            symbol.word_width
            for symbol in self.functions[func][0].values()
            if not symbol.is_global and symbol.is_arg
        )

    def count_globals(self):
        return sum(symbol.word_width for symbol in self.top_level.values())

    def calculate_layouts(self):
        """Replace declaration indexes with flattened VM-word offsets."""
        offset = 0
        for symbol in self.top_level.values():
            symbol.word_width = word_count(symbol.type)
            symbol.stack_offset = offset
            offset += symbol.word_width

        for function_symbols, _ in self.functions.values():
            arguments = sorted(
                (
                    symbol for symbol in function_symbols.values()
                    if not symbol.is_global and symbol.is_arg
                ),
                key=lambda symbol: symbol.stack_offset,
            )
            locals_ = sorted(
                (
                    symbol for symbol in function_symbols.values()
                    if not symbol.is_global and not symbol.is_arg
                ),
                key=lambda symbol: symbol.stack_offset,
            )

            offset = 0
            for symbol in arguments:
                symbol.word_width = word_count(symbol.type)
                symbol.stack_offset = offset
                offset += symbol.word_width

            offset = 0
            for symbol in locals_:
                symbol.word_width = word_count(symbol.type)
                symbol.stack_offset = offset
                offset += symbol.word_width

        for class_info in self.classes.values():
            offset = 0
            for field in class_info.fields.values():
                field.word_width = word_count(field.type)
                field.offset = offset
                offset += field.word_width
            class_info.word_width = offset

    def process(statements, is_top_level: bool, globals = {}):

        e = ExtractVariables(is_top_level, globals)

        if isinstance(statements, list):

            for s in statements:
                e.walk(s)
        else:
            e.walk(statements)

        e.dead_variable_check()

        return e

