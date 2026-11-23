+++
name = "python"
title = "Python standards pack"
prefix = "PY"
applies_to = ["*.py", "*.pyi"]

[[sources]]
title = "PEP 8: Style Guide for Python Code"
url = "https://peps.python.org/pep-0008/"
licence = "Public domain"

[[sources]]
title = "PEP 257: Docstring Conventions"
url = "https://peps.python.org/pep-0257/"
licence = "Public domain"

[[sources]]
title = "PEP 484: Type Hints"
url = "https://peps.python.org/pep-0484/"
licence = "Public domain"
+++

# Python standards pack

Rules a reviewer judges in Python code. Each rule is in our own words and links the section of the source it comes from. Cite a rule by its id in a finding. Severity follows ADR 0037: `blocker` for unsafe or incorrect code, `major` for code that misleads or is hard to change, `minor` for readability.

## Left to the tools

The gate's format check (`ruff format`) owns layout, line length and whitespace. Its lint check (`ruff check`, with the rules the project selects) owns import order, unused names, bare `except:` and the other mechanical checks, and its types check (`mypy`) owns type consistency. This pack doesn't repeat them: it covers what those tools can't judge.

## Rules

| Rule id | Severity | Rule                                                                                                                                                       | Why/example                                                                                      | Source                                                                                                    |
| ------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| PY-001  | blocker  | Don't catch `Exception` just to carry on. Catch the specific exceptions you can handle, and let the rest propagate.                                        | `except Exception: pass` hides a bug as easily as a network blip.                                | [PEP 8: Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)       |
| PY-002  | blocker  | Keep a `try` block to the statements that can raise what its handler catches.                                                                              | A wide `try` around a `KeyError` handler also hides a `KeyError` from a bug three calls down.    | [PEP 8: Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)       |
| PY-003  | blocker  | Release files, locks and connections with `with`, never by hoping a later line runs.                                                                       | `f = open(p)` leaks the handle when an exception skips `f.close()`.                              | [PEP 8: Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)       |
| PY-004  | blocker  | Don't `return`, `break` or `continue` inside `finally`.                                                                                                    | It cancels an exception that was on its way out, without a trace.                                | [PEP 8: Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)       |
| PY-005  | major    | When you raise a new exception while handling one, chain it: `raise ConfigError(...) from err`, or `from None` when the cause is noise.                    | The traceback keeps the real cause, so the reader can see why it failed.                         | [PEP 8: Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)       |
| PY-006  | major    | Derive your exceptions from `Exception`, and name them for the problem (`ConfigError`), not for where they're raised.                                      | Callers catch by meaning, and `except Exception` still works.                                    | [PEP 8: Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)       |
| PY-007  | major    | A function returns a value on every path or on none. When some paths return something, write `return None` on the others.                                  | A missing return in one branch reads as a bug, and often is one.                                 | [PEP 8: Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)       |
| PY-008  | major    | Mark what isn't part of a module's interface with a leading underscore, and keep `__all__` in step when the module has one.                                | Callers can't come to depend on what's clearly internal, so it stays free to change.             | [PEP 8: Public and Internal Interfaces](https://peps.python.org/pep-0008/#public-and-internal-interfaces) |
| PY-009  | major    | Names say what a thing is or does, not its type or how it's stored.                                                                                        | `names`, not `str_list`: the type can change, the meaning is what the reader needs.              | [PEP 8: Naming Conventions](https://peps.python.org/pep-0008/#naming-conventions)                         |
| PY-010  | major    | Annotate every public function's parameters and return type.                                                                                               | The types check can only check what's annotated.                                                 | [PEP 484](https://peps.python.org/pep-0484/)                                                              |
| PY-011  | major    | Prefer a precise type to `Any`. When `Any` is really needed, say why in a comment.                                                                         | `Any` switches the type checker off for every value it touches.                                  | [PEP 484](https://peps.python.org/pep-0484/)                                                              |
| PY-012  | major    | Write `X \| None` wherever `None` is a valid value, and handle the `None` case where it's used.                                                            | Callers learn from the signature that they must check, and the type checker holds them to it.    | [PEP 484](https://peps.python.org/pep-0484/)                                                              |
| PY-013  | major    | A `# type: ignore` names the error code it silences and says why.                                                                                          | `# type: ignore[arg-type]  # stub is wrong, see issue 12` can be revisited; a bare ignore can't. | [PEP 484](https://peps.python.org/pep-0484/)                                                              |
| PY-014  | major    | Comments agree with the code. A change that makes a comment wrong updates it or deletes it.                                                                | A comment that contradicts the code is worse than none.                                          | [PEP 8: Comments](https://peps.python.org/pep-0008/#comments)                                             |
| PY-015  | minor    | Public modules, classes and functions have a docstring.                                                                                                    | `help()` and editors show it to every caller.                                                    | [PEP 257: What is a Docstring?](https://peps.python.org/pep-0257/#what-is-a-docstring)                    |
| PY-016  | minor    | A one-line docstring is a command ending in a period ("Return the config path."), not a restatement of the signature.                                      | `"""load(path) -> Config"""` tells the reader nothing new.                                       | [PEP 257: One-line Docstrings](https://peps.python.org/pep-0257/#one-line-docstrings)                     |
| PY-017  | minor    | A longer docstring is a summary line, a blank line, then the arguments, return value, exceptions and side effects that the signature doesn't make obvious. | The summary still works in a one-line listing.                                                   | [PEP 257: Multi-line Docstrings](https://peps.python.org/pep-0257/#multi-line-docstrings)                 |
| PY-018  | minor    | Use `str.startswith()` and `str.endswith()` rather than comparing slices.                                                                                  | `name[:5] == "test_"` breaks quietly when the prefix changes length.                             | [PEP 8: Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)       |
