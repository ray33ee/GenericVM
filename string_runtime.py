"""Source-level ASCII string runtime compiled with the user's program.

The two private intrinsics used here lower to existing heap/stack IR.  Public
operations are normal functions and therefore require no string-specific VM
instructions.
"""

import ast

import hr
from typesystem import BOOL, CHAR, INT, STR, ListType


PREFIX = "__gvm_str_"

METHODS = {
    "__contains__": ("contains", (STR,), BOOL),
    "substr": ("slice", (INT, INT), STR),
    "find": ("find", (STR,), INT),
    "rfind": ("rfind", (STR,), INT),
    "count": ("count", (STR,), INT),
    "startswith": ("startswith", (STR,), BOOL),
    "endswith": ("endswith", (STR,), BOOL),
    "removeprefix": ("removeprefix", (STR,), STR),
    "removesuffix": ("removesuffix", (STR,), STR),
    "replace": ("replace", (STR, STR), STR),
    "lower": ("lower", (), STR),
    "casefold": ("lower", (), STR),
    "upper": ("upper", (), STR),
    "swapcase": ("swapcase", (), STR),
    "capitalize": ("capitalize", (), STR),
    "title": ("title", (), STR),
    "strip": ("strip", (), STR),
    "lstrip": ("lstrip", (), STR),
    "rstrip": ("rstrip", (), STR),
    "isascii": ("isascii", (), BOOL),
    "isalpha": ("isalpha", (), BOOL),
    "isalnum": ("isalnum", (), BOOL),
    "isdecimal": ("isdecimal", (), BOOL),
    "isdigit": ("isdecimal", (), BOOL),
    "isnumeric": ("isdecimal", (), BOOL),
    "islower": ("islower", (), BOOL),
    "isupper": ("isupper", (), BOOL),
    "isspace": ("isspace", (), BOOL),
    "isprintable": ("isprintable", (), BOOL),
    "istitle": ("istitle", (), BOOL),
    "isidentifier": ("isidentifier", (), BOOL),
    "join": ("join", (ListType(STR),), STR),
    "expandtabs": ("expandtabs", (), STR),
    "zfill": ("zfill", (INT,), STR),
}


