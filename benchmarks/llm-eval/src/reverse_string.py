def reverse_string(s):
    """Reverse a string using a for loop."""
    result = ""
    for char in s:
        result = char + result
    return result
