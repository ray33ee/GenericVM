import ast

# Higher representation - Trimmed version of python ast modified to work with GenericVM

class HRNode:
    pass

class Expression(HRNode):
    pass

class Statement(HRNode):
    pass

class HRConstructor(ast.NodeVisitor):

    def generic_visit(self, node):
        raise Exception(f"Node '{str(type(node).__name__)}' not allowed")

    def traverse(self, node):
        if isinstance(node, list):
            return [self.traverse(item) for item in node]
        else:
            return self.visit(node)

    def visit_Module(self, node):
        body = self.traverse(node.body)
        for statement in body:
            if not isinstance(statement, Statement) and type(statement) != FunctionDef:
                raise Exception(f"Top level module statements must be functions or statements, found {statement}")
        return Module(body)

    def visit_FunctionDef(self, node):
        # Must contain a return annotation

        if node.args.kwarg is not None:
            raise Exception(f"**kwargs not allowed (line: {node.lineno})")

        if node.args.vararg is not None:
            raise Exception(f"*args not allowed (line: {node.lineno})")

        if len(node.args.posonlyargs) != 0:
            raise Exception(f"Pos only args not allowed (line: {node.lineno})")

        if len(node.args.kwonlyargs) != 0:
            raise Exception(f"KW only args not allowed (line: {node.lineno})")

        if len(node.args.defaults) != 0:
            raise Exception(f"Default arguments not yet supported (line: {node.lineno})")

        args: list[Argument] = []

        for a in node.args.args:

            if a.annotation is None:
                Exception(f"All function args must be annotated (line: {node.lineno})")

            # Todo: convert this function to allow annotations like list[int]

            if type(a.annotation) is not ast.Name:
                raise Exception(f"All function args must be annotated with int | float (line: {node.lineno})")

            annotation = a.annotation.id

            if annotation != "int" and annotation != "float":
                raise Exception(f"Only int and float type annotations for arguments are supported at this time (line: {node.lineno})")

            args.append(Argument(node.lineno, a.arg, a.annotation.id))

        if node.returns is None:
            raise Exception(f"Functions must have a return annotation (use -> NoneType for functions that have no return value) (line: {node.lineno})")

        if type(node.returns) is not ast.Name:
            raise Exception(f"Return type annotations must be NoneType | int | float (line: {node.lineno})")

        return_annotation = node.returns.id

        if return_annotation != "int" and return_annotation != "float" and return_annotation != "NoneType":
            raise Exception(f"Only int, float, None and NoneType type annotations are supported for return types at this time (line: {node.lineno})")

        return FunctionDef(node.lineno, node.name, args, self.traverse(node.body), return_annotation)

    def visit_Return(self, node):

        if node.value is None:
            return Return(node.lineno, None)
        else:
            return Return(node.lineno, self.traverse(node.value))


    def visit_Assign(self, node):
        if len(node.targets) != 1:
            raise Exception(f"Assignments can only work with single targets, i.e. x = y (line: {node.lineno})")

        lhs = node.targets[0]

        return Assign(node.lineno, self.traverse(lhs), self.traverse(node.value), None)

    def visit_AnnAssign(self, node):

        if type(node.target) is not ast.Name:
            raise Exception(f"LHS of annotated assignments must be a named variable (and not a subscript) (line: {node.lineno})")

        annotation = node.annotation.id

        if annotation != "int" and annotation != "float":
            raise Exception(f"Only int and float type annotations for assignment annotations are supported at this time (line: {node.lineno})")

        return Assign(node.lineno, self.traverse(node.target), self.traverse(node.value), annotation)

    def visit_For(self, node):

        if type(node.target) is not ast.Name and type(node.target) is not ast.Subscript:
            raise Exception(f"Counter of For loops must be either a named variable or a subscripted variable (line: {node.lineno})")

        if type(node.iter) is not ast.Call:
            raise Exception(f"Loop iterator MUST be range(stop) or range(start, stop[, step])")

        args = node.iter.args

        start = 0
        stop = None
        step = 1

        if len(args) == 1:
            stop = args[0].value
        elif len(args) == 2:
            start = args[0].value
            stop = args[1].value
        elif len(args) == 3:
            start = args[0].value
            stop = args[1].value
            step = args[2].value

        return For(node.lineno, self.traverse(node.target), start, stop, step, self.traverse(node.body))


    def visit_While(self, node):
        return While(node.lineno, self.traverse(node.test), self.traverse(node.body), self.traverse(node.orelse))

    def visit_If(self, node):
        return If(node.lineno, self.traverse(node.test), self.traverse(node.body), self.traverse(node.orelse))

    def visit_Assert(self, node):
        return Assert(node.lineno, self.traverse(node.test))

    def visit_Expr(self, node):
        return Expr(node.lineno, self.traverse(node.value))

    def visit_Pass(self, node):
        return Pass()

    def visit_Break(self, node):
        return Break()

    def visit_Continue(self, node):
        return Continue()

    def visit_AugAssign(self, node):
        return Assign(node.lineno, node.lineno, self.traverse(node.target), BinOp(self.traverse(node.target), node.op, self.traverse(node.value)))

    def visit_BoolOp(self, node):

        chained = BinOp(node.lineno, self.traverse(node.values[0]), node.op, self.traverse(node.values[1]))

        for i in range(len(node.values)-2):
            chained = BinOp(node.lineno, chained, node.op, self.traverse(node.values[i+2]))

        return chained

    def visit_BinOp(self, node):
        return BinOp(node.lineno, self.traverse(node.left), node.op, self.traverse(node.right))

    def visit_UnaryOp(self, node):
        return UnaryOp(node.lineno, self.traverse(node.operand), node.op)

    def visit_IfExp(self, node):
        return IfExpr(node.lineno, self.traverse(node.test), self.traverse(node.body), self.traverse(node.orelse))

    def visit_Compare(self, node):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise Exception(f"Chained comparison is not allowed. (line: {node.lineno})")

        operator = node.ops[0]

        if type(operator) is ast.Is or type(operator) is ast.IsNot:
            raise Exception(f"'is' operator not allowed. (line: {node.lineno})")

        if type(operator) is ast.In or type(operator) is ast.NotIn:
            raise Exception(f"'in' operator not allowed. (line: {node.lineno})")


        return BinOp(node.lineno, self.traverse(node.left), node.ops[0], self.traverse(node.comparators[0]))

    def visit_Call(self, node):
        if type(node.func) is not ast.Name:
            raise Exception(f"Can only call functions named at compile time. Cannot call expressions. (line: {node.lineno})")

        return Call(node.lineno, node.func.id, self.traverse(node.args))

    def visit_Constant(self, node):
        if type(node.value) is not int and type(node.value) is not float:
            raise Exception(f"Only int and float constants are supported, '{type(node.value).__name__}' not allowed. (line: {node.lineno})")

        return Constant(node.lineno, node.value)

    def visit_Subscript(self, node):
        if type(node.value) is not ast.Name:
            raise Exception(f"Can only subscript identifiers named at compile time. Cannot subscript expressions. (line: {node.lineno})")

        return Subscript(node.lineno, node.value.id, self.traverse(node.slice))

    def visit_Name(self, node):
        return Name(node.lineno, node.id)