SOURCE = r'''
def __gvm_str_contains(text: str, sub: str) -> bool:
    return __gvm_str_find(text, sub) != -1

def __gvm_int_str_is_space(value: int) -> bool:
    return value == 32 or (value >= 9 and value <= 13)


def __gvm_int_str(value: str) -> int:
    length: int = len(value)
    i: int = 0
    while i < length and __gvm_int_str_is_space(ord(value[i])):
        i = i + 1

    negative: bool = False
    if i < length and (value[i] == '+' or value[i] == '-'):
        negative = value[i] == '-'
        i = i + 1

    digit_count: int = 0
    result: int = 0
    while i < length:
        character: int = ord(value[i])
        if character < 48 or character > 57:
            break
        result = result * 10 + character - 48
        digit_count = digit_count + 1
        i = i + 1

    if digit_count == 0:
        return 0
    if negative:
        result = -result
    return result


def __gvm_float_digits(value: float) -> str:
    digits: str = __gvm_str_alloc(8)
    i: int = 0
    while i < 8:
        digit: int = 0
        while value >= 1.0:
            value = value - 1.0
            digit = digit + 1
        __gvm_str_set(digits, i, chr(48 + digit))
        value = value * 10.0
        i = i + 1

    rounding_digit: int = 0
    while value >= 1.0:
        value = value - 1.0
        rounding_digit = rounding_digit + 1
    if rounding_digit >= 5:
        position: int = 7
        carrying: bool = True
        while position >= 0 and carrying:
            current: int = ord(digits[position]) - 48
            if current == 9:
                __gvm_str_set(digits, position, '0')
                position = position - 1
            else:
                __gvm_str_set(digits, position, chr(49 + current))
                carrying = False
        if carrying:
            __gvm_str_set(digits, 0, '1')
            return __gvm_str_concat("+", digits)
    return digits

def __gvm_str_float(value: float) -> str:
    if value != value:
        return "nan"
    if value > 1.7976931348623157e308:
        return "inf"
    if value < -1.7976931348623157e308:
        return "-inf"
    if value == 0.0:
        return "0.0"

    negative: bool = value < 0.0
    if negative:
        value = -value

    exponent: int = 0
    while value >= 10.0:
        value = value * 0.1
        exponent = exponent + 1
    while value < 1.0:
        value = value * 10.0
        exponent = exponent - 1

    raw_digits: str = __gvm_float_digits(value)
    if raw_digits[0] == '+':
        exponent = exponent + 1
        raw_digits = __gvm_str_slice(raw_digits, 1, len(raw_digits))

    end: int = len(raw_digits)
    while end > 1 and raw_digits[end - 1] == '0':
        end = end - 1
    digits: str = __gvm_str_slice(raw_digits, 0, end)

    result: str = ""
    if exponent >= -4 and exponent <= 15:
        integer_digits: int = exponent + 1
        if integer_digits <= 0:
            zeros: str = __gvm_str_repeat("0", -integer_digits)
            result = __gvm_str_concat(__gvm_str_concat("0.", zeros), digits)
        elif integer_digits >= len(digits):
            zeros: str = __gvm_str_repeat("0", integer_digits - len(digits))
            result = __gvm_str_concat(__gvm_str_concat(digits, zeros), ".0")
        else:
            whole: str = __gvm_str_slice(digits, 0, integer_digits)
            fraction: str = __gvm_str_slice(digits, integer_digits, len(digits))
            result = __gvm_str_concat(__gvm_str_concat(whole, "."), fraction)
    else:
        first: str = str(digits[0])
        if len(digits) == 1:
            result = __gvm_str_concat(first, ".0")
        else:
            rest: str = __gvm_str_slice(digits, 1, len(digits))
            result = __gvm_str_concat(__gvm_str_concat(first, "."), rest)
        if exponent < 0:
            result = __gvm_str_concat(__gvm_str_concat(result, "e-"), str(-exponent))
        else:
            result = __gvm_str_concat(__gvm_str_concat(result, "e+"), str(exponent))

    if negative:
        result = __gvm_str_concat("-", result)
    return result

def __gvm_str_bool(value: bool) -> str:
    if value:
        return "True"
    return "False"

def __gvm_int_div10(value: int) -> int:
    result: int = 0
    while value >= 10:
        value = value - 10
        result = result + 1
    return result

def __gvm_str_int(value: int) -> str:
    if value == 0:
        return "0"
    negative: bool = value < 0
    if negative:
        value = -value
    divisor: int = 1
    while divisor * 10 <= value:
        divisor = divisor * 10
    result: str = ""
    while divisor > 0:
        digit: int = 0
        while value >= divisor:
            value = value - divisor
            digit = digit + 1
        result = __gvm_str_concat(result, str(chr(48 + digit)))
        divisor = __gvm_int_div10(divisor)
    if negative:
        result = __gvm_str_concat("-", result)
    return result

def __gvm_str_slice(text: str, start: int, end: int) -> str:
    length: int = len(text)
    if start < 0:
        start = start + length
    if end < 0:
        end = end + length
    if start < 0:
        start = 0
    if start > length:
        start = length
    if end < start:
        end = start
    if end > length:
        end = length
    result: str = __gvm_str_alloc(end - start)
    i: int = 0
    while start + i < end:
        __gvm_str_set(result, i, text[start + i])
        i = i + 1
    return result

def __gvm_str_concat(left: str, right: str) -> str:
    result: str = __gvm_str_alloc(len(left) + len(right))
    i: int = 0
    while i < len(left):
        __gvm_str_set(result, i, left[i])
        i = i + 1
    j: int = 0
    while j < len(right):
        __gvm_str_set(result, i + j, right[j])
        j = j + 1
    return result

def __gvm_str_repeat(text: str, count: int) -> str:
    if count < 0:
        count = 0
    result: str = __gvm_str_alloc(len(text) * count)
    i: int = 0
    while i < count:
        j: int = 0
        while j < len(text):
            __gvm_str_set(result, i * len(text) + j, text[j])
            j = j + 1
        i = i + 1
    return result

def __gvm_str_compare(left: str, right: str) -> int:
    limit: int = len(left)
    if len(right) < limit:
        limit = len(right)
    i: int = 0
    while i < limit:
        if left[i] < right[i]:
            return -1
        if left[i] > right[i]:
            return 1
        i = i + 1
    if len(left) < len(right):
        return -1
    if len(left) > len(right):
        return 1
    return 0

def __gvm_str_find(text: str, sub: str) -> int:
    if len(sub) == 0:
        return 0
    i: int = 0
    while i + len(sub) <= len(text):
        j: int = 0
        while j < len(sub) and text[i + j] == sub[j]:
            j = j + 1
        if j == len(sub):
            return i
        i = i + 1
    return -1

def __gvm_str_rfind(text: str, sub: str) -> int:
    if len(sub) == 0:
        return len(text)
    i: int = len(text) - len(sub)
    while i >= 0:
        j: int = 0
        while j < len(sub) and text[i + j] == sub[j]:
            j = j + 1
        if j == len(sub):
            return i
        i = i - 1
    return -1

def __gvm_str_count(text: str, sub: str) -> int:
    if len(sub) == 0:
        return len(text) + 1
    total: int = 0
    position: int = 0
    while position + len(sub) <= len(text):
        tail: str = __gvm_str_slice(text, position, len(text))
        found: int = __gvm_str_find(tail, sub)
        if found < 0:
            return total
        total = total + 1
        position = position + found + len(sub)
    return total

def __gvm_str_startswith(text: str, prefix: str) -> bool:
    if len(prefix) > len(text):
        return False
    i: int = 0
    while i < len(prefix):
        if text[i] != prefix[i]:
            return False
        i = i + 1
    return True

def __gvm_str_endswith(text: str, suffix: str) -> bool:
    if len(suffix) > len(text):
        return False
    i: int = 0
    start: int = len(text) - len(suffix)
    while i < len(suffix):
        if text[start + i] != suffix[i]:
            return False
        i = i + 1
    return True

def __gvm_str_removeprefix(text: str, prefix: str) -> str:
    if __gvm_str_startswith(text, prefix):
        return __gvm_str_slice(text, len(prefix), len(text))
    return text

def __gvm_str_removesuffix(text: str, suffix: str) -> str:
    if __gvm_str_endswith(text, suffix):
        return __gvm_str_slice(text, 0, len(text) - len(suffix))
    return text

def __gvm_str_replace(text: str, old: str, new: str) -> str:
    matches: int = __gvm_str_count(text, old)
    result_length: int = len(text) + matches * (len(new) - len(old))
    result: str = __gvm_str_alloc(result_length)
    source: int = 0
    target: int = 0
    if len(old) == 0:
        i: int = 0
        while i <= len(text):
            j: int = 0
            while j < len(new):
                __gvm_str_set(result, target, new[j])
                target = target + 1
                j = j + 1
            if i < len(text):
                __gvm_str_set(result, target, text[i])
                target = target + 1
            i = i + 1
        return result
    while source < len(text):
        tail: str = __gvm_str_slice(text, source, len(text))
        if __gvm_str_startswith(tail, old):
            j: int = 0
            while j < len(new):
                __gvm_str_set(result, target, new[j])
                target = target + 1
                j = j + 1
            source = source + len(old)
        else:
            __gvm_str_set(result, target, text[source])
            source = source + 1
            target = target + 1
    return result

def __gvm_ascii_lower_char(value: char) -> char:
    if value >= 'A' and value <= 'Z':
        return chr(ord(value) + 32)
    return value

def __gvm_ascii_upper_char(value: char) -> char:
    if value >= 'a' and value <= 'z':
        return chr(ord(value) - 32)
    return value

def __gvm_str_lower(text: str) -> str:
    result: str = __gvm_str_alloc(len(text))
    i: int = 0
    while i < len(text):
        __gvm_str_set(result, i, __gvm_ascii_lower_char(text[i]))
        i = i + 1
    return result

def __gvm_str_upper(text: str) -> str:
    result: str = __gvm_str_alloc(len(text))
    i: int = 0
    while i < len(text):
        __gvm_str_set(result, i, __gvm_ascii_upper_char(text[i]))
        i = i + 1
    return result

def __gvm_str_swapcase(text: str) -> str:
    result: str = __gvm_str_alloc(len(text))
    i: int = 0
    while i < len(text):
        value: char = text[i]
        if value >= 'a' and value <= 'z':
            value = __gvm_ascii_upper_char(value)
        else:
            value = __gvm_ascii_lower_char(value)
        __gvm_str_set(result, i, value)
        i = i + 1
    return result

def __gvm_str_capitalize(text: str) -> str:
    result: str = __gvm_str_lower(text)
    if len(result) > 0:
        __gvm_str_set(result, 0, __gvm_ascii_upper_char(result[0]))
    return result

def __gvm_is_alpha_char(value: char) -> bool:
    return (value >= 'A' and value <= 'Z') or (value >= 'a' and value <= 'z')

def __gvm_is_digit_char(value: char) -> bool:
    return value >= '0' and value <= '9'

def __gvm_is_space_char(value: char) -> bool:
    return value == ' ' or value == '\t' or value == '\n' or value == '\r' or value == '\v' or value == '\f'

def __gvm_str_title(text: str) -> str:
    result: str = __gvm_str_alloc(len(text))
    new_word: bool = True
    i: int = 0
    while i < len(text):
        value: char = text[i]
        if __gvm_is_alpha_char(value):
            if new_word:
                value = __gvm_ascii_upper_char(value)
            else:
                value = __gvm_ascii_lower_char(value)
            new_word = False
        else:
            new_word = True
        __gvm_str_set(result, i, value)
        i = i + 1
    return result

def __gvm_str_lstrip(text: str) -> str:
    start: int = 0
    while start < len(text) and __gvm_is_space_char(text[start]):
        start = start + 1
    return __gvm_str_slice(text, start, len(text))

def __gvm_str_rstrip(text: str) -> str:
    end: int = len(text)
    while end > 0 and __gvm_is_space_char(text[end - 1]):
        end = end - 1
    return __gvm_str_slice(text, 0, end)

def __gvm_str_strip(text: str) -> str:
    return __gvm_str_lstrip(__gvm_str_rstrip(text))

def __gvm_str_isascii(text: str) -> bool:
    i: int = 0
    while i < len(text):
        if ord(text[i]) > 127:
            return False
        i = i + 1
    return True

def __gvm_str_isalpha(text: str) -> bool:
    if len(text) == 0:
        return False
    i: int = 0
    while i < len(text):
        if not __gvm_is_alpha_char(text[i]):
            return False
        i = i + 1
    return True

def __gvm_str_isalnum(text: str) -> bool:
    if len(text) == 0:
        return False
    i: int = 0
    while i < len(text):
        if not __gvm_is_alpha_char(text[i]) and not __gvm_is_digit_char(text[i]):
            return False
        i = i + 1
    return True

def __gvm_str_isdecimal(text: str) -> bool:
    if len(text) == 0:
        return False
    i: int = 0
    while i < len(text):
        if not __gvm_is_digit_char(text[i]):
            return False
        i = i + 1
    return True

def __gvm_str_isspace(text: str) -> bool:
    if len(text) == 0:
        return False
    i: int = 0
    while i < len(text):
        if not __gvm_is_space_char(text[i]):
            return False
        i = i + 1
    return True

def __gvm_str_isprintable(text: str) -> bool:
    i: int = 0
    while i < len(text):
        value: int = ord(text[i])
        if value < 32 or value > 126:
            return False
        i = i + 1
    return True

def __gvm_str_islower(text: str) -> bool:
    has_cased: bool = False
    i: int = 0
    while i < len(text):
        value: char = text[i]
        if value >= 'A' and value <= 'Z':
            return False
        if value >= 'a' and value <= 'z':
            has_cased = True
        i = i + 1
    return has_cased

def __gvm_str_isupper(text: str) -> bool:
    return __gvm_str_islower(__gvm_str_swapcase(text))

def __gvm_str_istitle(text: str) -> bool:
    return text == __gvm_str_title(text) and __gvm_str_isalpha(__gvm_str_replace(text, " ", ""))

def __gvm_str_isidentifier(text: str) -> bool:
    if len(text) == 0:
        return False
    first: char = text[0]
    if not __gvm_is_alpha_char(first) and first != '_':
        return False
    i: int = 1
    while i < len(text):
        value: char = text[i]
        if not __gvm_is_alpha_char(value) and not __gvm_is_digit_char(value) and value != '_':
            return False
        i = i + 1
    return True

def __gvm_str_join(separator: str, values: list[str]) -> str:
    if len(values) == 0:
        return ""
    result: str = values[0]
    i: int = 1
    while i < len(values):
        result = __gvm_str_concat(__gvm_str_concat(result, separator), values[i])
        i = i + 1
    return result

def __gvm_str_expandtabs(text: str) -> str:
    result: str = ""
    column: int = 0
    i: int = 0
    while i < len(text):
        if text[i] == '\t':
            spaces: int = 8 - (column & 7)
            while spaces > 0:
                result = __gvm_str_concat(result, " ")
                column = column + 1
                spaces = spaces - 1
        else:
            result = __gvm_str_concat(result, str(text[i]))
            if text[i] == '\n' or text[i] == '\r':
                column = 0
            else:
                column = column + 1
        i = i + 1
    return result

def __gvm_str_zfill(text: str, width: int) -> str:
    if width <= len(text):
        return text
    zeros: str = __gvm_str_repeat("0", width - len(text))
    if len(text) > 0 and (text[0] == '+' or text[0] == '-'):
        return __gvm_str_concat(__gvm_str_concat(str(text[0]), zeros), __gvm_str_slice(text, 1, len(text)))
    return __gvm_str_concat(zeros, text)
'''


