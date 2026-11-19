def greet(name: str) -> str:
    """A greeting for `name`, keeping its case as typed."""
    return f"Hello, {name}!"


def greet_many(names: list[str]) -> list[str]:
    """Greetings for `names`, each greeting once, in order."""
    result: list[str] = []
    for name in names:
        greeting = greet(name)
        if greeting not in result:
            result.append(greeting)
    return result