class Argument(HRNode):
    def __init__(self, lineno: int, name: str, annotation: str):
        self.lineno = lineno
        self.name = name
        self.annotation = annotation

class FunctionDef(HRNode):
    def __init__(self, lineno: int, name: str, args: list[Argument], body: list[Statement], return_type: str):
        self.lineno = lineno
        self.name = name
        self.args = args
        self.body = body
        self.return_type = return_type

# Includes ast.BinOp, ast.BoolOp and ast.Compare
class BinOp(Expression):
    def __init__(self, lineno: int, left: Expression, operator: ast.operator | ast.cmpop | ast.boolop, right: Expression):
        self.lineno = lineno
        self.left = left
        self.operator = operator
        self.right = right

class UnaryOp(Expression):
    def __init__(self, lineno: int, operand: Expression, operator: ast.unaryop):
        self.lineno = lineno
        self.operand = operand
        self.operator = operator

class Name(Expression):
    def __init__(self, lineno: int, id: str):
        self.lineno = lineno
        self.id = id

class Constant(Expression):
    def __init__(self, lineno: int, value: int | float):
        self.lineno = lineno
        self.value = value

class Call(Expression):
    def __init__(self, lineno: int, func: str, args: list[Expression]):
        self.lineno = lineno
        self.func = func
        self.args = args

