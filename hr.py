import ast
from dataclasses import dataclass
from typesystem import ClassType, FLOAT, INT, NONE, STR, ListType, TupleType, Type, primitive_type

# Higher representation - Trimmed version of python ast modified to work with GenericVM

@dataclass(frozen=True)
class SourceSpan:
    filename: str | None
    line: int
    column: int
    end_line: int
    end_column: int
    source_line: str | None = None


class HRNode:
    pass

class Expression(HRNode):
    def __init__(self):
        # Filled by the dedicated type-analysis pass in milestone 2.
        self.type: Type | None = None

class Statement(HRNode):
    pass


def parse_annotation(node: ast.expr, allowed: set[Type] | None = None) -> Type:
    """Convert a supported annotation AST node into a source-language Type."""
    if isinstance(node, ast.Subscript):
        if not isinstance(node.value, ast.Name):
            raise Exception(f"Invalid type annotation (line: {node.lineno})")

        if node.value.id == "list":
            annotation = ListType(parse_annotation(node.slice))
        elif node.value.id == "tuple":
            elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            annotation = TupleType(tuple(parse_annotation(element) for element in elements))
        else:
            raise Exception(f"Unknown generic type '{node.value.id}' (line: {node.lineno})")
    elif isinstance(node, ast.Name):
        if node.id in {"list", "tuple"}:
            raise Exception(
                f"Type '{node.id}' requires element type arguments (line: {node.lineno})"
            )

        try:
            annotation = primitive_type(node.id)
        except ValueError:
            annotation = ClassType(node.id)
    elif isinstance(node, ast.Constant) and node.value is None:
        annotation = NONE
    else:
        raise Exception(f"Invalid type annotation (line: {node.lineno})")

    if allowed is not None and annotation not in allowed:
        expected = " | ".join(sorted(str(item) for item in allowed))
        raise Exception(
            f"Type annotation must be one of {expected}, found {annotation} (line: {node.lineno})"
        )

    return annotation


def parse_primitive_annotation(node: ast.expr, allowed: set[Type] | None = None) -> Type:
    """Backward-compatible name for milestone 1 callers."""
    annotation = parse_annotation(node, allowed)
    if not isinstance(annotation, type(INT)):
        raise Exception(f"Expected a primitive type annotation (line: {node.lineno})")
    return annotation

