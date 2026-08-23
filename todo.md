# Todo

- Overhaul the type system to allow annotating lists (and their elements) and tuples
- Allow tuples? Dont allow nested tuples? or allow them but flatten them? Maybe allow variables to be more than just 1 u64 and address as .0, etc?
  - Thing get complex - lets say you have range(x) if x is a tuple or a thruple this needs to be factored in. The number of args an expression contains can only be known via type deduction
- If a statement is an expression this is bad - this  might leave values on the stack that can interfere with other operations.
  - To fix this, there are two solutions:
    1. Allow these types of statements but use a 'drop' instruction to clean the stack
    2. Do NOT allow these types of statements and have the compiler throw an error
  - An exception to this case is the main function call, which can have a return value that is not used - This allows interpreters to obtain a return code for programs
- Add a bit more functionality:
  - Malloc and free can also be used to implement custom types via `class`. These types are always instantiated on the heap and must be manually freed
    - `__init__` is implemented as first calling malloc, then treating the memory as a struct that the member variables are initialised into



# Tuples

- Variables can be tuples: By giving each variable the needed space on the stack and addressing tuples like .0, .1, etc.
- Explicit type annotation: Variables are annotated
- Type deduction: REturn types and variable types must be factored into type deduction
- Nested tuples: a tuple like `(int, str, (int, int))` only has 3 members despite being 4 u64s
- Use pythons '*' to flatten (i.e. unpack) tuples?