# E31 · Evidence tags bind only real markers — Spec

Issue: [#82](https://github.com/michael-muir/software-factory/issues/82) · Milestone: M1 · Manual factory (alpha) · Depends on: E08 (done)
Status: **Approved by michael-muir, 24 Nov 2026** · Next: Architect design note and ADRs, then failing tests per AC

## Goal

`evidence.py` traces each acceptance criterion to the test after **any** occurrence of its tag (`<EPIC>-AC-nn`) in a locked test file, including one inside a string literal (`trace_file`, ADR 0025). In E08-T5 this traced AC-17 and AC-19 to `test_evidence_py_is_standard_library_only`, because a coverage test lists those ids in a string just before it. Subagent B removed both lines from #80's body by hand. E31 makes the trace bind only real markers: a pytest `ac` mark, a tag in a comment, or a tag in a test's title. Tags anywhere else in a string literal are ignored.

**Done when:** a PR body drafted by `evidence.py` traces no AC through a tag that sits only in a string literal, and no hand edits to the trace are needed.

## Decisions in force (product owner, 20 Nov 2026)

| Topic        | Decision                                                                                                                                                     |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| The fix      | **Bind only real markers,** such as `@pytest.mark.ac("…")`, a tag in a comment, or a test's title. Ignore tags in string literals. Recorded as a follow-up of #80. |
| Locked tests | E08-T2's locked tests (`tests/test_evidence_draft.py`) pin the current binding, so changing them needs a **product owner-approved relock**.                  |

## In scope

- Changing how `trace_file` in `.factory/workflow/evidence.py` (and its copy in `kit/`) finds tags, for Python and TS/JS test files.
- New and changed tests for the binding, and the relock of `tests/test_evidence_draft.py`.
- Updating ADR 0025 or adding an ADR that supersedes its binding rule (the Architect decides which).

## Out of scope

- `docs.py check-pr`: it checks the trace's ids against the spec, not where the tags come from. Unchanged.
- Resolving test names by running or importing tests. The trace stays a static, standard-library read.
- Stacks other than Python and TS/JS, which keep listing tags under the file alone.

## Acceptance criteria

- **AC-01** In a Python test file, a tag inside a string literal that isn't a marker (for example a list of ids in a coverage test) binds to no test, and the AC isn't listed for that file because of it.
- **AC-02** In a Python test file, a tag in `@pytest.mark.ac("<EPIC>-AC-nn")` (one or more ids) binds to the test the decorator applies to.
- **AC-03** In a Python or TS/JS test file, a tag in a comment (`#` in Python, `//` or `/* */` in TS/JS) binds to the next test definition, as today.
- **AC-04** In a TS/JS test file, a tag in a test's title (`test("… <EPIC>-AC-nn …", …)` or `it(…)`) binds to that test, and a tag in any other string literal binds to no test.
- **AC-05** A tag in a Python test's docstring binds to that test.
- **AC-06** Text that looks like a comment marker inside a string (for example `"# E31-AC-01"`) is treated as a string, not a comment, so it binds to nothing.
- **AC-07** Run on the E08-T5 locked files, `evidence.py` no longer traces E08 AC-17 or AC-19 to `test_evidence_py_is_standard_library_only`.
- **AC-08** `tests/test_evidence_draft.py` is relocked with the product owner's approval recorded in the lock record, and the gate passes on it.
- **AC-09** `evidence.py` stays standard library only. ruff, `ruff format --check` and `mypy --strict` pass, and `kit/.factory/workflow/evidence.py` matches `.factory/workflow/evidence.py`.

## Assumptions (to confirm with approval)

1. **Docstrings count as a marker (AC-05).** A test's docstring is its title in Python, so I've treated it like a TS title. Option: don't count docstrings, so Python only binds marks and comments.
2. **The pytest mark is named `ac`** and takes the full tag, `@pytest.mark.ac("E31-AC-01")`. The kit registers the mark so pytest doesn't warn. Option: a different name, or the bare `AC-01`.
3. **Python is read with the standard `tokenize` module,** so strings and comments are told apart exactly. TS/JS has no standard-library parser, so a small scanner skips strings, template literals and comments. This is a hint for the Architect, not a constraint.
4. **Comments still bind to the next test,** as today, so existing tagged tests across the repo keep their trace without edits.
5. **The issue is #82,** the live job's issue (E13 decision 11). Correct it if E31 has its own issue.
