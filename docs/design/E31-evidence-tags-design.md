# E31 · Evidence tags bind only real markers design note

Spec: [E31 spec](../specs/E31-evidence-tags.md) · Issue: [#82](https://github.com/michael-muir/software-factory/issues/82)
Status: **Accepted by michael-muir, 24 Nov 2026** · ADRs: [0054](../adr/0054-evidence-tags-bind-only-real-markers-read-with-a-lexer.md)

## Summary

`trace_file` in `.factory/workflow/evidence.py` stops searching raw text. It lexes the file first, then looks for tags only in markers (ADR 0054, which supersedes ADR 0025's binding rule):

- **Python** is read with `tokenize`. Tags bind from comments (to the next test), from `@pytest.mark.ac(...)` arguments (to the decorated test) and from a test's docstring (to that test).
- **TS/JS** is read by a small scanner that tells strings, template literals and comments apart. Tags bind from comments (to the next test) and from the title argument of `test(`/`it(` (to that test).

A tag anywhere else is ignored. Other stacks keep listing tags under the file alone. `trace_file`'s signature and its `Traced` result don't change, so the drafting code around it is untouched.

## Source layout

```text
.factory/workflow/evidence.py        # trace_file, _python_markers (tokenize), _ts_markers (scanner)
kit/.factory/workflow/evidence.py    # byte-identical copy
kit/pyproject or pytest config       # registers the `ac` mark
tests/test_evidence_tags.py          # new: E31 binding tests, per stack
tests/test_evidence_draft.py         # relocked: E08-T2 tests updated to the new rule
docs/adr/0054-…                      # the binding rule
```

## Test seams

- **In-process calls** to `trace_file(path, text, "E31")` with small inline sources. Each AC gets fixtures covering the marker, the string-literal case, and the comment-like text inside a string (AC-01 to AC-06).
- **The E08-T5 locked files,** read from the repo at their locked commit and passed to `trace_file` with epic `E08`, so the test asserts AC-17 and AC-19 aren't bound to `test_evidence_py_is_standard_library_only` (AC-07).
- **The gate and lock record** for the relock: `agents.py` lock verification on `tests/test_evidence_draft.py`, with the product owner's approval in the record (AC-08).
- **Hygiene:** the existing standard-library import check, ruff, `ruff format --check`, `mypy --strict` and the kit-copy equality test (AC-09).

## Vertical slices

| Task | Slice                                                                                    | ACs                                      |
| ---- | ---------------------------------------------------------------------------------------- | ---------------------------------------- |
| T1   | Python binding by `tokenize`, the E08-T5 regression and the relock of the E08-T2 tests   | AC-01, AC-02, AC-03, AC-05, AC-06, AC-07, AC-08 |
| T2   | The TS/JS scanner, the `ac` mark registration and kit parity                             | AC-04, AC-09                             |

T1 also covers the Python half of AC-03 and AC-06. T2 adds the TS/JS half of both and tests it, under the same AC tags. T1 has to keep the kit copy in step too, but T2 owns AC-09's tests.

## Risks

- **The relock hides a regression.** Only the tests that pin the old binding change, and the PR lists each changed assertion for the product owner.
- **Existing tagged tests lose their trace.** Comments still bind as before. T1 runs the new trace over every locked file in the repo and reports any AC that drops out, to be fixed with a mark or comment.
- **The TS scanner gets regex literals or JSX wrong.** Its only job is to find strings and comments. A misread can only drop or add a tag, never crash, and test files rarely use regex literals near tags.
- **A Python file that doesn't tokenize.** It falls back to listing comment-free tags under the file alone, and never raises.