class HRConstructor(ast.NodeVisitor):

    def __init__(self, source: str | None = None, filename: str | None = None):
        self.filename = filename
        self.source_lines = source.splitlines() if source is not None else None

    def visit(self, node):
        result = super().visit(node)
        if isinstance(node, ast.AST) and isinstance(result, HRNode):
            line = getattr(node, "lineno", 1)
            end_line = getattr(node, "end_lineno", line)
            column = getattr(node, "col_offset", 0)
            end_column = getattr(node, "end_col_offset", column + 1)
            source_line = None
            if self.source_lines is not None and 0 < line <= len(self.source_lines):
                source_line = self.source_lines[line - 1]
                # CPython AST columns are UTF-8 byte offsets; diagnostics need
                # character offsets to align carets with displayed source.
                column = len(source_line.encode("utf-8")[:column].decode("utf-8"))
                if end_line == line:
                    end_column = len(
                        source_line.encode("utf-8")[:end_column].decode("utf-8")
                    )
            result.source_span = SourceSpan(
                self.filename, line, column, end_line, end_column, source_line
            )
            if not hasattr(result, "lineno"):
                result.lineno = line
        return result

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
            if not isinstance(statement, Statement) and not isinstance(statement, (FunctionDef, ClassDef)):
                raise Exception(f"Top level module statements must be functions or statements, found {statement}")
        return Module(body)

    def visit_ClassDef(self, node):
        if node.bases or node.keywords:
            raise Exception(f"Class inheritance is not supported (line: {node.lineno})")
        if node.decorator_list:
            raise Exception(f"Class decorators are not supported (line: {node.lineno})")

        fields = []
        methods = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign):
                if not isinstance(item.target, ast.Name):
                    raise Exception(f"Class fields must be named (line: {item.lineno})")
                if item.value is not None:
                    raise Exception(f"Class field defaults are not supported (line: {item.lineno})")
                fields.append(FieldDef(item.lineno, item.target.id, parse_annotation(item.annotation)))
            elif isinstance(item, ast.FunctionDef):
                method = self.visit(item)
                method.owner_class = node.name
                method.qualified_name = f"{node.name}.{method.name}"
                methods.append(method)
            elif isinstance(item, ast.Pass):
                continue
            else:
                raise Exception(
                    f"Class bodies may contain only annotated fields and methods (line: {item.lineno})"
                )
        return ClassDef(node.lineno, node.name, fields, methods)

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

        args: list[Argument] = []

        default_offset = len(node.args.args) - len(node.args.defaults)

        for index, a in enumerate(node.args.args):

            if a.annotation is None:
                annotation = None
            else:
                annotation = parse_annotation(a.annotation)
            default = None
            if index >= default_offset:
                default = self.traverse(node.args.defaults[index - default_offset])
            args.append(Argument(node.lineno, a.arg, annotation, default))

        return_annotation = parse_annotation(node.returns) if node.returns is not None else None

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

        annotation = parse_annotation(node.annotation)

        return Assign(node.lineno, self.traverse(node.target), self.traverse(node.value), annotation)

    def visit_For(self, node):
        if type(node.target) is not ast.Name:
            raise Exception(f"Target of a for loop must be a named variable (line: {node.lineno})")
        return For(
            node.lineno,
            self.traverse(node.target),
            self.traverse(node.iter),
            self.traverse(node.body),
            self.traverse(node.orelse),
        )


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
        return Assign(node.lineno, self.traverse(node.target), BinOp(node.lineno, self.traverse(node.target), node.op, self.traverse(node.value)))

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

        if isinstance(operator, (ast.In, ast.NotIn)):
            call = MethodCall(node.lineno, self.traverse(node.comparators[0]),
                              "__contains__", [self.traverse(node.left)])
            return UnaryOp(node.lineno, call, ast.Not()) if isinstance(operator, ast.NotIn) else call

        if type(operator) is ast.Is or type(operator) is ast.IsNot:
            raise Exception(f"'is' operator not allowed. (line: {node.lineno})")

        return BinOp(node.lineno, self.traverse(node.left), node.ops[0], self.traverse(node.comparators[0]))

    def visit_Call(self, node):
        if node.keywords:
            raise Exception(f"Keyword arguments are not supported (line: {node.lineno})")
        if isinstance(node.func, ast.Attribute):
            return MethodCall(
                node.lineno,
                self.traverse(node.func.value),
                node.func.attr,
                self.traverse(node.args),
            )
        if type(node.func) is not ast.Name:
            return MethodCall(node.lineno, self.traverse(node.func), "__call__", self.traverse(node.args))

        return Call(node.lineno, node.func.id, self.traverse(node.args))

    def visit_Constant(self, node):
        if type(node.value) not in {bool, int, float, str} and node.value is not None:
            raise Exception(f"Constant type '{type(node.value).__name__}' is not supported. (line: {node.lineno})")

        return Constant(node.lineno, node.value)

    def visit_List(self, node):
        return List(node.lineno, [self.traverse(e) for e in node.elts])

    def visit_JoinedStr(self, node):
        return JoinedStr(node.lineno, [self.traverse(value) for value in node.values])

    def visit_FormattedValue(self, node):
        if node.conversion != -1:
            raise Exception(f"F-string conversions are not supported (line: {node.lineno})")
        if node.format_spec is not None:
            raise Exception(f"F-string format specifications are not supported (line: {node.lineno})")
        return FormattedValue(node.lineno, self.traverse(node.value))

    def visit_Tuple(self, node):
        if isinstance(node.ctx, ast.Store):
            return TupleTarget(node.lineno, [self.traverse(e) for e in node.elts])
        return Tuple(node.lineno, [self.traverse(e) for e in node.elts])

    def visit_Starred(self, node):
        if not isinstance(node.ctx, ast.Load):
            raise Exception(
                f"Starred assignment targets are not currently supported (line: {node.lineno})"
            )
        return Starred(node.lineno, self.traverse(node.value))




    def visit_Subscript(self, node):

        return Subscript(node.lineno, self.traverse(node.value), self.traverse(node.slice), node.ctx)

    def visit_Slice(self, node):
        return Slice(
            node.lineno,
            self.traverse(node.lower) if node.lower is not None else None,
            self.traverse(node.upper) if node.upper is not None else None,
            self.traverse(node.step) if node.step is not None else None,
        )

    def visit_Name(self, node):
        return Name(node.lineno, node.id)

    def visit_Attribute(self, node):
        return Attribute(node.lineno, self.traverse(node.value), node.attr, node.ctx)









class Argument(HRNode):
    def __init__(self, lineno: int, name: str, annotation: Type | None, default: Expression | None = None):
        self.lineno = lineno
        self.name = name
        self.annotation = annotation
        self.default = default

class FunctionDef(HRNode):
    def __init__(self, lineno: int, name: str, args: list[Argument], body: list[Statement], return_type: Type | None):
        self.lineno = lineno
        self.name = name
        self.args = args
        self.body = body
        self.return_type = return_type
        self.owner_class = None
        self.qualified_name = name


