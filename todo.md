# Todo

- add the if expression 
- If a statement is an expression this is bad - this  might leave values on the stack that can interfere with other operations.
  - To fix this, there are two solutions:
    1. Allow these types of statements but use a 'drop' instruction to clean the stack
    2. Do NOT allow these types of statements and have the compiler throw an error
  - An exception to this case is the main function call, which can have a return value that is not used - This allows interpreters to obtain a return code for programs
- Add a bit more functionality:
  - Add built in functionality for the heap, accessed with `heap[index]`
  - This allows the VM to supply special `malloc` and `free` instructions
  - If malloc and free are implemented, sizable primitives like list, map, strings, etc. can be supported
    - these types can be implemented by translating into a malloc followed by `heap[index] = x` instructions
  - Malloc and free can also be used to implement custom types via `class`. These types are always instantiated on the heap and must be manually freed
    - `__init__` is implemented as first calling malloc, then treating the memory as a struct that the member variables are initialised into