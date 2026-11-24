"""Greetings for people, by name."""


def greet(name: str) -> str:
    """Return a greeting for `name`, keeping its case as typed."""
    return f"Hello, {name}!"


def greet_list(str_list: list[str]) -> list[str]:
    return [greet(item) for item in str_list]