class IfExpr(Expression):
    def __init__(self, lineno: int, condition: Expression, true_body: Expression, false_body: Expression):
        self.lineno = lineno
        self.condition = condition
        self.true_body = true_body
        self.false_body = false_body

class Subscript(Expression):
    def __init__(self, lineno: int, name: str, index: Expression):
        self.lineno = lineno
        self.name = name
        self.index = index



class Return(Statement):
    def __init__(self, lineno: int, value: Expression | None):
        self.lineno = lineno
        self.value = value


class Assign(Statement):
    def __init__(self, lineno: int, lhs: Name | Subscript, rhs: Expression, annotation: str | None = None):
        self.lineno = lineno
        self.lhs = lhs
        self.rhs = rhs
        self.annotation = annotation


class For(Statement):
    def __init__(self, lineno: int, assignable: Name | Subscript, start: int, end: int, step: int, body: list[Statement]):
        self.lineno = lineno
        self.assignable = assignable
        self.start = start
        self.end = end
        self.step = step
        self.body = body

class While(Statement):
    def __init__(self, lineno: int, condition: Expression, body: list[Statement], orelse: list[Statement] | None):
        self.lineno = lineno
        self.condition = condition
        self.body= body
        self.orelse = orelse

class If(Statement):
    def __init__(self, lineno: int, condition: Expression, body: list[Statement], orelse: list[Statement] | None):
        self.lineno = lineno
        self.condition = condition
        self.body = body
        self.orelse = orelse

class Assert(Statement):
    def __init__(self, lineno: int, test: Expression):
        self.lineno = lineno
        self.test = test

class Expr(Statement):
    def __init__(self, lineno: int, expr: Expression):
        self.lineno = lineno
        self.expr = expr

class Pass(Statement):
    pass

class Break(Statement):
    pass

class Continue(Statement):
    pass

class Module(HRNode):
    def __init__(self, body: list[Statement | FunctionDef]):
        self.body = body

def filtered_vars(obj):
    return {k: v for k, v in vars(obj).items() if not k.startswith("lineno")}

def ast_to_hr(node: ast.Module):
    c = HRConstructor()
    return c.visit(node)

def dump(node: "HRNode"):
    s = []

    def render_value(value, level: int):
        if isinstance(value, list):
            s.append("[\n")
            for j, a in enumerate(value):
                s.append("\t" * (level + 1))
                _format(a, level + 1)
                if j != len(value) - 1:
                    s.append(",\n")
                else:
                    s.append("\n")
            s.append("\t" * level)
            s.append("]")
        elif isinstance(value, str):
            s.append(repr(value))
        elif isinstance(value, (int, float)) or value is None:
            s.append(str(value))
        else:
            _format(value, level)

    def _format(node, level: int = 0):
        s.append(f"{type(node).__name__}(")
        attrs = list(filtered_vars(node).items())
        if attrs:
            s.append("\n")
            for i, (attr, val) in enumerate(attrs):
                s.append("\t" * (level + 1))
                s.append(f"{attr}=")
                render_value(val, level + 1)
                if i != len(attrs) - 1:
                    s.append(",\n")
                else:
                    s.append("\n")
            s.append("\t" * level)
        s.append(")")

    _format(node)
    return "".join(s)


class Walker:

    def generic_walk(self, node: HRNode):

        attrs = filtered_vars(node).items()


        for attr, value in attrs:
            if isinstance(value, list):
                for n in value:
                    self.walk(n)
            elif isinstance(value, HRNode):
                self.walk(value)

    def traverse(self, node):
        if isinstance(node, list):
            for n in node:
                self.walk(n)
        else:
            self.walk(node)

    def walk(self, node: HRNode):
        method = 'visit_' + node.__class__.__name__
        visitor = getattr(self, method, self.generic_walk)
        return visitor(node)
