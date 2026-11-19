def greet(name: str) -> str:
    """A greeting for `name`, keeping its case as typed; the world when it is empty."""
    if not name:
        return "Hello, world!"
    return f"Hello, {name}!"
