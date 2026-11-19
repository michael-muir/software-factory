from greet import greet


def test_greets_by_name() -> None:
    assert greet("Ada") == "Hello, Ada!"


def test_keeps_the_names_case() -> None:
    assert greet("McDonald") == "Hello, McDonald!"
