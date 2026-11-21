"""E13/T1: each stage's exit check, one passing case and one failing case per condition.

Covers E13 AC-04 (in-process). The conditions come from the E13 spec ("The stages", "Passes when")
and the design note ("The checks"), not from the implementation: a check reads committed files
and history only, and returns problems naming the stage and the file or commit (ADR 0040).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import pipeline
from tests._pipeline import (
    CHANGELOG,
    DESIGN_REL,
    EPIC,
    LOCK_REL,
    REVIEWERS,
    SPEC_REL,
    TASK,
    TASK_REL,
    TEST_REL,
    TESTS,
    commit,
    design_text,
    gate_report,
    git,
    head,
    lock_tests,
    plan_and_slice_base,
    plan_files,
    pr_body,
    repo,
    spec_text,
    task_text,
    write,
)

AC = "E13-AC-04"


def check(stage: str, root: Path, **fields: Any) -> list[pipeline.Problem]:
    fields.setdefault("epic", EPIC)
    problems = pipeline.check(stage, pipeline.Checkout(root=root, **fields))
    assert all(p.where == stage for p in problems), problems
    return problems


def base_of(root: Path) -> str:
    return head(root)


# --- spec ---------------------------------------------------------------------------------------


@pytest.mark.ac(AC)
def test_spec_passes_when_committed_lint_clean_and_with_acs(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    commit(root, {SPEC_REL: spec_text()})
    assert check("spec", root, base=base) == []


@pytest.mark.ac(AC)
def test_spec_fails_with_no_spec(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    commit(root, {"notes.md": "no spec\n"})
    problems = check("spec", root, base=base)
    assert problems and any("docs/specs" in p.path for p in problems)


@pytest.mark.ac(AC)
def test_spec_fails_with_two_specs_for_the_epic(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    commit(root, {SPEC_REL: spec_text(), "docs/specs/E31-other.md": spec_text()})
    assert check("spec", root, base=base)


@pytest.mark.ac(AC)
def test_a_spec_for_another_epic_does_not_count(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    commit(root, {"docs/specs/E32-other.md": spec_text(epic="E32")})
    assert check("spec", root, base=base)


@pytest.mark.ac(AC)
def test_spec_fails_when_only_written_not_committed(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    write(root, {SPEC_REL: spec_text()})
    assert check("spec", root, base=base)


@pytest.mark.ac(AC)
def test_spec_fails_when_not_changed_since_the_base(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = commit(root, {SPEC_REL: spec_text()})
    commit(root, {"notes.md": "later\n"})
    problems = check("spec", root, base=base)
    assert [p.path for p in problems] == [SPEC_REL]


@pytest.mark.ac(AC)
def test_spec_fails_docs_check_without_acs(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    commit(root, {SPEC_REL: spec_text(acs=())})
    problems = check("spec", root, base=base)
    assert problems and all(p.path == SPEC_REL for p in problems)


@pytest.mark.ac(AC)
def test_spec_fails_docs_check_with_a_missing_heading(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    commit(root, {SPEC_REL: spec_text().replace("## Out of scope", "## Outside")})
    problems = check("spec", root, base=base)
    assert problems and "Out of scope" in str(problems)


@pytest.mark.ac(AC)
def test_spec_reads_the_committed_text_not_the_disk(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    commit(root, {SPEC_REL: spec_text(acs=())})
    write(root, {SPEC_REL: spec_text()})  # fixed on disk only
    assert check("spec", root, base=base)


# --- design -------------------------------------------------------------------------------------


@pytest.mark.ac(AC)
def test_design_passes_with_a_design_and_tasks_covering_every_ac(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    commit(root, plan_files())
    assert check("design", root, base=base) == []


@pytest.mark.ac(AC)
def test_design_accepts_an_ac_range_in_a_task(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    files = plan_files(acs=("AC-01", "AC-02", "AC-03"))
    files[TASK_REL] = task_text(acs="E31 AC-01 to AC-03.")
    commit(root, files)
    assert check("design", root, base=base) == []


@pytest.mark.ac(AC)
def test_design_fails_with_no_design_note(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    files = plan_files()
    del files[DESIGN_REL]
    commit(root, files)
    problems = check("design", root, base=base)
    assert problems and any("docs/design" in p.path for p in problems)


@pytest.mark.ac(AC)
def test_design_fails_when_the_note_is_not_changed_since_the_base(tmp_path: Path) -> None:
    root = repo(tmp_path)
    files = plan_files()
    base = commit(root, {DESIGN_REL: files[DESIGN_REL]})
    commit(root, {SPEC_REL: files[SPEC_REL], TASK_REL: files[TASK_REL]})
    problems = check("design", root, base=base)
    assert [p.path for p in problems] == [DESIGN_REL]


@pytest.mark.ac(AC)
def test_design_fails_docs_check_on_a_broken_spec_link(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    files = plan_files()
    files[DESIGN_REL] = design_text(spec_link="../specs/E31-missing.md")
    commit(root, files)
    problems = check("design", root, base=base)
    assert problems and all(p.path == DESIGN_REL for p in problems)


@pytest.mark.ac(AC)
def test_design_fails_with_no_task_files(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    files = plan_files()
    del files[TASK_REL]
    commit(root, files)
    problems = check("design", root, base=base)
    assert problems and any(".agentic/tasks" in p.path for p in problems)


@pytest.mark.ac(AC)
def test_design_fails_with_an_invalid_task_file(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    files = plan_files()
    files[TASK_REL] = task_text().replace('status = "in-progress"', 'status = "busy"')
    commit(root, files)
    problems = check("design", root, base=base)
    assert [p.path for p in problems] == [TASK_REL]


@pytest.mark.ac(AC)
def test_design_fails_when_a_task_names_an_ac_the_spec_lacks(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    files = plan_files()
    files[TASK_REL] = task_text(acs="E31 AC-01, AC-02, AC-07.")
    commit(root, files)
    problems = check("design", root, base=base)
    assert len(problems) == 1 and "AC-07" in problems[0].message


@pytest.mark.ac(AC)
def test_design_fails_when_a_spec_ac_is_in_no_task(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    files = plan_files(acs=("AC-01", "AC-02", "AC-03"))
    commit(root, files)
    problems = check("design", root, base=base)
    assert len(problems) == 1 and "AC-03" in problems[0].message


@pytest.mark.ac(AC)
def test_design_fails_when_a_task_names_no_ac(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    files = plan_files()
    files[".agentic/tasks/E31-T2.md"] = task_text("E31-T2", acs="Nothing yet.")
    commit(root, files)
    problems = check("design", root, base=base)
    assert [p.path for p in problems] == [".agentic/tasks/E31-T2.md"]


@pytest.mark.ac(AC)
def test_design_counts_tasks_of_its_own_epic_only(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = base_of(root)
    files = plan_files()
    files[".agentic/tasks/E32-T1.md"] = task_text("E32-T1", acs="E32 AC-09.")
    commit(root, files)
    assert check("design", root, base=base) == []


# --- test ---------------------------------------------------------------------------------------


@pytest.mark.ac(AC)
def test_test_passes_with_locked_tagged_tests_before_any_code(tmp_path: Path) -> None:
    root, base = plan_and_slice_base(tmp_path)
    lock_tests(root)
    assert check("test", root, task=TASK, base=base) == []


@pytest.mark.ac(AC)
def test_test_fails_with_no_lock_record(tmp_path: Path) -> None:
    root, base = plan_and_slice_base(tmp_path)
    commit(root, {TEST_REL: TESTS})
    problems = check("test", root, task=TASK, base=base)
    assert problems and any(p.path == LOCK_REL for p in problems)


@pytest.mark.ac(AC)
def test_test_fails_when_the_lock_record_is_not_committed(tmp_path: Path) -> None:
    import agents

    root, base = plan_and_slice_base(tmp_path)
    commit(root, {TEST_REL: TESTS})
    agents.lock(root, TASK, [root / TEST_REL])
    problems = check("test", root, task=TASK, base=base)
    assert problems and any(p.path == LOCK_REL for p in problems)


@pytest.mark.ac(AC)
def test_test_fails_when_a_task_ac_is_not_tagged_in_a_locked_file(tmp_path: Path) -> None:
    root, base = plan_and_slice_base(tmp_path)
    lock_tests(root, {TEST_REL: TESTS.replace("E31-AC-02", "E31-AC-01")})
    problems = check("test", root, task=TASK, base=base)
    assert len(problems) == 1 and "AC-02" in problems[0].message


@pytest.mark.ac(AC)
def test_test_fails_when_code_is_committed_before_the_lock(tmp_path: Path) -> None:
    root, base = plan_and_slice_base(tmp_path)
    early = commit(root, {"widgets.py": "WIDGETS = 1\n"}, "feat: too early")
    lock_tests(root)
    problems = check("test", root, task=TASK, base=base)
    assert len(problems) == 1 and problems[0].path.startswith(early[:7])


@pytest.mark.ac(AC)
def test_test_allows_state_file_commits_before_the_lock(tmp_path: Path) -> None:
    root, base = plan_and_slice_base(tmp_path)
    commit(root, {".agentic/handoffs/note.md": "x\n"}, "chore: a handoff")
    lock_tests(root)
    assert check("test", root, task=TASK, base=base) == []


# --- build --------------------------------------------------------------------------------------


def built(tmp_path: Path) -> tuple[Path, str]:
    root, base = plan_and_slice_base(tmp_path)
    lock_tests(root)
    return root, base


@pytest.mark.ac(AC)
def test_build_passes_with_a_commit_after_the_lock_and_a_clean_tree(tmp_path: Path) -> None:
    root, base = built(tmp_path)
    commit(root, {"widgets.py": "WIDGETS = 2\n"}, "feat: widgets")
    assert check("build", root, task=TASK, base=base) == []


@pytest.mark.ac(AC)
def test_build_fails_with_no_commit_after_the_lock(tmp_path: Path) -> None:
    root, base = built(tmp_path)
    assert check("build", root, task=TASK, base=base)


@pytest.mark.ac(AC)
def test_build_fails_with_a_dirty_tree(tmp_path: Path) -> None:
    root, base = built(tmp_path)
    commit(root, {"widgets.py": "WIDGETS = 2\n"})
    write(root, {"widgets.py": "WIDGETS = 3\n"})
    problems = check("build", root, task=TASK, base=base)
    assert len(problems) == 1 and "widgets.py" in str(problems[0])


@pytest.mark.ac(AC)
def test_build_fails_when_a_locked_test_changed(tmp_path: Path) -> None:
    root, base = built(tmp_path)
    commit(root, {TEST_REL: TESTS.replace("assert False", "assert True")}, "weaken")
    problems = check("build", root, task=TASK, base=base)
    assert len(problems) == 1 and TEST_REL in str(problems[0])


@pytest.mark.ac(AC)
def test_build_fails_without_a_lock_record(tmp_path: Path) -> None:
    root, base = plan_and_slice_base(tmp_path)
    commit(root, {"widgets.py": "WIDGETS = 2\n"})
    assert check("build", root, task=TASK, base=base)


# --- gate ---------------------------------------------------------------------------------------


@pytest.mark.ac(AC)
def test_gate_passes_with_a_pass_report_for_the_head_from_a_clean_tree(tmp_path: Path) -> None:
    root = repo(tmp_path)
    report = gate_report(head(root))
    assert check("gate", root, task=TASK, gate_report=report) == []


@pytest.mark.ac(AC)
def test_gate_fails_with_no_report(tmp_path: Path) -> None:
    assert check("gate", repo(tmp_path), task=TASK, gate_report=None)


@pytest.mark.ac(AC)
def test_gate_fails_on_a_red_report_naming_the_failed_check(tmp_path: Path) -> None:
    root = repo(tmp_path)
    problems = check("gate", root, task=TASK, gate_report=gate_report(head(root), verdict="fail"))
    assert len(problems) == 1 and "tests" in problems[0].message


@pytest.mark.ac(AC)
def test_gate_fails_on_a_report_for_another_commit(tmp_path: Path) -> None:
    root = repo(tmp_path)
    old = head(root)
    commit(root, {"widgets.py": "WIDGETS = 2\n"})
    problems = check("gate", root, task=TASK, gate_report=gate_report(old))
    assert len(problems) == 1


@pytest.mark.ac(AC)
def test_gate_fails_on_a_report_from_a_dirty_tree(tmp_path: Path) -> None:
    root = repo(tmp_path)
    problems = check("gate", root, task=TASK, gate_report=gate_report(head(root), dirty=True))
    assert len(problems) == 1


# --- review -------------------------------------------------------------------------------------


def reviewed(tmp_path: Path, **task: Any) -> Path:
    root = repo(tmp_path)
    task.setdefault("review_round", 1)
    commit(root, {TASK_REL: task_text(**task)})
    return root


MAJOR_OPEN = {"id": "F1", "severity": "major", "status": "open", "summary": "x.py:1 wrong"}


@pytest.mark.ac(AC)
def test_review_passes_after_all_six_sessions_in_round_one(tmp_path: Path) -> None:
    root = reviewed(tmp_path)
    assert check("review", root, task=TASK, reviews=REVIEWERS) == []


@pytest.mark.ac(AC)
@pytest.mark.parametrize("missing", REVIEWERS)
def test_review_fails_when_a_session_has_not_run(tmp_path: Path, missing: str) -> None:
    root = reviewed(tmp_path)
    reviews = tuple(role for role in REVIEWERS if role != missing)
    problems = check("review", root, task=TASK, reviews=reviews)
    assert len(problems) == 1 and missing in problems[0].message


@pytest.mark.ac(AC)
def test_review_fails_when_the_review_round_is_not_one(tmp_path: Path) -> None:
    root = reviewed(tmp_path, review_round=0)
    assert len(check("review", root, task=TASK, reviews=REVIEWERS)) == 1


@pytest.mark.ac(AC)
@pytest.mark.parametrize("severity", ["blocker", "major"])
def test_review_fails_on_an_open_blocker_or_major_finding(tmp_path: Path, severity: str) -> None:
    root = reviewed(tmp_path, findings=[{**MAJOR_OPEN, "severity": severity}])
    problems = check("review", root, task=TASK, reviews=REVIEWERS)
    assert len(problems) == 1 and "F1" in problems[0].message


@pytest.mark.ac(AC)
@pytest.mark.parametrize(
    "finding",
    [
        {**MAJOR_OPEN, "severity": "minor"},
        {**MAJOR_OPEN, "status": "fixed"},
        {**MAJOR_OPEN, "status": "wont-fix"},
    ],
)
def test_review_passes_with_minor_or_closed_findings(
    tmp_path: Path, finding: dict[str, str]
) -> None:
    root = reviewed(tmp_path, findings=[finding])
    assert check("review", root, task=TASK, reviews=REVIEWERS) == []


@pytest.mark.ac(AC)
def test_review_reads_the_committed_task_file(tmp_path: Path) -> None:
    root = reviewed(tmp_path, findings=[MAJOR_OPEN])
    write(root, {TASK_REL: task_text(review_round=1)})  # fixed on disk only
    assert check("review", root, task=TASK, reviews=REVIEWERS)


# --- docs ---------------------------------------------------------------------------------------


def unreleased(line: str) -> str:
    return CHANGELOG.replace("## [Unreleased]\n", f"## [Unreleased]\n\n{line}\n")


@pytest.mark.ac(AC)
def test_docs_passes_with_an_unreleased_entry_and_a_green_gate_on_the_head(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = head(root)
    commit(root, {"CHANGELOG.md": unreleased("- Widgets.")})
    report = gate_report(head(root))
    assert check("docs", root, task=TASK, base=base, gate_report=report) == []


@pytest.mark.ac(AC)
def test_docs_fails_with_no_changelog_change(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = head(root)
    commit(root, {"README.md": "more\n"})
    problems = check("docs", root, task=TASK, base=base, gate_report=gate_report(head(root)))
    assert len(problems) == 1 and "CHANGELOG.md" in str(problems[0])


@pytest.mark.ac(AC)
def test_docs_fails_when_the_entry_is_outside_unreleased(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = head(root)
    commit(root, {"CHANGELOG.md": CHANGELOG + "- An old note.\n"})
    problems = check("docs", root, task=TASK, base=base, gate_report=gate_report(head(root)))
    assert len(problems) == 1


@pytest.mark.ac(AC)
def test_docs_fails_when_the_gate_report_is_for_an_older_commit(tmp_path: Path) -> None:
    root = repo(tmp_path)
    base = head(root)
    report = gate_report(base)
    commit(root, {"CHANGELOG.md": unreleased("- Widgets.")})
    assert len(check("docs", root, task=TASK, base=base, gate_report=report)) == 1


# --- ship ---------------------------------------------------------------------------------------


def shippable(tmp_path: Path) -> tuple[Path, str]:
    root = repo(tmp_path)
    base = head(root)
    commit(root, {SPEC_REL: spec_text()})
    return root, base


@pytest.mark.ac(AC)
def test_ship_passes_with_a_strict_body_for_the_branch_and_an_open_pr(tmp_path: Path) -> None:
    root, base = shippable(tmp_path)
    body = pr_body(head(root))
    assert check("ship", root, task=TASK, base=base, pr_body=body, pr="17") == []


@pytest.mark.ac(AC)
def test_ship_fails_with_no_body(tmp_path: Path) -> None:
    root, base = shippable(tmp_path)
    assert len(check("ship", root, task=TASK, base=base, pr_body=None, pr="17")) == 1


@pytest.mark.ac(AC)
def test_ship_fails_when_the_body_fails_check_pr_strict(tmp_path: Path) -> None:
    root, base = shippable(tmp_path)
    body = pr_body(head(root)).replace("- Widgets.", "- TODO(author): what changes")
    assert check("ship", root, task=TASK, base=base, pr_body=body, pr="17")


@pytest.mark.ac(AC)
def test_ship_fails_when_the_evidence_is_for_a_commit_not_on_the_branch(tmp_path: Path) -> None:
    root, base = shippable(tmp_path)
    body = pr_body(base)
    assert check("ship", root, task=TASK, base=base, pr_body=body, pr="17")


@pytest.mark.ac(AC)
def test_ship_fails_with_no_pr_opened(tmp_path: Path) -> None:
    root, base = shippable(tmp_path)
    problems = check("ship", root, task=TASK, base=base, pr_body=pr_body(head(root)), pr="")
    assert len(problems) == 1


# --- learn --------------------------------------------------------------------------------------

HANDOFF = "## Done\n\n- Widgets.\n\n## Next\n\n- Nothing.\n\n## Open questions\n\nNone.\n"


@pytest.mark.ac(AC)
def test_learn_passes_when_every_task_merged_and_the_summary_is_written(tmp_path: Path) -> None:
    root = repo(tmp_path)
    tasks = (("E31-T1", True), ("E31-T2", True))
    assert check("learn", root, tasks=tasks, summary={"handoff": HANDOFF}) == []


@pytest.mark.ac(AC)
def test_learn_fails_while_a_task_is_unmerged(tmp_path: Path) -> None:
    root = repo(tmp_path)
    tasks = (("E31-T1", True), ("E31-T2", False))
    problems = check("learn", root, tasks=tasks, summary={"handoff": HANDOFF})
    assert len(problems) == 1 and "E31-T2" in str(problems[0])


@pytest.mark.ac(AC)
def test_learn_fails_with_no_tasks(tmp_path: Path) -> None:
    assert check("learn", repo(tmp_path), tasks=(), summary={"handoff": HANDOFF})


@pytest.mark.ac(AC)
def test_learn_fails_with_no_summary(tmp_path: Path) -> None:
    assert len(check("learn", repo(tmp_path), tasks=(("E31-T1", True),), summary=None)) == 1


@pytest.mark.ac(AC)
@pytest.mark.parametrize("heading", ["## Done", "## Next", "## Open questions"])
def test_learn_fails_when_the_handoff_lacks_a_heading(tmp_path: Path, heading: str) -> None:
    summary = {"handoff": HANDOFF.replace(heading, "## Other")}
    problems = check("learn", repo(tmp_path), tasks=(("E31-T1", True),), summary=summary)
    assert len(problems) == 1 and heading in problems[0].message


# --- every stage --------------------------------------------------------------------------------


@pytest.mark.ac(AC)
def test_an_unknown_stage_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="stage"):
        pipeline.check("deploy", pipeline.Checkout(root=repo(tmp_path), epic=EPIC))


@pytest.mark.ac(AC)
def test_a_check_changes_nothing(tmp_path: Path) -> None:
    root, base = plan_and_slice_base(tmp_path)
    lock_tests(root)
    write(root, {"scratch.txt": "uncommitted\n"})
    before = (head(root), git(root, "status", "--porcelain"))
    for stage in ("spec", "design", "test", "build", "gate", "docs"):
        pipeline.check(stage, pipeline.Checkout(root=root, epic=EPIC, task=TASK, base=base))
    assert (head(root), git(root, "status", "--porcelain")) == before
