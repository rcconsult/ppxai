def fibonacci(n):
    """Generate the Fibonacci sequence up to n terms."""
    a, b = 0, 1
    sequence = []
    for _ in range(n):
        sequence.append(a)
        a, b = b, a + b
    return sequence

if __name__ == "__main__":
    num_terms = 15
    fib_sequence = fibonacci(num_terms)
    print(f"The Fibonacci sequence up to {num_terms} terms is:")
    print(fib_sequence)
