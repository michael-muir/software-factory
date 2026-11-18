"""A tiny module for proving the Python gate profile."""


def add(a: int, b: int) -> int:
    return a + b


def is_positive(x: int) -> bool:
    return x > 0


def clamp(value: int, low: int, high: int) -> int:
    if value < low:
        return low
    if value > high:
        return high
    return value
