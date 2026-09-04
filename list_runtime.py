"""Source-level dynamic-list helpers compiled with the user's program.

List values point to a stable three-word heap descriptor containing
``[data_pointer, length, capacity]``. Helpers are specialized by the flattened
element width, currently one or two words, and use only existing VM operations.
"""

import ast

import hr


SOURCE = r'''
def __gvm_list_resize_1(descriptor: ptr, new_capacity: int):
    old_data: ptr = cast_ptr(descriptor[0])
    new_data: ptr = malloc(new_capacity)
    i: int = 0
    while i < descriptor[1]:
        new_data[i] = old_data[i]
        i = i + 1
    free(old_data)
    descriptor[0] = cast_int(new_data)
    descriptor[2] = new_capacity

def __gvm_list_resize_2(descriptor: ptr, new_capacity: int):
    old_data: ptr = cast_ptr(descriptor[0])
    new_data: ptr = malloc(new_capacity * 2)
    i: int = 0
    while i < descriptor[1] * 2:
        new_data[i] = old_data[i]
        i = i + 1
    free(old_data)
    descriptor[0] = cast_int(new_data)
    descriptor[2] = new_capacity

def __gvm_list_grow_1(descriptor: ptr):
    if descriptor[1] >= descriptor[2]:
        capacity: int = descriptor[2] * 2
        if capacity < 10:
            capacity = 10
        __gvm_list_resize_1(descriptor, capacity)

def __gvm_list_grow_2(descriptor: ptr):
    if descriptor[1] >= descriptor[2]:
        capacity: int = descriptor[2] * 2
        if capacity < 10:
            capacity = 10
        __gvm_list_resize_2(descriptor, capacity)

def __gvm_list_append_1(descriptor: ptr, word0: int):
    __gvm_list_grow_1(descriptor)
    data: ptr = cast_ptr(descriptor[0])
    data[descriptor[1]] = word0
    descriptor[1] = descriptor[1] + 1

def __gvm_list_append_2(descriptor: ptr, word0: int, word1: int):
    __gvm_list_grow_2(descriptor)
    data: ptr = cast_ptr(descriptor[0])
    offset: int = descriptor[1] * 2
    data[offset] = word0
    data[offset + 1] = word1
    descriptor[1] = descriptor[1] + 1

def __gvm_list_insert_1(descriptor: ptr, index: int, word0: int):
    length: int = descriptor[1]
    if index < 0:
        index = index + length
    if index < 0:
        index = 0
    if index > length:
        index = length
    __gvm_list_grow_1(descriptor)
    data: ptr = cast_ptr(descriptor[0])
    i: int = length
    while i > index:
        data[i] = data[i - 1]
        i = i - 1
    data[index] = word0
    descriptor[1] = length + 1

def __gvm_list_insert_2(descriptor: ptr, index: int, word0: int, word1: int):
    length: int = descriptor[1]
    if index < 0:
        index = index + length
    if index < 0:
        index = 0
    if index > length:
        index = length
    __gvm_list_grow_2(descriptor)
    data: ptr = cast_ptr(descriptor[0])
    i: int = length
    while i > index:
        data[i * 2] = data[(i - 1) * 2]
        data[i * 2 + 1] = data[(i - 1) * 2 + 1]
        i = i - 1
    data[index * 2] = word0
    data[index * 2 + 1] = word1
    descriptor[1] = length + 1

def __gvm_list_pop_1(descriptor: ptr, index: int) -> int:
    length: int = descriptor[1]
    if index < 0:
        index = index + length
    assert index >= 0 and index < length
    data: ptr = cast_ptr(descriptor[0])
    result: int = data[index]
    i: int = index
    while i + 1 < length:
        data[i] = data[i + 1]
        i = i + 1
    descriptor[1] = length - 1
    return result

def __gvm_list_pop_2(descriptor: ptr, index: int) -> tuple[int, int]:
    length: int = descriptor[1]
    if index < 0:
        index = index + length
    assert index >= 0 and index < length
    data: ptr = cast_ptr(descriptor[0])
    result0: int = data[index * 2]
    result1: int = data[index * 2 + 1]
    i: int = index
    while i + 1 < length:
        data[i * 2] = data[(i + 1) * 2]
        data[i * 2 + 1] = data[(i + 1) * 2 + 1]
        i = i + 1
    descriptor[1] = length - 1
    return (result0, result1)

def __gvm_list_clear(descriptor: ptr):
    descriptor[1] = 0

def __gvm_list_initial_capacity(length: int) -> int:
    capacity: int = 10
    while capacity < length:
        capacity = capacity * 2
    return capacity

def __gvm_list_slice_1(source: ptr, start: int, end: int) -> ptr:
    length: int = source[1]
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
    result: ptr = malloc(3)
    result[1] = end - start
    result[2] = __gvm_list_initial_capacity(end - start)
    data: ptr = malloc(result[2])
    result[0] = cast_int(data)
    old_data: ptr = cast_ptr(source[0])
    i: int = 0
    while start + i < end:
        data[i] = old_data[start + i]
        i = i + 1
    return result

def __gvm_list_slice_2(source: ptr, start: int, end: int) -> ptr:
    length: int = source[1]
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
    result: ptr = malloc(3)
    result[1] = end - start
    result[2] = __gvm_list_initial_capacity(end - start)
    data: ptr = malloc(result[2] * 2)
    result[0] = cast_int(data)
    old_data: ptr = cast_ptr(source[0])
    i: int = 0
    while start + i < end:
        data[i * 2] = old_data[(start + i) * 2]
        data[i * 2 + 1] = old_data[(start + i) * 2 + 1]
        i = i + 1
    return result

'''


def runtime_definitions():
    return hr.ast_to_hr(
        ast.parse(SOURCE, filename="<list-runtime>"),
        source=SOURCE,
        filename="<list-runtime>",
    ).body


def required_functions(module: hr.Module) -> frozenset[str]:
    definitions = {
        node.name: node
        for node in module.body
        if isinstance(node, hr.FunctionDef) and node.name.startswith("__gvm_list_")
    }

    class Dependencies(hr.Walker):
        def __init__(self, *, skip_runtime_definitions=False):
            self.names = set()
            self.skip_runtime_definitions = skip_runtime_definitions

        def visit_FunctionDef(self, node):
            if not (self.skip_runtime_definitions and node.name.startswith("__gvm_list_")):
                self.traverse(node.body)

        def visit_MethodCall(self, node):
            runtime = getattr(node, "resolved_list_method", None)
            if runtime is not None:
                self.names.add(runtime)
            self.generic_walk(node)

        def visit_Subscript(self, node):
            runtime = getattr(node, "resolved_list_slice", None)
            if runtime is not None:
                self.names.add(runtime)
            self.generic_walk(node)

        def visit_Call(self, node):
            if node.func in definitions:
                self.names.add(node.func)
            self.generic_walk(node)

    roots = Dependencies(skip_runtime_definitions=True)
    roots.walk(module)
    required = set(roots.names)
    pending = list(required)
    while pending:
        definition = definitions.get(pending.pop())
        if definition is None:
            continue
        dependencies = Dependencies()
        dependencies.walk(definition)
        for dependency in dependencies.names - required:
            required.add(dependency)
            pending.append(dependency)
    return frozenset(required)
