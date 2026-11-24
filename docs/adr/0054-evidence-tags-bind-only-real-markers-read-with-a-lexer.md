# 0054 · Evidence tags bind only real markers, found by a lexer rather than a text search

Status: Proposed · Date: 2026-11-24 · Epic: E31

## Context

ADR 0025 has `trace_file` bind every `<EPIC>-AC-nn` match in a locked test file to the next test definition. A match inside a string literal counts too. In E08-T5 this traced E08 AC-17 and AC-19 to `test_evidence_py_is_standard_library_only`, because a coverage test lists those ids in a string just before it. The product owner decided on 20 Nov 2026 that only real markers bind (E31 spec). The trace has to stay a static, standard-library read.

The options were:

- **Strip strings with a regex** before searching. That's fragile with nested quotes, f-strings and template literals.
- **Parse Python with `ast`.** It drops comments, so the comment rule would need a second pass anyway.
- **Use the `tokenize` module for Python and a small scanner for TS/JS.** Both give comments and strings as separate tokens with positions.

## Decision

- This ADR **supersedes ADR 0025's binding rule** only. The rest of ADR 0025 stands.
- **Python is read with `tokenize`.** A tag binds when it's in:
  - a `COMMENT` token: it binds to the next `def test_*`, as today;
  - the arguments of a `@pytest.mark.ac(...)` decorator (full tags, one or more): it binds to the test that decorator applies to;
  - a test's docstring (the first statement string after `def test_*:`): it binds to that test.
- **TS/JS is read by a scanner in `evidence.py`.** It knows `'…'`, `"…"`, `` `…` `` (with `${…}` nesting), `//` and `/* */`, and escapes. A tag binds when it's in a comment (to the next test) or in the first string argument of `test(`/`it(` (including `.only`, `.skip` and so on). Comment-like text inside a string is part of the string.
- **A tag anywhere else is ignored.** It doesn't bind to a test, and it isn't listed under the file alone.
- If Python fails to tokenize, the file falls back to listing its comment-free tags under the file alone, with no test, so a broken file never crashes the draft.
- Other stacks are unchanged: their tags are listed under the file alone.
- The kit registers the `ac` mark in its pytest config, so pytest doesn't warn.

## Consequences

- A coverage test can name AC ids in strings without inventing evidence.
- `trace_file` grows by a scanner of about a hundred lines. It stays standard library only, and its kit copy must match.
- E08-T2's locked tests pin the old rule, so they're relocked with the product owner's approval.
- Tags in plain strings that used to count, for example in a parametrize id, now need a mark or comment.
