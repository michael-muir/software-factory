+++
name = "tests"
title = "Tests standards pack"
prefix = "TST"
applies_to = ["*"]

[[sources]]
title = "Software Engineering at Google, chapters 11 to 13"
url = "https://abseil.io/resources/swe-book/html/"
licence = "CC-BY-NC-ND-4.0: cited, never quoted"

[[sources]]
title = "Software Factory docs"
url = "https://github.com/michael-muir/software-factory/blob/main/"
licence = "Apache-2.0"
+++

# Tests standards pack

Rules a reviewer judges in tests, in any language. It applies to every change, because a change without tests is a finding too. Each rule is in our own words and links the section of the source it comes from. Cite a rule by its id in a finding. Severity follows ADR 0037: `blocker` for unsafe or incorrect code, `major` for code that misleads or is hard to change, `minor` for readability.

## Left to the tools

The gate's format and lint checks own how test code is laid out, and its tests, coverage and mutation checks prove the tests pass and bite. This pack covers what a reviewer has to judge: whether the tests test the right thing.

## Rules

| Rule id | Severity | Rule                                                                                                                  | Why/example                                                              | Source                                                                                                                                                                |
| ------- | -------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TST-001 | blocker  | A test never sleeps to wait for something. It waits on a condition with a timeout, or uses a fake clock.              | Sleeps make tests slow, and flaky on a busy machine.                     | [SWE at Google: Testing Overview](https://abseil.io/resources/swe-book/html/ch11.html)                                                                                |
| TST-002 | blocker  | Tests don't depend on each other's order or shared state. Each one sets up what it needs.                             | An order-dependent test fails when it's run alone, or in parallel.       | [SWE at Google: Testing Overview](https://abseil.io/resources/swe-book/html/ch11.html)                                                                                |
| TST-003 | blocker  | Every test asserts on an outcome the change could break.                                                              | A test that can't fail proves nothing and hides the gap.                 | [SWE at Google: Unit Testing](https://abseil.io/resources/swe-book/html/ch12.html)                                                                                    |
| TST-004 | blocker  | Don't edit a locked test to make it pass. Report it, and relock only with a human's approval.                         | The author never grades the work.                                        | [Software Factory: ADR 0018, test locks](https://github.com/michael-muir/software-factory/blob/main/docs/adr/0018-test-locks-are-hash-records-checked-by-the-gate.md) |
| TST-005 | major    | Test behaviour through public APIs, not implementation details.                                                       | Tests that reach into internals break on every refactor.                 | [SWE at Google: Unit Testing](https://abseil.io/resources/swe-book/html/ch12.html)                                                                                    |
| TST-006 | major    | Test state, not interactions: assert on results rather than on which calls happened inside.                           | Interaction checks pin the implementation, not the behaviour.            | [SWE at Google: Test Doubles](https://abseil.io/resources/swe-book/html/ch13.html)                                                                                    |
| TST-007 | major    | Prefer real implementations, then fakes, then mocks.                                                                  | Each step away from the real thing tests less of it.                     | [SWE at Google: Test Doubles](https://abseil.io/resources/swe-book/html/ch13.html)                                                                                    |
| TST-008 | major    | Test one behaviour per test, and name the test for that behaviour.                                                    | A failure then names what broke.                                         | [SWE at Google: Unit Testing](https://abseil.io/resources/swe-book/html/ch12.html)                                                                                    |
| TST-009 | major    | Tests that need the network or real services are marked as such, and skip with a reason where those aren't available. | Unmarked, they fail for reasons that have nothing to do with the change. | [SWE at Google: Testing Overview](https://abseil.io/resources/swe-book/html/ch11.html)                                                                                |
| TST-010 | major    | Every acceptance criterion has at least one test tagged with its id.                                                  | The PR's evidence traces each criterion to its tests.                    | [Software Factory: E05 spec](https://github.com/michael-muir/software-factory/blob/main/docs/specs/E05-gate-engine.md)                                                |
| TST-011 | major    | A bug fix adds a regression test that fails without the fix.                                                          | The bug can't come back unnoticed.                                       | [Software Factory: debugging skill](https://github.com/michael-muir/software-factory/blob/main/.factory/skills/debugging/SKILL.md)                                    |
| TST-012 | minor    | Keep logic out of tests: no loops or conditionals that decide what to assert.                                         | Logic in a test needs its own tests.                                     | [SWE at Google: Unit Testing](https://abseil.io/resources/swe-book/html/ch12.html)                                                                                    |
| TST-013 | minor    | Failure messages say what was expected and what happened.                                                             | The reader can act on a failure without rerunning it.                    | [SWE at Google: Unit Testing](https://abseil.io/resources/swe-book/html/ch12.html)                                                                                    |
| TST-014 | minor    | Prefer clear tests to clever ones: repeat setup in a test when that makes it readable on its own.                     | A test is read far more often than it's written.                         | [SWE at Google: Unit Testing](https://abseil.io/resources/swe-book/html/ch12.html)                                                                                    |
| TST-015 | minor    | Name a test as a sentence about the behaviour, such as `test_a_missing_file_is_reported`.                             | The test list reads as a specification.                                  | [SWE at Google: Unit Testing](https://abseil.io/resources/swe-book/html/ch12.html)                                                                                    |
| TST-016 | minor    | Assert only what the test is about, and leave incidental details out.                                                 | Over-specified tests break on unrelated changes.                         | [SWE at Google: Unit Testing](https://abseil.io/resources/swe-book/html/ch12.html)                                                                                    |
