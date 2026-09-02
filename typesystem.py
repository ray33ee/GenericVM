from dataclasses import dataclass


class Type:
    """Base class for all source-language types."""


@dataclass(frozen=True)
class UnknownType(Type):
    def __str__(self):
        return "?"

    def __repr__(self):
        return "?"


@dataclass(frozen=True)
class PrimitiveType(Type):
    name: str

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


@dataclass(frozen=True)
class ListType(Type):
    element_type: Type

    def __str__(self):
        return f"list[{self.element_type}]"

    def __repr__(self):
        return str(self)


@dataclass(frozen=True)
class TupleType(Type):
    element_types: tuple[Type, ...]

    def __str__(self):
        return f"tuple[{', '.join(str(item) for item in self.element_types)}]"

    def __repr__(self):
        return str(self)


@dataclass(frozen=True)
class FunctionType(Type):
    parameter_types: tuple[Type, ...]
    return_type: Type

    def __str__(self):
        parameters = ", ".join(str(item) for item in self.parameter_types)
        return f"({parameters}) -> {self.return_type}"

    def __repr__(self):
        return str(self)


@dataclass(frozen=True)
class ClassType(Type):
    name: str

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


@dataclass(frozen=True)
class BuiltinSignature:
    parameter_types: tuple[Type, ...]
    return_type: Type
    opcode: int


INT = PrimitiveType("int")
FLOAT = PrimitiveType("float")
BOOL = PrimitiveType("bool")
STR = PrimitiveType("str")
CHAR = PrimitiveType("char")
PTR = PrimitiveType("ptr")
NONE = PrimitiveType("NoneType")
UNKNOWN = UnknownType()

# One-argument Python protocol conveniences. A None result means the dunder's
# declared return type is used (for iterator and value-producing protocols).
DUNDER_BUILTINS = {
    "len": ("__len__", INT),
    "int": ("__int__", INT),
    "float": ("__float__", FLOAT),
    "str": ("__str__", STR),
    "bool": ("__bool__", BOOL),
    "next": ("__next__", None),
    "iter": ("__iter__", None),
    "abs": ("__abs__", None),
    "hash": ("__hash__", INT),
    "repr": ("__repr__", STR),
    "reversed": ("__reversed__", None),
}

# Retained solely so an unparameterised annotation can receive a targeted error.
LIST = PrimitiveType("list")


PRIMITIVE_TYPES = {
    primitive.name: primitive
    for primitive in (INT, FLOAT, BOOL, STR, CHAR, PTR, NONE, LIST)
}


def primitive_type(name: str) -> PrimitiveType:
    try:
        return PRIMITIVE_TYPES[name]
    except KeyError:
        raise ValueError(f"Unknown primitive type '{name}'") from None


def word_count(value_type: Type) -> int:
    """Number of VM words in the flattened runtime representation."""
    if value_type == NONE:
        return 0
    if value_type == STR:
        return 2
    if isinstance(value_type, TupleType):
        return sum(word_count(element) for element in value_type.element_types)
    return 1


def tuple_member_layout(tuple_type: TupleType, index: int) -> tuple[int, int]:
    """Return the flattened word offset and width of a logical tuple member."""
    if index < 0 or index >= len(tuple_type.element_types):
        raise IndexError(index)
    offset = sum(word_count(element) for element in tuple_type.element_types[:index])
    return offset, word_count(tuple_type.element_types[index])


def contains_tuple(value_type: Type) -> bool:
    if isinstance(value_type, TupleType):
        return True
    if isinstance(value_type, ListType):
        return contains_tuple(value_type.element_type)
    return False


def contains_unknown(value_type: Type) -> bool:
    if value_type == UNKNOWN:
        return True
    if isinstance(value_type, ListType):
        return contains_unknown(value_type.element_type)
    if isinstance(value_type, TupleType):
        return any(contains_unknown(item) for item in value_type.element_types)
    return False
