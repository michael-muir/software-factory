def greet(name: str) -> str:
    """A greeting for `name`; the world when it is empty."""
    if not name:
        return "Hello, world!"
    return f"Hello, {name.title()}!"
