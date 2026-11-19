from greet import greet


def test_greets_by_name() -> None:
    assert greet("Ada") == "Hello, Ada!"


def test_keeps_the_names_case() -> None:
    assert greet("McDonald") == "Hello, McDonald!"


def test_greets_the_world_when_the_name_is_empty() -> None:
    assert greet("") == "Hello, world!"
