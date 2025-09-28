# Symbol table with entries for each function and a final entry for top level code (i.e. any statements in the module)
# This must be versatile, working with code that has a module containing statements, main, functions, and any combination of these

import hr



class Symbol:
    def __init__(self, identifier: str, annotation: str, is_global: bool, is_arg: bool, offset: int):
        self.identifier = identifier
        self.annotation = annotation
        self.is_global = is_global
        self.is_arg = is_arg
        self.stack_offset = offset

    def __repr__(self):
        return f"Symbol('{self.identifier}', '{self.annotation}', {'Global' if self.is_global else 'Local'}, {'Argument' if self.is_arg else 'NonArg'}, {self.stack_offset})"



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

        # Dont perform analysis for global variables, cba right now
        # todo: perform analysis for global variables
        if self.is_top_level:
            return

        # If declared contains local variables that do not appear in all then there are dead variables

        used_locals = list(filter(lambda x: self.declared[x].is_global == False, self.all))
        declared_locals = list(filter(lambda x: self.declared[x].is_global == False, self.declared))

        for declared in declared_locals:
            if declared not in used_locals:
                raise Exception(f"Variable {declared} is declared but never read")


    def visit_Name(self, node):
        if node.id not in self.declared:
            raise Exception(f"Variable '{node.id}' is used before it is declared (line: {node.lineno})")

        self.all[node.id] = self.declared[node.id]

    def visit_Argument(self, node):


        if node.name in self.declared:
            if self.declared[node.name] != node.annotation and node.annotation is not None:
                raise Exception(f"Redeclaring variables not supported (line: {node.lineno})")
            return
        else:
            if node.annotation is None:
                raise Exception(f"First declaration of '{node.lhs.id}' must contain type annotation (line: {node.lineno})")

        self.declared[node.name] = Symbol(node.name, node.annotation, self.is_top_level, True, self.arg_offset)

        self.arg_offset += 1

    def visit_Assign(self, node):

        # Go ahead and walk rhs FIRST, that way if it contains any expressions containng LHS, this will be flagged as 'used before declared' error
        self.walk(node.rhs)

        if isinstance(node.lhs, hr.Subscript):
            return

        if node.lhs.id in self.declared:
            if self.declared[node.lhs.id] != node.annotation and node.annotation is not None:
                raise Exception(f"Redeclaring variables not supported (line: {node.lineno})")
            return
        else:
            if node.annotation is None:
                raise Exception(f"First declaration of '{node.lhs.id}' must contain type annotation (line: {node.lineno})")



        self.declared[node.lhs.id] = Symbol(node.lhs.id, node.annotation, self.is_top_level, False, self.global_offset if self.is_top_level else self.local_offset)

        if self.is_top_level:
            self.global_offset += 1
        else:
            self.local_offset += 1

    def results(self):
        return self.declared



class Symbols:
    def __init__(self, module: hr.Module):
        self.module = module
        self.functions = {}


        top = Symbols.process(list(filter(lambda x : isinstance(x, hr.Statement), self.module.body)), True)
        self.top_level = top.declared



        for func in filter(lambda x : isinstance(x, hr.FunctionDef), self.module.body):
            self.functions[func.name] = Symbols.process(func, False, top.declared).all, func
            #print(func.name + ": " + str(Symbols.process(func, False, top.declared).results()))


    def count_args(self, func):
        return len(self.functions[func][1].args)

    def count_locals(self, func):
        return len(list(filter(lambda x : x.is_global == False and x.is_arg == False, self.functions[func][0].values())))

    def process(statements, is_top_level: bool, globals = {}):

        e = ExtractVariables(is_top_level, globals)

        if isinstance(statements, list):

            for s in statements:
                e.walk(s)
        else:
            e.walk(statements)

        e.dead_variable_check()

        return e

