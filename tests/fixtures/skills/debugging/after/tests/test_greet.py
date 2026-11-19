from greet import greet


def test_greets_by_name() -> None:
    assert greet("Ada") == "Hello, Ada!"


def test_keeps_the_names_case() -> None:
    assert greet("McDonald") == "Hello, McDonald!"


def test_greets_the_world_when_the_name_is_empty() -> None:
    assert greet("") == "Hello, world!"


def test_does_not_recapitalise_particles() -> None:
    """Regression: title() turned 'van der Berg' into 'Van Der Berg'."""
    assert greet("van der Berg") == "Hello, van der Berg!"
