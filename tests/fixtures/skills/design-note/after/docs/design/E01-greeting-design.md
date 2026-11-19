# E01 · Greeting design note

Spec: [E01 spec](../specs/E01-greeting.md) · Issue: [#1](https://example.com/issues/1)
Status: **Accepted by the product owner, 19 Nov 2026** · ADRs: [0001](../adr/0001-greet-is-a-pure-function.md)

## Summary

One pure function, `greet(name: str) -> str`, in `src/greet.py`, with no I/O, so the CLI and the tests call it the same way (ADR 0001).

## Source layout

```text
src/greet.py         # greet()
tests/test_greet.py  # one test per AC
```

## Test seams

Call `greet` directly with each AC's input and compare the string.

## Vertical slices

| Task | Slice | ACs |
| --- | --- | --- |
| T1 | `greet` with names, case and the empty name | AC-01 to AC-03 |

## Risks

- None worth a slice of its own: the function is small and pure.
