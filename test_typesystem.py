import ast
import unittest

import hr
from symbols import Symbols
from typecheck import TypeCheckError, check_types
from typesystem import BOOL, FLOAT, INT, LIST, NONE, STR, PrimitiveType


class PrimitiveTypeTests(unittest.TestCase):
    def test_primitive_types_are_structural_and_canonical(self):
        self.assertEqual(INT, PrimitiveType("int"))
        self.assertIs(hr.parse_primitive_annotation(ast.Name(id="int")), INT)
        self.assertEqual(str(BOOL), "bool")
        self.assertEqual(str(STR), "str")
        self.assertEqual(str(NONE), "NoneType")
        self.assertEqual(str(LIST), "list")

    def test_annotations_and_symbols_store_type_objects(self):
        module = hr.ast_to_hr(ast.parse("""
def identity(value: int) -> int:
    result: int = value
    return result
"""))
        symbols = Symbols(module)
        function = module.body[0]

        self.assertIs(function.args[0].annotation, INT)
        self.assertIs(function.return_type, INT)
        self.assertIs(symbols.functions["identity"][0]["value"].type, INT)
        self.assertIs(symbols.functions["identity"][0]["result"].declared_type, INT)

    def test_every_expression_has_an_unresolved_type_field(self):
        module = hr.ast_to_hr(ast.parse("""
def choose(value: int) -> int:
    return value if value == 1 else -1
"""))
        expressions = []

        class CollectExpressions(hr.Walker):
            def generic_walk(self, node):
                if isinstance(node, hr.Expression):
                    expressions.append(node)
                super().generic_walk(node)

        CollectExpressions().walk(module)

        self.assertTrue(expressions)
        self.assertTrue(all(hasattr(expression, "type") for expression in expressions))
        self.assertTrue(all(expression.type is None for expression in expressions))

    def test_missing_argument_annotation_is_preserved_for_inference(self):
        module = hr.ast_to_hr(ast.parse("""
def invalid(value) -> int:
    return 1
"""))
        self.assertIsNone(module.body[0].args[0].annotation)

    def test_unknown_annotation_is_rejected(self):
        module = hr.ast_to_hr(ast.parse("""
def invalid(value: number) -> int:
    value
    return 1
"""))
        symbols = Symbols(module)
        with self.assertRaisesRegex(TypeCheckError, "Unknown class type 'number'"):
            check_types(module, symbols, {})

    def test_float_annotation_is_a_type_object(self):
        assignment = ast.parse("value: float = 1.0").body[0]
        self.assertIs(hr.parse_primitive_annotation(assignment.annotation), FLOAT)


if __name__ == "__main__":
    unittest.main()