def runtime_definitions():
    """Return fresh HR definitions for the internal runtime."""
    return hr.ast_to_hr(ast.parse(SOURCE, filename="<string-runtime>"), source=SOURCE, filename="<string-runtime>").body


def runtime_name(method: str) -> str:
    return PREFIX + METHODS[method][0]


def required_functions(module: hr.Module) -> frozenset[str]:
    """Return the transitive closure of runtime functions used by *module*."""
    definitions = {
        node.name: node
        for node in module.body
        if isinstance(node, hr.FunctionDef) and node.name.startswith("__gvm_")
    }

    class Dependencies(hr.Walker):
        def __init__(self, *, skip_runtime_definitions=False):
            self.names = set()
            self.skip_runtime_definitions = skip_runtime_definitions

        def visit_FunctionDef(self, node):
            if not (self.skip_runtime_definitions and node.name.startswith("__gvm_")):
                self.traverse(node.body)

        def visit_Call(self, node):
            runtime = getattr(node, "resolved_runtime", None)
            if runtime is not None:
                self.names.add(runtime)
            if node.func in definitions:
                self.names.add(node.func)
            self.generic_walk(node)

        def visit_MethodCall(self, node):
            runtime = getattr(node, "resolved_method", None)
            if isinstance(runtime, str) and runtime.startswith("__gvm_"):
                self.names.add(runtime)
            self.generic_walk(node)

        def visit_Subscript(self, node):
            runtime = getattr(node, "resolved_runtime", None)
            if runtime is not None:
                self.names.add(runtime)
            self.generic_walk(node)

        def visit_BinOp(self, node):
            operator = type(node.operator)
            if operator in {ast.In, ast.NotIn} and getattr(node, "right_type", None) == STR:
                self.names.add("__gvm_str_find")
            elif (
                operator is ast.Add
                and getattr(node, "left_type", None) in {STR, CHAR}
                and getattr(node, "right_type", None) in {STR, CHAR}
            ):
                self.names.add("__gvm_str_concat")
            elif getattr(node, "left_type", None) == STR and getattr(node, "right_type", None) == STR:
                if operator is ast.Add:
                    self.names.add("__gvm_str_concat")
                elif operator in {ast.Eq, ast.NotEq, ast.Lt, ast.Gt, ast.LtE, ast.GtE}:
                    self.names.add("__gvm_str_compare")
            elif getattr(node, "type", None) == STR and operator is ast.Mult:
                self.names.add("__gvm_str_repeat")
            self.generic_walk(node)

    roots = Dependencies(skip_runtime_definitions=True)
    roots.walk(module)
    required = set(roots.names)
    pending = list(required)
    while pending:
        name = pending.pop()
        definition = definitions.get(name)
        if definition is None:
            continue
        dependencies = Dependencies()
        dependencies.walk(definition)
        for dependency in dependencies.names - required:
            required.add(dependency)
            pending.append(dependency)
    return frozenset(required)