class FieldDef(HRNode):
    def __init__(self, lineno: int, name: str, field_type: Type):
        self.lineno = lineno
        self.name = name
        self.type = field_type


class ClassDef(HRNode):
    def __init__(self, lineno: int, name: str, fields: list[FieldDef], methods: list[FunctionDef]):
        self.lineno = lineno
        self.name = name
        self.fields = fields
        self.methods = methods

# Includes ast.BinOp, ast.BoolOp and ast.Compare
class BinOp(Expression):
    def __init__(self, lineno: int, left: Expression, operator: ast.operator | ast.cmpop | ast.boolop, right: Expression):
        super().__init__()
        self.lineno = lineno
        self.left = left
        self.operator = operator
        self.right = right

class UnaryOp(Expression):
    def __init__(self, lineno: int, operand: Expression, operator: ast.unaryop):
        super().__init__()
        self.lineno = lineno
        self.operand = operand
        self.operator = operator

class Name(Expression):
    def __init__(self, lineno: int, id: str):
        super().__init__()
        self.lineno = lineno
        self.id = id

class Constant(Expression):
    def __init__(self, lineno: int, value: int | float):
        super().__init__()
        self.lineno = lineno
        self.value = value

class List(Expression):
    def __init__(self, lineno: int, elements: list[Expression]):
        super().__init__()
        self.lineno = lineno
        self.elements = elements


class Tuple(Expression):
    def __init__(self, lineno: int, elements: list[Expression]):
        super().__init__()
        self.lineno = lineno
        self.elements = elements


class Starred(Expression):
    def __init__(self, lineno: int, value: Expression):
        super().__init__()
        self.lineno = lineno
        self.value = value


class JoinedStr(Expression):
    def __init__(self, lineno: int, values: list[Expression]):
        super().__init__()
        self.lineno = lineno
        self.values = values


class FormattedValue(Expression):
    def __init__(self, lineno: int, value: Expression):
        super().__init__()
        self.lineno = lineno
        self.value = value


class TupleTarget(HRNode):
    def __init__(self, lineno: int, elements: list[HRNode]):
        self.lineno = lineno
        self.elements = elements
        self.type: Type | None = None

class Call(Expression):
    def __init__(self, lineno: int, func: str, args: list[Expression]):
        super().__init__()
        self.lineno = lineno
        self.func = func
        self.args = args


class MethodCall(Expression):
    def __init__(self, lineno: int, receiver: Expression, method: str, args: list[Expression]):
        super().__init__()
        self.lineno = lineno
        self.receiver = receiver
        self.method = method
        self.args = args


class Attribute(Expression):
    def __init__(self, lineno: int, value: Expression, attr: str, context: ast.expr_context):
        super().__init__()
        self.lineno = lineno
        self.value = value
        self.attr = attr
        self.context = context

class IfExpr(Expression):
    def __init__(self, lineno: int, condition: Expression, true_expr: Expression, false_expr: Expression):
        super().__init__()
        self.lineno = lineno
        self.condition = condition
        self.true_expr = true_expr
        self.false_expr = false_expr


class Subscript(Expression):
    def __init__(self, lineno: int, value: Expression, slice: Expression, context: ast.expr_context):
        super().__init__()
        self.lineno = lineno
        self.value = value
        self.slice = slice
        self.context = context


class Slice(HRNode):
    def __init__(
        self,
        lineno: int,
        lower: Expression | None,
        upper: Expression | None,
        step: Expression | None,
    ):
        self.lineno = lineno
        self.lower = lower
        self.upper = upper
        self.step = step


class Return(Statement):
    def __init__(self, lineno: int, value: Expression | None):
        self.lineno = lineno
        self.value = value


class Assign(Statement):
    def __init__(self, lineno: int, lhs: Name | Subscript | Attribute | TupleTarget, rhs: Expression, annotation: Type | None = None):
        self.lineno = lineno
        self.lhs = lhs
        self.rhs = rhs
        self.annotation = annotation


class For(Statement):
    def __init__(self, lineno: int, target: Name, iterable: Expression, body: list[Statement], orelse: list[Statement] | None):
        self.lineno = lineno
        self.target = target
        self.iterable = iterable
        self.body = body
        self.orelse = orelse

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
    return {
        k: v for k, v in vars(obj).items()
        if not k.startswith("lineno") and k != "source_span"
    }

def ast_to_hr(node: ast.Module, *, source: str | None = None, filename: str | None = None):
    c = HRConstructor(source=source, filename=filename)
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
