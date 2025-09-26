import ast
from hr import ast_to_hr, dump

at = ast.parse("""

def thing() -> NoneType:
    def stuff() -> NoneType:
        pass

""")

print(ast.dump(at))

print(dump(ast_to_hr(at)))


