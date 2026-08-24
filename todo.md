# Todo

- If a statement is an expression this is bad - this  might leave values on the stack that can interfere with other operations.
  - To fix this, there are two solutions:
    1. Allow these types of statements but use a 'drop' instruction to clean the stack
    2. Do NOT allow these types of statements and have the compiler throw an error
  - An exception to this case is the main function call, which can have a return value that is not used - This allows interpreters to obtain a return code for programs
- Implement type-specific functions:
  - Conversion from primitives to string
  - floating point operations
  - String operations