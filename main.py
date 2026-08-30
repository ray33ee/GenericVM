"""Runnable GenericVM example using a declared target instruction set."""

import interpreter
from compiler import compile_source
from bytecode import bytecode

SOURCE = """


main()

def copy_string(s, d):
    d[0] = len(s)
    
    for i in range(len(s)):
        d[i+1] = ord(s[i])

def main():
    
    print("Enter username: ")
    username = input(100)
    
    print("Enter password: ")
    password = input(100)
    
    username_buff = malloc(101)
    password_buff = malloc(101)
    
    copy_string(username, username_buff)
    copy_string(password, password_buff)
    
    user = cast_str(username_buff + 1)
    passwd = cast_str(password_buff + 1)
    
    char_sum = 0
    
    lower_case_u = 0
    lower_case_p = 0
    
    upper_case = 0
    digit_sum = 0
    special_21_sum = 0
    special_3a_sum = 0
    special_5b_sum = 0
    lengths = 0
    
    for i in range(100):
    
        u = ord(user[i])
        p = ord(passwd[i])
    
        # Sum of chars (mod 256) in username and password must be equal
        char_sum += u - p
        
        # Number of lower case chars in username and password must be equal but not 0
        lower_case_u += u >= 0x61 and u <= 0x7A
        
        lower_case_p += p >= 0x61 and p <= 0x7A
        
        # Password must have exactly 4 more uppercase chars than username
        upper_case -= u >= 0x41 and u <= 0x5A
        
        upper_case += p >= 0x41 and p <= 0x5A
        
        # Sum of all digits in username and password must be 8
        digit_sum += (u >= 0x30 and u <= 0x39) * (u - 0x30)
        
        digit_sum += (p >= 0x30 and p <= 0x39) * (p - 0x30)
        
        # Number of special chars from 0x21 to 0x2f in password must be one more then the number of vowels in username
        special_21_sum += p >= 0x21 and p <= 0x2f
        
        special_21_sum -= u == 0x41 or u == 0x45 or u == 0x49 or u == 0x4F or u == 0x55 or u == 0x61 or u == 0x65 or u == 0x69 or u == 0x6F or u == 0x75
        
        # Password cannot have any specials from 0x3a to 0x40
        special_3a_sum += p >= 0x3a and p <= 0x40
             
        # Password cannot have any specials from 0x3a to 0x40
        special_5b_sum += p >= 0x5B and p <= 0x60
        
        # password length must be exactly twice the length of the username length
        lengths += 2 * (u != 0)
        
        lengths -= p != 0
            
    well_done = "well done lmao\\n"
    nope = "nope\\n"
    
    if char_sum & 0xFF == 0 and lower_case_u == lower_case_p and lower_case_p != 0 and upper_case == 4 and digit_sum == 8 and special_21_sum == 1 and special_3a_sum == 0 and lengths == 0 and special_5b_sum == 2:
        print(well_done)
    else:
        print(nope)
    
    
"""


def main():
    # The supplied interpreter declares the exact IR operations it supports.
    target = interpreter.Interpreter.INSTRUCTION_SET

    # Compiling from source retains filenames, source lines, and columns for
    # readable errors if this program needs an instruction absent from target.
    result = compile_source(
        SOURCE,
        filename="example.gvm",
        instruction_set=target,
    )

    print("Instructions:")
    for index, instruction in enumerate(result):
        print(f"{index:03}: {instruction}")

    print()
    print("START PROGRAM")
    return_value = interpreter.Interpreter().run(result)
    print("END PROGRAM")
    print()
    print(f"Interpreter result: {return_value}")

    print(bytecode(result, instruction_set=target))

if __name__ == "__main__":
    main()
