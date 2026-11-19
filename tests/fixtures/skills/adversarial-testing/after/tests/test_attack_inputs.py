from greet import greet


def test_a_blank_name_is_not_greeted_as_blank() -> None:
    assert greet("   ") == "Hello, world!"


def test_a_name_with_a_newline_stays_on_one_line() -> None:
    assert "\n" not in greet("Ada\nBob")


def test_a_long_name_is_greeted_in_full() -> None:
    name = "a" * 10_000
    assert greet(name) == f"Hello, {name}!"
